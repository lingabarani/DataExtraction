"""
DataExtraction — Autonomy Planner Agent
=======================================
Looks at the state of the platform (data counts, staleness, DLQ, running workflows,
LLM budget), asks the configured LLM what to run next, then starts the chosen
Temporal workflows by itself.

Safety model (enforced in code, never by prompt):
  * Only workflows in ALLOWLIST can start, with whitelisted and clamped parameters.
  * Workflows that need a human (full refresh, OSM) are recorded as `needs_approval`.
  * Per-queue and global concurrency caps; a workflow already running is not started again.
  * Deterministic workflow ids (hour-bucketed) prevent duplicate starts.
  * PLANNER_DRY_RUN=true or dry_run=True records the decision and starts nothing.
  * If the LLM is unavailable or over budget, deterministic rules decide instead.
  * Every cycle is written to ops_dataextraction.planner_decisions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from packages.agents.base_agent import AgentDecision, BaseAgent
from packages.temporal.config import QUEUE_EMAIL_ENRICHMENT, QUEUE_GEOSPATIAL, QUEUE_GOVERNANCE

logger = logging.getLogger("dataextraction.agents.autonomy_planner")

_REPO_ROOT = Path(__file__).resolve().parents[3]


# ══════════════════════════════════════════════════════════════════════════════
# Allowlist
# ══════════════════════════════════════════════════════════════════════════════

class PlanRejected(Exception):
    """An action failed validation."""


def _int(lo: int, hi: int) -> Callable[[Any], int]:
    def f(v: Any) -> int:
        if isinstance(v, bool):
            raise PlanRejected("expected a number")
        try:
            return max(lo, min(int(v), hi))
        except (TypeError, ValueError):
            raise PlanRejected(f"expected an integer between {lo} and {hi}")
    return f


def _float(lo: float, hi: float) -> Callable[[Any], float]:
    def f(v: Any) -> float:
        try:
            return max(lo, min(float(v), hi))
        except (TypeError, ValueError):
            raise PlanRejected(f"expected a number between {lo} and {hi}")
    return f


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if str(v).lower() in ("true", "false"):
        return str(v).lower() == "true"
    raise PlanRejected("expected true/false")


def _str_list(max_items: int, pattern: str = r"^[A-Za-z0-9_\- ]{1,40}$") -> Callable[[Any], List[str]]:
    import re
    rx = re.compile(pattern)

    def f(v: Any) -> List[str]:
        if not isinstance(v, list):
            raise PlanRejected("expected a list")
        out = []
        for item in v[:max_items]:
            s = str(item).strip()
            if not rx.match(s):
                raise PlanRejected(f"invalid list item '{s[:30]}'")
            out.append(s)
        return out
    return f


def _enum(*allowed: str) -> Callable[[Any], str]:
    def f(v: Any) -> str:
        if str(v) not in allowed:
            raise PlanRejected(f"must be one of {allowed}")
        return str(v)
    return f


def _text(pattern: str) -> Callable[[Any], str]:
    import re
    rx = re.compile(pattern)

    def f(v: Any) -> str:
        s = str(v).strip()
        if not rx.match(s):
            raise PlanRejected(f"invalid value '{s[:30]}'")
        return s
    return f


@dataclass(frozen=True)
class WorkflowSpec:
    queue: str
    params: Dict[str, Callable[[Any], Any]]
    description: str
    needs_approval_when: Optional[Callable[[Dict[str, Any]], bool]] = None


ALLOWLIST: Dict[str, WorkflowSpec] = {
    "DiscoverySearchWorkflow": WorkflowSpec(
        queue=QUEUE_GEOSPATIAL,
        params={
            "query": _text(r"^.{1,300}$"),
            "budget_seconds": _float(5.0, 120.0),
        },
        description="Run multi-source discovery search across CMS, state registries, Google Maps, web search, and LinkedIn.",
    ),
    "PlaceDeepExtractionWorkflow": WorkflowSpec(
        queue=QUEUE_GEOSPATIAL,
        params={
            "region": _text(r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$"),
            "category": _text(r"^[A-Za-z0-9_ &\-]{1,40}$"),
            "max_places": _int(1, 500),
            "batch_size": _int(1, 50),
            "with_llm": _bool,
            "max_reviews": _int(0, 2000),
        },
        description="Scrape details, services, reviews, contacts and people for already-discovered Google Maps places.",
    ),
    "GMapsExtractionWorkflow": WorkflowSpec(
        queue="gmaps-extraction",
        params={
            "regions": _str_list(5, r"^[A-Z]{2}-[A-Z0-9]{1,3}$"),
            "categories": _str_list(5),
            "verification_limit": _int(1, 10000),
        },
        description="Discover new Google Maps places for regions and categories (max 5 each).",
    ),
    "FederalIngestionWorkflow": WorkflowSpec(
        queue="federal-ingestion",
        params={"mode": _enum("incremental", "full")},
        description="Pull federal registries. mode=full requires human approval.",
        needs_approval_when=lambda p: p.get("mode") == "full",
    ),
    "OSMStateWorkflow": WorkflowSpec(
        queue="osm-extraction",
        params={"scope": _enum("full", "sample"), "states": _str_list(3, r"^[A-Za-z_ ]{2,30}$")},
        description="OpenStreetMap extraction (heavy).",
        needs_approval_when=lambda p: True,
    ),
    "DLQReplayWorkflow": WorkflowSpec(
        queue="storage-ops",
        params={"limit": _int(1, 1000), "mode": _enum("auto", "manual")},
        description="Replay dead-letter queue records.",
    ),
    "EmailEnrichmentWorkflow": WorkflowSpec(
        queue=QUEUE_EMAIL_ENRICHMENT,
        params={"batch_size": _int(1, 1000), "max_records": _int(1, 20000), "probe_smtp": _bool,
                "verify_dedup_completed": _bool},
        description="Discover and verify emails for canonical organizations.",
    ),
    "RevalidationSweepWorkflow": WorkflowSpec(
        queue=QUEUE_GOVERNANCE,
        params={"batch_size": _int(1, 10000), "freshness_threshold": _float(0.0, 1.0), "auto_reharvest": _bool},
        description="Re-check stale records and re-harvest them.",
    ),
    "PromotionGateWorkflow": WorkflowSpec(
        queue=QUEUE_GOVERNANCE,
        params={},
        description="Promote certified records to master data.",
    ),
}


def sanitize_params(workflow: str, params: Dict[str, Any]) -> Dict[str, Any]:
    spec = ALLOWLIST.get(workflow)
    if spec is None:
        raise PlanRejected(f"workflow '{workflow}' is not in the allowlist")
    clean: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        validator = spec.params.get(key)
        if validator is None:
            raise PlanRejected(f"parameter '{key}' is not allowed for {workflow}")
        if value is None:
            # LLMs routinely emit null for "not set". Treat that as an omitted parameter.
            continue
        clean[key] = validator(value)
    return clean


# ══════════════════════════════════════════════════════════════════════════════
# Plan schema
# ══════════════════════════════════════════════════════════════════════════════

class PlannedAction(BaseModel):
    workflow: str
    params: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 5
    reason: str = ""


class Plan(BaseModel):
    summary: str = ""
    actions: List[PlannedAction] = Field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════════════
# Config
# ══════════════════════════════════════════════════════════════════════════════

def load_planner_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {}
    path = _REPO_ROOT / "config" / "agents.yaml"
    try:
        cfg = ((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("agents", {})
               .get("autonomy_planner", {})) or {}
    except Exception as exc:
        logger.warning("Could not read planner config: %s", exc)
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "max_actions_per_cycle": int(os.getenv("PLANNER_MAX_ACTIONS", cfg.get("max_actions_per_cycle", 3))),
        "max_running_per_queue": int(os.getenv("PLANNER_MAX_PER_QUEUE", cfg.get("max_running_per_queue", 2))),
        "max_running_total": int(os.getenv("PLANNER_MAX_RUNNING", cfg.get("max_running_total", 6))),
        "stale_hours": int(cfg.get("stale_hours", 24)),
        "dlq_replay_threshold": int(cfg.get("dlq_replay_threshold", 100)),
        "regions": list(cfg.get("regions") or ["US-CA", "US-TX", "US-NY"]),
        "categories": list(cfg.get("categories") or ["restaurant", "hotel", "retail", "healthcare"]),
        "place_batch": int(cfg.get("place_batch", 50)),
    }


def dry_run_default() -> bool:
    return os.getenv("PLANNER_DRY_RUN", "false").strip().lower() in ("1", "true", "yes")


# ══════════════════════════════════════════════════════════════════════════════
# Signals (SQL only, no LLM)
# ══════════════════════════════════════════════════════════════════════════════

def _scalar(cur: Any, sql: str, params: tuple = ()) -> Optional[Any]:
    try:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return None


def gather_signals(cfg: Dict[str, Any], get_conn: Optional[Callable[[], Any]] = None,
                   release: Optional[Callable[[Any], None]] = None) -> Dict[str, Any]:
    """Read-only snapshot of platform state. Every probe is independent and failure-tolerant."""
    if get_conn is None:
        from packages.infrastructure.db_connector import get_connection, release_connection
        get_conn, release = get_connection, release_connection
    release = release or (lambda c: None)

    signals: Dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}
    conn = None
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            signals["gmaps_places_total"] = _scalar(
                cur, "SELECT COUNT(*) FROM staging_dataextraction.staging_companies WHERE source='GOOGLE_MAPS'")
            signals["places_without_deep_data"] = _scalar(
                cur, """SELECT COUNT(*) FROM staging_dataextraction.staging_companies sc
                        LEFT JOIN staging_dataextraction.place_details pd ON pd.place_id = sc.raw_payload->>'cid'
                        WHERE sc.source='GOOGLE_MAPS' AND sc.raw_payload->>'cid' IS NOT NULL
                          AND pd.place_id IS NULL""")
            signals["places_with_stale_deep_data"] = _scalar(
                cur, "SELECT COUNT(*) FROM staging_dataextraction.place_details WHERE scraped_at < NOW() - INTERVAL '14 days'")
            signals["reviews_total"] = _scalar(cur, "SELECT COUNT(*) FROM staging_dataextraction.place_reviews")
            signals["dlq_pending"] = _scalar(
                cur, "SELECT COUNT(*) FROM staging_dataextraction.dead_letter_queue WHERE status = 'PENDING'")
            signals["hours_since_gmaps_update"] = _scalar(
                cur, """SELECT EXTRACT(EPOCH FROM (NOW() - MAX(updated_at)))/3600
                        FROM staging_dataextraction.staging_companies WHERE source='GOOGLE_MAPS'""")
            signals["hours_since_federal_update"] = _scalar(
                cur, """SELECT EXTRACT(EPOCH FROM (NOW() - MAX(updated_at)))/3600
                        FROM staging_dataextraction.staging_companies
                        WHERE source IN ('SEC_EDGAR','CMS_NPI','FDIC','USASPENDING','PROPUBLICA','SAM_GOV')""")
            gaps = []
            for region in cfg["regions"]:
                code = region.split("-")[-1]
                n = _scalar(cur, """SELECT COUNT(*) FROM staging_dataextraction.staging_companies
                                    WHERE source='GOOGLE_MAPS' AND (UPPER(state_code)=%s OR UPPER(state)=%s)""",
                            (code, code))
                if not n:
                    gaps.append(region)
            signals["regions_without_gmaps_data"] = gaps
    except Exception as exc:
        signals["db_error"] = type(exc).__name__
    finally:
        if conn is not None:
            release(conn)

    for key, val in list(signals.items()):
        if hasattr(val, "__float__") and not isinstance(val, (int, float, bool)):
            signals[key] = float(val)
    try:
        from packages.infrastructure.llm.usage import budget_status
        signals["llm_budget"] = budget_status()
    except Exception:
        pass
    return signals


# ══════════════════════════════════════════════════════════════════════════════
# Deterministic fallback
# ══════════════════════════════════════════════════════════════════════════════

def fallback_plan(signals: Dict[str, Any], cfg: Dict[str, Any]) -> Plan:
    actions: List[PlannedAction] = []
    dlq = signals.get("dlq_pending") or 0
    if 0 < dlq <= cfg["dlq_replay_threshold"]:
        actions.append(PlannedAction(workflow="DLQReplayWorkflow", params={"limit": int(dlq), "mode": "auto"},
                                     priority=1, reason=f"{dlq} DLQ records pending (below threshold)"))
    gaps = signals.get("regions_without_gmaps_data") or []
    if gaps:
        actions.append(PlannedAction(
            workflow="GMapsExtractionWorkflow",
            params={"regions": gaps[:2], "categories": cfg["categories"][:3]}, priority=2,
            reason=f"No Google Maps data for {', '.join(gaps[:2])}"))
    missing = signals.get("places_without_deep_data") or 0
    if missing > 0:
        actions.append(PlannedAction(
            workflow="PlaceDeepExtractionWorkflow",
            params={"max_places": min(int(missing), cfg["place_batch"]), "batch_size": 25, "with_llm": True},
            priority=3, reason=f"{missing} places have no deep data yet"))
    stale = signals.get("places_with_stale_deep_data") or 0
    if stale > 0 and missing == 0:
        actions.append(PlannedAction(
            workflow="PlaceDeepExtractionWorkflow",
            params={"max_places": min(int(stale), cfg["place_batch"]), "batch_size": 25, "with_llm": True},
            priority=4, reason=f"{stale} places have deep data older than 14 days"))
    hrs = signals.get("hours_since_federal_update")
    if hrs is not None and hrs > cfg["stale_hours"]:
        actions.append(PlannedAction(workflow="FederalIngestionWorkflow", params={"mode": "incremental"},
                                     priority=5, reason=f"Federal data is {hrs:.0f}h old"))
    actions.sort(key=lambda a: a.priority)
    return Plan(summary="Deterministic rules (LLM not used)", actions=actions)


# ══════════════════════════════════════════════════════════════════════════════
# LLM planning
# ══════════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = (
    "You are the operations planner for a B2B data extraction platform. You are given a JSON snapshot "
    "of the platform and a list of workflows you may start. Choose the most valuable actions for right now. "
    "Rules: prefer fixing data gaps and failures first; never choose a workflow that is not listed; "
    "use only the listed parameters; choose at most {max_actions} actions; return an empty list when "
    "nothing is needed. Give a short factual reason for each action."
)


def llm_plan(llm: Any, signals: Dict[str, Any], cfg: Dict[str, Any], running: List[Dict[str, Any]]) -> Plan:
    catalogue = {name: {"description": spec.description, "parameters": sorted(spec.params)}
                 for name, spec in ALLOWLIST.items()}
    user = json.dumps({"signals": signals, "running_workflows": [r.get("workflow_type") for r in running],
                       "allowed_workflows": catalogue,
                       "configured_regions": cfg["regions"], "configured_categories": cfg["categories"]},
                      default=str)
    result = llm.chat(
        [{"role": "system", "content": _SYSTEM_PROMPT.format(max_actions=cfg["max_actions_per_cycle"])},
         {"role": "user", "content": user}],
        schema=Plan, temperature=0.0, max_tokens=2000, purpose="autonomy_planner",
    )
    return result.parsed  # type: ignore[return-value]


# ══════════════════════════════════════════════════════════════════════════════
# Guardrails + execution
# ══════════════════════════════════════════════════════════════════════════════

def workflow_id_for(workflow: str, params: Dict[str, Any], now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    digest = hashlib.sha1(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:10]
    return f"planner-{workflow}-{digest}-{now:%Y%m%d%H}"


@dataclass
class GuardResult:
    approved: List[Dict[str, Any]] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)


def apply_guardrails(plan: Plan, cfg: Dict[str, Any], running: List[Dict[str, Any]],
                     now: Optional[datetime] = None) -> GuardResult:
    res = GuardResult()
    running_types = [str(r.get("workflow_type")) for r in running]
    running_total = len(running)
    per_queue: Dict[str, int] = {}
    for t in running_types:
        spec = ALLOWLIST.get(t)
        if spec:
            per_queue[spec.queue] = per_queue.get(spec.queue, 0) + 1

    seen_ids: set = set()
    for action in sorted(plan.actions, key=lambda a: a.priority):
        entry = {"workflow": action.workflow, "params": action.params, "reason": action.reason}
        try:
            clean = sanitize_params(action.workflow, action.params)
        except PlanRejected as exc:
            res.rejected.append({**entry, "rejected_because": f"invalid: {exc}"})
            continue
        spec = ALLOWLIST[action.workflow]
        entry["params"] = clean
        if spec.needs_approval_when and spec.needs_approval_when(clean):
            res.rejected.append({**entry, "rejected_because": "needs_approval"})
            continue
        if len(res.approved) >= cfg["max_actions_per_cycle"]:
            res.rejected.append({**entry, "rejected_because": "max_actions_per_cycle reached"})
            continue
        if action.workflow in running_types:
            res.rejected.append({**entry, "rejected_because": "same workflow type already running"})
            continue
        if running_total + len(res.approved) >= cfg["max_running_total"]:
            res.rejected.append({**entry, "rejected_because": "global concurrency cap"})
            continue
        queue_load = per_queue.get(spec.queue, 0) + sum(
            1 for a in res.approved if ALLOWLIST[a["workflow"]].queue == spec.queue)
        if queue_load >= cfg["max_running_per_queue"]:
            res.rejected.append({**entry, "rejected_because": f"queue cap on {spec.queue}"})
            continue
        wf_id = workflow_id_for(action.workflow, clean, now)
        if wf_id in seen_ids:
            res.rejected.append({**entry, "rejected_because": "duplicate action in plan"})
            continue
        seen_ids.add(wf_id)
        res.approved.append({**entry, "workflow_id": wf_id, "task_queue": spec.queue})
    return res


Starter = Callable[[str, Dict[str, Any], str, str], Awaitable[None]]
RunningFetcher = Callable[[], Awaitable[List[Dict[str, Any]]]]


async def _default_starter(workflow: str, params: Dict[str, Any], wf_id: str, queue: str) -> None:
    from temporalio.common import WorkflowIDReusePolicy
    from packages.temporal.client import get_temporal_client
    client = await get_temporal_client()
    # REJECT_DUPLICATE: the same plan in the same hour can never start twice, even after the first run finished.
    await client.start_workflow(workflow, params, id=wf_id, task_queue=queue,
                                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)


async def _default_running() -> List[Dict[str, Any]]:
    """Running workflows. Raises when Temporal cannot be queried so the caller can flag it."""
    from packages.supervisor.tools.temporal_tool import _iter_workflows
    from packages.temporal.client import get_temporal_client
    client = await get_temporal_client()
    out: List[Dict[str, Any]] = []
    async for wf in _iter_workflows(client, "ExecutionStatus='Running'"):
        out.append({"workflow_type": wf.workflow_type, "id": wf.id})
    return out


def save_decision(record: Dict[str, Any]) -> Optional[int]:
    try:
        from packages.infrastructure.db_connector import get_db_cursor
        with get_db_cursor() as (_c, cur):
            cur.execute(
                """
                INSERT INTO ops_dataextraction.planner_decisions
                    (mode, dry_run, llm_provider, llm_model, inputs_json, plan_json, executed_json,
                     rejected_json, note)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                RETURNING id
                """,
                (record["mode"], record["dry_run"], record.get("llm_provider"), record.get("llm_model"),
                 json.dumps(record["inputs"], default=str), json.dumps(record["plan"], default=str),
                 json.dumps(record["executed"], default=str), json.dumps(record["rejected"], default=str),
                 record.get("note")),
            )
            return int(cur.fetchone()[0])
    except Exception as exc:
        logger.warning("Could not persist planner decision: %s", exc)
        return None


class AutonomyPlannerAgent(BaseAgent):
    """Observe -> plan (LLM or rules) -> guardrails -> start workflows -> audit."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, *, llm: Any = None,
                 starter: Starter = _default_starter, running_fetcher: RunningFetcher = _default_running,
                 signals_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                 save_fn: Callable[[Dict[str, Any]], Optional[int]] = save_decision):
        super().__init__("autonomy_planner", config)
        self._llm = llm
        self._starter = starter
        self._running_fetcher = running_fetcher
        self._signals_fn = signals_fn or gather_signals
        self._save_fn = save_fn

    # BaseAgent contract (read-only observe, informational decide)
    async def observe(self) -> dict:
        return self._signals_fn(load_planner_config())

    async def decide(self, observations: dict) -> AgentDecision:
        return AgentDecision(action="noop", rationale="AutonomyPlannerAgent plans through run_cycle().")

    def _get_llm(self) -> Any:
        if self._llm is not None:
            return self._llm
        from packages.infrastructure.llm import get_llm
        return get_llm()

    async def run_cycle(self, dry_run: Optional[bool] = None) -> dict:  # type: ignore[override]
        cfg = load_planner_config()
        dry = dry_run_default() if dry_run is None else bool(dry_run)
        if not cfg["enabled"]:
            return {"status": "DISABLED"}

        signals = self._signals_fn(cfg)
        try:
            running = await self._running_fetcher()
        except Exception as exc:
            logger.warning("Could not list running workflows: %s", exc)
            running = []
            signals["running_workflows_unknown"] = True

        mode, provider, model, note = "fallback", None, None, None
        plan: Plan
        try:
            llm = self._get_llm()
            plan = await _to_thread(llm_plan, llm, signals, cfg, running)
            mode = "llm"
            provider = getattr(llm, "name", None)
            model = getattr(getattr(llm, "providers", [None])[0], "model", None) if hasattr(llm, "providers") \
                else getattr(llm, "model", None)
        except Exception as exc:
            note = f"LLM unavailable ({type(exc).__name__}); used deterministic rules"
            logger.info(note)
            plan = fallback_plan(signals, cfg)

        guard = apply_guardrails(plan, cfg, running)
        executed: List[Dict[str, Any]] = []
        rejected = list(guard.rejected)
        for item in guard.approved:
            if dry:
                executed.append({**item, "started": False, "dry_run": True})
                continue
            try:
                await self._starter(item["workflow"], item["params"], item["workflow_id"], item["task_queue"])
                executed.append({**item, "started": True})
            except Exception as exc:
                name = type(exc).__name__
                reason = "duplicate (already started this hour)" if "AlreadyStarted" in name \
                    else f"start failed: {name}"
                rejected.append({**item, "rejected_because": reason})

        record = {
            "mode": mode, "dry_run": dry, "llm_provider": provider, "llm_model": model,
            "inputs": signals, "plan": plan.model_dump(), "executed": executed,
            "rejected": rejected, "note": note,
        }
        decision_id = await _to_thread(self._save_fn, record)
        return {"status": "OK", "decision_id": decision_id, "mode": mode, "dry_run": dry,
                "summary": plan.summary, "executed": executed, "rejected": rejected, "note": note}


async def _to_thread(fn: Callable, *args: Any) -> Any:
    import asyncio
    return await asyncio.to_thread(fn, *args)
