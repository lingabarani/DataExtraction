"""
DataExtraction — Promotion Gate Workflow
=========================================
Queue: governance-quality-queue
Worker: packages.temporal.workers.worker_governance

Autonomous Promotion Gate Workflow:
Enforces that ONLY verified, enriched, certified records from staging_dataextraction.working_*
(Quality >= 80, Trust >= 0.85, Sanctions CLEAR) are atomically promoted into master_dataextraction.*.
"""

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.storage_activities import (
        promote_certified_to_master_activity,
        evaluate_working_governance_activity,
    )
    from packages.temporal.config import QUEUE_GOVERNANCE, GOVERNANCE_RETRY_POLICY

TASK_QUEUE = QUEUE_GOVERNANCE


@workflow.defn(name="PromotionGateWorkflow")
class PromotionGateWorkflow:
    """
    Autonomous Promotion Gate Workflow.
    Executes pre-master evaluation followed by atomic single-transaction promotion into Master Vault.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._step: str = "INIT"
        self._paused: bool = False
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Promotion Gate] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Promotion Gate] Resume signal received")
        self._paused = False

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "workflow": "PromotionGateWorkflow",
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
        workflow.logger.info("[Promotion Gate] Starting gate execution on queue: %s", TASK_QUEUE)

        min_quality = config.get("min_quality", 80)
        min_trust = config.get("min_trust", 0.85)
        batch_size = config.get("batch_size", 1000)
        auto_evaluate = config.get("auto_evaluate", True)

        # ── Step 1: Pre-Evaluation (if requested) ─────────────────────────────
        if auto_evaluate:
            self._step = "EVALUATE_PRE_MASTER"
            await workflow.wait_condition(lambda: not self._paused)
            try:
                eval_res = await workflow.execute_activity(
                    evaluate_working_governance_activity,
                    args=[batch_size],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=15),
                    retry_policy=GOVERNANCE_RETRY_POLICY,
                )
                self._results["evaluation"] = eval_res
            except Exception as exc:
                self._results["evaluation"] = {"error": str(exc)}

        # ── Step 2: Atomic Promotion CTE ───────────────────────────────────────
        self._step = "ATOMIC_PROMOTION"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            promo_res = await workflow.execute_activity(
                promote_certified_to_master_activity,
                args=[min_quality, min_trust, batch_size],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=GOVERNANCE_RETRY_POLICY,
            )
            self._results["promotion"] = promo_res
        except Exception as exc:
            self._results["promotion"] = {"error": str(exc)}

        self._step = "COMPLETED"
        self._status = "COMPLETED"
        return {
            "status": self._status,
            "results": self._results,
        }
