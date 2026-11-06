"""
DataExtraction — Autonomous Freshness & SLA Revalidation Engine Workflow
=========================================================================
Queue: governance-quality-queue
Worker: packages.temporal.workers.worker_governance

Autonomous Freshness & SLA Revalidation Engine Workflow:
- Calculates continuous exponential decay F(t) = exp(-lambda * delta_t) across master records
- Detects expired SLA thresholds across all 6 dimensions (Website 30d, Email 90d, Exec 90d, Maps 180d, Registry 365d)
- Stages stale entities back into staging_dataextraction.working_organizations for reharvest
- Orchestrates re-certification and promotion back to Master single source of truth
"""

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.storage_activities import (
        apply_freshness_decay_activity,
        fetch_overdue_revalidations_activity,
        stage_overdue_for_reharvest_activity,
        promote_certified_to_master_activity,
    )
    from packages.temporal.config import QUEUE_GOVERNANCE, GOVERNANCE_RETRY_POLICY

TASK_QUEUE = QUEUE_GOVERNANCE


@workflow.defn(name="RevalidationSweepWorkflow")
class RevalidationSweepWorkflow:
    """
    Autonomous Freshness & SLA Revalidation Engine Workflow.
    Executes daily sweep across master vault, decaying freshness, staging expired SLAs,
    and maintaining continuous data veracity.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._step: str = "INIT"
        self._paused: bool = False
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Revalidation Sweep] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Revalidation Sweep] Resume signal received")
        self._paused = False

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "workflow": "RevalidationSweepWorkflow",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "step": self._step,
            "paused": self._paused,
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        self._status = "RUNNING"
        workflow.logger.info("[Revalidation Sweep] Starting autonomous freshness sweep on queue: %s", TASK_QUEUE)

        batch_size = config.get("batch_size", 5000)
        auto_stage = config.get("auto_reharvest", True)

        # ── Step 1: Apply Continuous Freshness Decay ──────────────────────────
        self._step = "APPLY_FRESHNESS_DECAY"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            decay_res = await workflow.execute_activity(
                apply_freshness_decay_activity,
                args=[batch_size],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=GOVERNANCE_RETRY_POLICY,
            )
            self._results["freshness_decay"] = decay_res
        except Exception as exc:
            self._results["freshness_decay"] = {"error": str(exc)}

        # ── Step 2: Fetch Overdue SLA Entities ────────────────────────────────
        self._step = "FETCH_OVERDUE_REVALIDATIONS"
        await workflow.wait_condition(lambda: not self._paused)
        overdue_records = []
        try:
            fetch_res = await workflow.execute_activity(
                fetch_overdue_revalidations_activity,
                args=[batch_size],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=GOVERNANCE_RETRY_POLICY,
            )
            self._results["overdue_detection"] = {
                "status": fetch_res.get("status"),
                "overdue_count": fetch_res.get("overdue_count", 0),
            }
            overdue_records = fetch_res.get("records", [])
        except Exception as exc:
            self._results["overdue_detection"] = {"error": str(exc)}

        # ── Step 3: Re-Stage Overdue Entities into Working Layer ──────────────
        if auto_stage and overdue_records:
            self._step = "STAGE_OVERDUE_FOR_REHARVEST"
            await workflow.wait_condition(lambda: not self._paused)
            try:
                stage_res = await workflow.execute_activity(
                    stage_overdue_for_reharvest_activity,
                    args=[overdue_records],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=20),
                    retry_policy=GOVERNANCE_RETRY_POLICY,
                )
                self._results["stage_reharvest"] = stage_res
            except Exception as exc:
                self._results["stage_reharvest"] = {"error": str(exc)}
        else:
            self._results["stage_reharvest"] = {"status": "SKIPPED", "reason": "No overdue records or auto_reharvest disabled"}

        self._step = "COMPLETED"
        self._status = "COMPLETED"
        return {
            "status": self._status,
            "results": self._results,
        }
