"""Autonomy planner: allowlist, guardrails, LLM/fallback decisions, audit trail."""

import asyncio
from datetime import datetime, timezone

import pytest

from packages.agents.orchestration_agents import autonomy_planner as ap
from packages.agents.orchestration_agents.autonomy_planner import (
    ALLOWLIST, AutonomyPlannerAgent, Plan, PlannedAction, PlanRejected, apply_guardrails, fallback_plan,
    load_planner_config, sanitize_params, workflow_id_for,
)
from packages.infrastructure.llm.base import LLMResult, LLMUnavailable

CFG = {"enabled": True, "max_actions_per_cycle": 3, "max_running_per_queue": 2, "max_running_total": 6,
       "stale_hours": 24, "dlq_replay_threshold": 100, "regions": ["US-CA", "US-TX"],
       "categories": ["restaurant", "hotel"], "place_batch": 50}
NOW = datetime(2026, 11, 16, 9, 30, tzinfo=timezone.utc)


def act(workflow, params=None, priority=5, reason="r"):
    return PlannedAction(workflow=workflow, params=params or {}, priority=priority, reason=reason)


def run(coro):
    return asyncio.run(coro)


# ── allowlist and parameter validation ───────────────────────────────────────

def test_unknown_workflow_is_rejected():
    with pytest.raises(PlanRejected, match="not in the allowlist"):
        sanitize_params("DropAllTablesWorkflow", {})


def test_unknown_parameter_is_rejected():
    with pytest.raises(PlanRejected, match="not allowed"):
        sanitize_params("DLQReplayWorkflow", {"limit": 5, "shell": "rm -rf /"})


def test_oversized_numbers_are_clamped():
    assert sanitize_params("PlaceDeepExtractionWorkflow", {"max_places": 10**6})["max_places"] == 500
    assert sanitize_params("DLQReplayWorkflow", {"limit": 99999})["limit"] == 1000
    assert sanitize_params("PlaceDeepExtractionWorkflow", {"max_places": -5})["max_places"] == 1


def test_malformed_values_are_rejected():
    for wf, p in [("PlaceDeepExtractionWorkflow", {"region": "US-CA; DROP TABLE"}),
                  ("GMapsExtractionWorkflow", {"regions": "US-CA"}),
                  ("GMapsExtractionWorkflow", {"regions": ["../etc/passwd"]}),
                  ("FederalIngestionWorkflow", {"mode": "destroy"}),
                  ("EmailEnrichmentWorkflow", {"probe_smtp": "maybe"}),
                  ("DLQReplayWorkflow", {"limit": "many"})]:
        with pytest.raises(PlanRejected):
            sanitize_params(wf, p)


def test_null_parameters_from_the_llm_are_treated_as_unset():
    """Found in a live run: the model sends {"category": null, "max_reviews": null}."""
    clean = sanitize_params("PlaceDeepExtractionWorkflow",
                            {"region": "US-CA", "category": None, "max_reviews": None, "max_places": 5})
    assert clean == {"region": "US-CA", "max_places": 5}
    with pytest.raises(PlanRejected, match="not allowed"):
        sanitize_params("PlaceDeepExtractionWorkflow", {"shell": None})  # unknown keys still rejected


def test_list_parameters_are_capped_at_five():
    regions = [f"US-{c}" for c in ("CA", "TX", "NY", "FL", "IL", "PA", "OH")]
    assert len(sanitize_params("GMapsExtractionWorkflow", {"regions": regions})["regions"]) == 5


def test_every_allowlisted_workflow_has_a_queue_and_known_name():
    for name, spec in ALLOWLIST.items():
        assert spec.queue and name.endswith("Workflow")


# ── guardrails ───────────────────────────────────────────────────────────────

def test_non_allowlisted_action_is_rejected_and_good_one_is_kept():
    plan = Plan(actions=[act("EvilWorkflow"), act("DLQReplayWorkflow", {"limit": 10, "mode": "auto"})])
    res = apply_guardrails(plan, CFG, [], NOW)
    assert [a["workflow"] for a in res.approved] == ["DLQReplayWorkflow"]
    assert "allowlist" in res.rejected[0]["rejected_because"]


def test_oversized_batch_is_clamped_not_started_oversized():
    res = apply_guardrails(Plan(actions=[act("PlaceDeepExtractionWorkflow", {"max_places": 99999})]), CFG, [], NOW)
    assert res.approved[0]["params"]["max_places"] == 500


def test_full_federal_refresh_and_osm_need_human_approval():
    plan = Plan(actions=[act("FederalIngestionWorkflow", {"mode": "full"}),
                         act("OSMStateWorkflow", {"scope": "sample", "states": ["Texas"]}),
                         act("FederalIngestionWorkflow", {"mode": "incremental"})])
    res = apply_guardrails(plan, CFG, [], NOW)
    assert [a["params"] for a in res.approved] == [{"mode": "incremental"}]
    assert [r["rejected_because"] for r in res.rejected] == ["needs_approval", "needs_approval"]


def test_workflow_already_running_is_not_started_again():
    running = [{"workflow_type": "DLQReplayWorkflow", "id": "x"}]
    res = apply_guardrails(Plan(actions=[act("DLQReplayWorkflow", {"limit": 5})]), CFG, running, NOW)
    assert res.approved == [] and "already running" in res.rejected[0]["rejected_because"]


def test_duplicate_actions_in_one_plan_start_once():
    a = act("DLQReplayWorkflow", {"limit": 5, "mode": "auto"})
    res = apply_guardrails(Plan(actions=[a, a]), CFG, [], NOW)
    assert len(res.approved) == 1 and len(res.rejected) == 1


def test_max_actions_per_cycle_is_enforced():
    cfg = {**CFG, "max_actions_per_cycle": 1}
    plan = Plan(actions=[act("DLQReplayWorkflow", {"limit": 1}, priority=1),
                         act("PromotionGateWorkflow", priority=2)])
    res = apply_guardrails(plan, cfg, [], NOW)
    assert len(res.approved) == 1 and res.approved[0]["workflow"] == "DLQReplayWorkflow"
    assert "max_actions" in res.rejected[0]["rejected_because"]


def test_global_and_per_queue_caps():
    running = [{"workflow_type": "RevalidationSweepWorkflow"}, {"workflow_type": "PromotionGateWorkflow"}]
    plan = Plan(actions=[act("EmailEnrichmentWorkflow", {"batch_size": 10})])
    cfg_queue = {**CFG, "max_running_per_queue": 2}
    # governance queue is full (2 running); email is a different queue so it passes
    assert apply_guardrails(plan, cfg_queue, running, NOW).approved
    # a third governance workflow is refused by the queue cap
    gov = Plan(actions=[act("RevalidationSweepWorkflow", {"batch_size": 5})])
    full = [{"workflow_type": "PromotionGateWorkflow"}, {"workflow_type": "PromotionGateWorkflow"}]
    assert "queue cap" in apply_guardrails(gov, cfg_queue, full, NOW).rejected[0]["rejected_because"]
    cfg_total = {**CFG, "max_running_total": 2}
    assert "global" in apply_guardrails(plan, cfg_total, running, NOW).rejected[0]["rejected_because"]


def test_workflow_ids_are_deterministic_and_hour_bucketed():
    a = workflow_id_for("DLQReplayWorkflow", {"limit": 1, "mode": "auto"}, NOW)
    assert a == workflow_id_for("DLQReplayWorkflow", {"mode": "auto", "limit": 1}, NOW)
    assert a != workflow_id_for("DLQReplayWorkflow", {"limit": 2, "mode": "auto"}, NOW)
    assert a != workflow_id_for("DLQReplayWorkflow", {"limit": 1, "mode": "auto"},
                                NOW.replace(hour=NOW.hour + 1))
    assert a.startswith("planner-DLQReplayWorkflow-") and a.endswith("2026111609")


# ── deterministic fallback ───────────────────────────────────────────────────

def test_fallback_replays_small_dlq_gap_fills_and_scrapes_missing_places():
    signals = {"dlq_pending": 40, "regions_without_gmaps_data": ["US-TX"], "places_without_deep_data": 12,
               "hours_since_federal_update": 100}
    plan = fallback_plan(signals, CFG)
    assert [a.workflow for a in plan.actions] == [
        "DLQReplayWorkflow", "GMapsExtractionWorkflow", "PlaceDeepExtractionWorkflow", "FederalIngestionWorkflow"]
    # every fallback action must survive the guardrails untouched
    res = apply_guardrails(plan, {**CFG, "max_actions_per_cycle": 10}, [], NOW)
    assert len(res.approved) == 4 and not res.rejected


def test_fallback_does_nothing_when_everything_is_fine():
    signals = {"dlq_pending": 0, "regions_without_gmaps_data": [], "places_without_deep_data": 0,
               "places_with_stale_deep_data": 0, "hours_since_federal_update": 3}
    assert fallback_plan(signals, CFG).actions == []


def test_fallback_leaves_huge_dlq_to_humans():
    assert not any(a.workflow == "DLQReplayWorkflow" for a in fallback_plan({"dlq_pending": 5000}, CFG).actions)


# ── agent cycle ──────────────────────────────────────────────────────────────

class FakePlannerLLM:
    name = "fake"
    model = "fake-model"

    def __init__(self, plan=None, error=None):
        self.plan, self.error, self.calls = plan, error, []

    def chat(self, messages, schema=None, **kw):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return LLMResult(text="{}", provider="fake", model="fake-model", parsed=self.plan)


def make_agent(llm, running=None, signals=None):
    started, saved = [], []

    async def starter(workflow, params, wf_id, queue):
        started.append((workflow, params, wf_id, queue))

    async def running_fetcher():
        return running or []

    agent = AutonomyPlannerAgent(
        llm=llm, starter=starter, running_fetcher=running_fetcher,
        signals_fn=lambda cfg: signals if signals is not None else {"dlq_pending": 0},
        save_fn=lambda rec: saved.append(rec) or 7)
    return agent, started, saved


def test_dry_run_records_the_plan_and_starts_nothing():
    plan = Plan(summary="s", actions=[act("DLQReplayWorkflow", {"limit": 5, "mode": "auto"})])
    agent, started, saved = make_agent(FakePlannerLLM(plan))
    out = run(agent.run_cycle(dry_run=True))
    assert started == [] and out["dry_run"] is True and out["mode"] == "llm"
    assert out["executed"][0]["started"] is False
    assert saved[0]["dry_run"] is True and saved[0]["plan"]["actions"][0]["workflow"] == "DLQReplayWorkflow"
    assert out["decision_id"] == 7


def test_live_cycle_starts_approved_workflows_with_deterministic_ids():
    plan = Plan(actions=[act("PlaceDeepExtractionWorkflow", {"max_places": 20, "with_llm": True})])
    agent, started, saved = make_agent(FakePlannerLLM(plan))
    out = run(agent.run_cycle(dry_run=False))
    wf, params, wf_id, queue = started[0]
    assert wf == "PlaceDeepExtractionWorkflow" and params == {"max_places": 20, "with_llm": True}
    assert wf_id.startswith("planner-PlaceDeepExtractionWorkflow-") and queue == ALLOWLIST[wf].queue
    assert out["executed"][0]["started"] is True and saved[0]["mode"] == "llm"


def test_llm_choosing_forbidden_things_is_contained():
    plan = Plan(actions=[act("EvilWorkflow"), act("FederalIngestionWorkflow", {"mode": "full"}),
                         act("DLQReplayWorkflow", {"limit": 10**9, "mode": "auto"})])
    agent, started, saved = make_agent(FakePlannerLLM(plan))
    out = run(agent.run_cycle(dry_run=False))
    assert [s[0] for s in started] == ["DLQReplayWorkflow"] and started[0][1]["limit"] == 1000
    reasons = " | ".join(r["rejected_because"] for r in out["rejected"])
    assert "allowlist" in reasons and "needs_approval" in reasons


def test_llm_outage_uses_deterministic_rules():
    agent, started, saved = make_agent(FakePlannerLLM(error=LLMUnavailable("no key")),
                                       signals={"dlq_pending": 5})
    out = run(agent.run_cycle(dry_run=False))
    assert out["mode"] == "fallback" and "LLM unavailable" in out["note"]
    assert [s[0] for s in started] == ["DLQReplayWorkflow"] and saved[0]["mode"] == "fallback"


def test_budget_exceeded_also_falls_back():
    from packages.infrastructure.llm.base import LLMBudgetExceeded
    agent, started, saved = make_agent(FakePlannerLLM(error=LLMBudgetExceeded("used up")),
                                       signals={"dlq_pending": 5})
    assert run(agent.run_cycle(dry_run=True))["mode"] == "fallback"


def test_start_failures_and_duplicates_are_reported_not_raised():
    class WorkflowAlreadyStartedError(Exception):
        pass

    async def starter(*a):
        raise WorkflowAlreadyStartedError()

    plan = Plan(actions=[act("DLQReplayWorkflow", {"limit": 5, "mode": "auto"})])
    agent = AutonomyPlannerAgent(llm=FakePlannerLLM(plan), starter=starter,
                                 running_fetcher=lambda: asyncio.sleep(0, result=[]),
                                 signals_fn=lambda cfg: {}, save_fn=lambda rec: 1)
    out = run(agent.run_cycle(dry_run=False))
    assert out["executed"] == [] and "duplicate" in out["rejected"][0]["rejected_because"]


def test_running_workflow_lookup_failure_does_not_stop_the_cycle():
    async def broken():
        raise ConnectionError("temporal down")
    agent = AutonomyPlannerAgent(llm=FakePlannerLLM(Plan()), starter=lambda *a: None, running_fetcher=broken,
                                 signals_fn=lambda cfg: {}, save_fn=lambda rec: 1)
    assert run(agent.run_cycle(dry_run=True))["status"] == "OK"


def test_dry_run_default_follows_env(monkeypatch):
    assert ap.dry_run_default() is False
    monkeypatch.setenv("PLANNER_DRY_RUN", "true")
    assert ap.dry_run_default() is True
    plan = Plan(actions=[act("DLQReplayWorkflow", {"limit": 5, "mode": "auto"})])
    agent, started, _ = make_agent(FakePlannerLLM(plan))
    run(agent.run_cycle())  # no explicit argument -> env decides
    assert started == []


def test_prompt_contains_catalogue_but_no_secrets():
    llm = FakePlannerLLM(Plan())
    agent, _, _ = make_agent(llm)
    run(agent.run_cycle(dry_run=True))
    text = " ".join(m["content"] for m in llm.calls[0])
    assert "PlaceDeepExtractionWorkflow" in text and "allowed_workflows" in text
    assert "gsk_" not in text and "password" not in text.lower()


def test_config_loads_from_yaml_with_env_overrides(monkeypatch):
    cfg = load_planner_config()
    assert cfg["max_actions_per_cycle"] == 3 and "US-CA" in cfg["regions"]
    monkeypatch.setenv("PLANNER_MAX_ACTIONS", "9")
    assert load_planner_config()["max_actions_per_cycle"] == 9


# ── database ─────────────────────────────────────────────────────────────────

def test_signals_read_real_tables(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO staging_dataextraction.staging_companies (id, name, state_code, source, raw_payload) "
                    "VALUES ('gmaps_1','A','CA','GOOGLE_MAPS','{\"cid\":\"1\"}'::jsonb), "
                    "('gmaps_2','B','CA','GOOGLE_MAPS','{\"cid\":\"2\"}'::jsonb)")
    db.commit()
    sig = ap.gather_signals(CFG, get_conn=lambda: db, release=lambda c: None)
    assert sig["gmaps_places_total"] == 2 and sig["places_without_deep_data"] == 2
    assert sig["regions_without_gmaps_data"] == ["US-TX"]
    assert sig["dlq_pending"] is None  # table missing in the test DB: probe failed safely, others still worked
    assert sig["reviews_total"] == 0


def test_decision_is_written_to_the_audit_table(db, cursor_ctx, monkeypatch):
    monkeypatch.setattr("packages.infrastructure.db_connector.get_db_cursor", cursor_ctx)
    rec_id = ap.save_decision({"mode": "llm", "dry_run": True, "llm_provider": "router", "llm_model": "m",
                               "inputs": {"a": 1}, "plan": {"actions": []}, "executed": [], "rejected": [],
                               "note": None})
    with db.cursor() as cur:
        cur.execute("SELECT mode, dry_run, inputs_json->>'a' FROM ops_dataextraction.planner_decisions WHERE id=%s",
                    (rec_id,))
        assert cur.fetchone() == ("llm", True, "1")
