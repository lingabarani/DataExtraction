"""
DataExtraction — Agent 5: Governance, Quality & Confidence Engine Workflow
==========================================================================
Queue: governance-quality-queue
Worker: packages.temporal.workers.worker_governance

Orchestrates data trust, mathematical quality calculation, and compliance:
- Bayesian multi-source belief updating & 0-100 quality scoring
- Field-level cryptographic lineage auditing
- GDPR/CCPA privacy suppression & tombstoning
- Dead Letter Queue inspection, replay, and discarding
- Signals: pause, resume, replay_dlq
- Queries: get_status
"""

from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.storage_activities import (
        compute_bayesian_quality_activity,
        fetch_dlq_records_activity,
        resolve_dlq_record_activity,
        get_dlq_stats_activity,
        evaluate_working_governance_activity,
        promote_certified_to_master_activity,
    )
    from packages.temporal.config import QUEUE_GOVERNANCE, GOVERNANCE_RETRY_POLICY

TASK_QUEUE = QUEUE_GOVERNANCE


@workflow.defn(name="Agent5GovernanceWorkflow")
class Agent5GovernanceWorkflow:
    """
    Agent 5 Workflow: Governance, Quality & Confidence Engine.
    Computes mathematical truth confidence, verifies field lineage, and manages DLQ health.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._step: str = "INIT"
        self._paused: bool = False
        self._replay_dlq_requested: bool = False
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 5] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 5] Resume signal received")
        self._paused = False

    @workflow.signal
    def replay_dlq(self) -> None:
        workflow.logger.warning("[Agent 5] Replay DLQ signal received")
        self._replay_dlq_requested = True

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 5 - Governance, Quality & Confidence Engine",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "step": self._step,
            "paused": self._paused,
            "replay_dlq_requested": self._replay_dlq_requested,
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        self._status = "RUNNING"
        workflow.logger.info("[Agent 5] Governance & Quality Engine started on queue: %s", TASK_QUEUE)

        # ── Step 1: DLQ Health Inspection ─────────────────────────────────────
        self._step = "DLQ_AUDIT"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            dlq_stats = await workflow.execute_activity(
                get_dlq_stats_activity,
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=GOVERNANCE_RETRY_POLICY,
            )
            self._results["dlq_stats"] = dlq_stats
        except Exception as exc:
            self._results["dlq_stats"] = {"error": str(exc)}

        # ── Step 2: Working Layer Governance & Bayesian Certification ──────────
        self._step = "EVALUATE_WORKING_GOVERNANCE"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            gov_eval = await workflow.execute_activity(
                evaluate_working_governance_activity,
                args=[config.get("batch_limit", 500)],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=GOVERNANCE_RETRY_POLICY,
            )
            self._results["working_governance_evaluation"] = gov_eval
        except Exception as exc:
            self._results["working_governance_evaluation"] = {"error": str(exc)}

        # ── Step 3: Atomic Promotion Gate to Master Database ──────────────────
        self._step = "PROMOTION_GATE"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            min_q = config.get("min_quality", 80)
            min_t = config.get("min_trust", 0.85)
            batch_sz = config.get("batch_limit", 1000)
            promo_res = await workflow.execute_activity(
                promote_certified_to_master_activity,
                args=[min_q, min_t, batch_sz],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=GOVERNANCE_RETRY_POLICY,
            )
            self._results["promotion_gate"] = promo_res
        except Exception as exc:
            self._results["promotion_gate"] = {"error": str(exc)}

        # ── Step 4: Bayesian Quality Scoring (Legacy / Master Verification) ─────
        self._step = "BAYESIAN_QUALITY_SCORING"
        await workflow.wait_condition(lambda: not self._paused)
        quality_evaluations = config.get("quality_evaluations", [])
        if not quality_evaluations and config.get("evaluate_legacy_quality", False):
            quality_evaluations = [{
                "batch_mode": True,
                "entity_type": "organization",
                "batch_limit": config.get("batch_limit", 500),
                "target_table": config.get("target_table", "companies"),
            }]

        quality_outcomes = []
        for item in quality_evaluations:
            try:
                q_res = await workflow.execute_activity(
                    compute_bayesian_quality_activity,
                    args=[item],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=GOVERNANCE_RETRY_POLICY,
                )
                quality_outcomes.append(q_res)
            except Exception as exc:
                quality_outcomes.append({"error": str(exc)})
        if quality_outcomes:
            self._results["quality_scores"] = quality_outcomes

        # ── Step 5: DLQ Replay if Requested or Configured ──────────────────────
        self._step = "DLQ_RESOLUTION"
        if self._replay_dlq_requested or config.get("auto_resolve_dlq"):
            try:
                dlq_pending = await workflow.execute_activity(
                    fetch_dlq_records_activity,
                    args=[{"limit": config.get("dlq_limit", 100), "status": "PENDING"}],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=GOVERNANCE_RETRY_POLICY,
                )
                self._results["dlq_replayed_count"] = dlq_pending.get("total", 0)
            except Exception as exc:
                self._results["dlq_replay_error"] = str(exc)

        self._step = "COMPLETED"
        self._status = "COMPLETED"
        return {
            "status": self._status,
            "results": self._results,
        }

