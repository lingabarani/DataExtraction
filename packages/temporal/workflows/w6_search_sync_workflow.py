"""
DataExtraction — Agent 6: Persistence, CDC & Search Synchronization Workflow
============================================================================
Queue: search-persistence-queue
Worker: packages.temporal.workers.worker_search

Orchestrates database partition maintenance & downstream CDC search sync:
- Automated quarterly & multi-year partition maintenance
- Change Data Capture (CDC) streaming to OpenSearch 2.x
- Watermark checkpoint commits
- High-efficiency edge n-gram autocomplete index hydration
- Signals: pause, resume, force_sync
- Queries: get_status
"""

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.storage_activities import (
        maintain_kg_partitions_activity,
        sync_opensearch_cdc_activity,
    )
    from packages.infrastructure.config_manager import config_manager

TASK_QUEUE = config_manager.QUEUE_SEARCH

SEARCH_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=4,
    non_retryable_error_types=["PermissionError"],
)


@workflow.defn(name="Agent6SearchSyncWorkflow")
class Agent6SearchSyncWorkflow:
    """
    Agent 6 Workflow: Persistence, CDC & Search Synchronization.
    Maintains physical storage partitions and syncs search projections to OpenSearch 2.x.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._step: str = "INIT"
        self._paused: bool = False
        self._force_sync_requested: bool = False
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 6] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 6] Resume signal received")
        self._paused = False

    @workflow.signal
    def force_sync(self) -> None:
        workflow.logger.warning("[Agent 6] Force CDC sync signal received")
        self._force_sync_requested = True

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 6 - Persistence, CDC & Search Synchronization",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "step": self._step,
            "paused": self._paused,
            "force_sync": self._force_sync_requested,
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        self._status = "RUNNING"
        workflow.logger.info("[Agent 6] Search Persistence & CDC started on queue: %s", TASK_QUEUE)

        # ── Step 1: Automated Knowledge Graph Partition Maintenance ──────────
        self._step = "PARTITION_MAINTENANCE"
        await workflow.wait_condition(lambda: not self._paused)
        if config.get("run_partitions", True):
            try:
                part_res = await workflow.execute_activity(
                    maintain_kg_partitions_activity,
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=SEARCH_RETRY_POLICY,
                )
                self._results["partitions"] = {"status": "SUCCESS", **part_res}
            except Exception as exc:
                self._results["partitions"] = {"status": "FAILED", "error": str(exc)}

        # ── Step 2: OpenSearch CDC Delta Synchronization ──────────────────────
        self._step = "OPENSEARCH_CDC_SYNC"
        await workflow.wait_condition(lambda: not self._paused)
        if config.get("run_search_sync", True) or self._force_sync_requested:
            batch_limit = config.get("sync_batch_limit", 1000)
            try:
                sync_res = await workflow.execute_activity(
                    sync_opensearch_cdc_activity,
                    args=[batch_limit],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(hours=1),
                    retry_policy=SEARCH_RETRY_POLICY,
                )
                self._results["opensearch_sync"] = {"status": "SUCCESS", **sync_res}
            except Exception as exc:
                self._results["opensearch_sync"] = {"status": "FAILED", "error": str(exc)}

        self._step = "COMPLETED"
        self._status = "COMPLETED"
        return {
            "status": self._status,
            "results": self._results,
        }
