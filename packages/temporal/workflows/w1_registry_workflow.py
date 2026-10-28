"""
DataExtraction — Agent 1: Official Registry Ingestion Workflow
==============================================================
Queue: registry-ingestion-queue
Worker: packages.temporal.workers.worker_registry

Orchestrates official registry scrapers sequentially with:
- SEC EDGAR Fair Access compliance (10 req/s, compliant User-Agent)
- Sequential rate-limited execution
- Per-source error isolation
- Signals: pause, resume, cancel_source
- Queries: get_status
"""

from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.federal_activities import (
        run_cms_npi_activity,
        run_sec_edgar_activity,
        run_fdic_activity,
        run_usaspending_activity,
        run_propublica_activity,
        run_sam_gov_activity,
    )
    from packages.infrastructure.config_manager import config_manager

TASK_QUEUE = config_manager.QUEUE_REGISTRY

REGISTRY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError", "ConfigurationError"],
)


@workflow.defn(name="Agent1RegistryWorkflow")
class Agent1RegistryWorkflow:
    """
    Agent 1 Workflow: Official Registry Intelligence.
    Ingests sovereign and regulatory registry data (SEC, CMS, FDIC, USASpending, SAM, ProPublica).
    """

    SOURCES = [
        ("cms_npi", run_cms_npi_activity),
        ("sec_edgar", run_sec_edgar_activity),
        ("fdic", run_fdic_activity),
        ("usaspending", run_usaspending_activity),
        ("propublica", run_propublica_activity),
        ("sam_gov", run_sam_gov_activity),
    ]

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._current_source: str = ""
        self._paused: bool = False
        self._cancelled_sources: set[str] = set()
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 1] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 1] Resume signal received")
        self._paused = False

    @workflow.signal
    def cancel_source(self, source_name: str) -> None:
        workflow.logger.warning("[Agent 1] Cancel source signal received: %s", source_name)
        self._cancelled_sources.add(source_name.lower())

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 1 - Official Registry Intelligence",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "current_source": self._current_source,
            "paused": self._paused,
            "completed": [s for s, r in self._results.items() if r.get("status") == "SUCCESS"],
            "failed": [s for s, r in self._results.items() if r.get("status") == "FAILED"],
            "total_sources": len(self.SOURCES),
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        self._status = "RUNNING"
        workflow.logger.info("[Agent 1] Registry Ingestion started on queue: %s", TASK_QUEUE)

        sources_to_run = config.get("sources", [s[0] for s in self.SOURCES])

        for source_name, activity_fn in self.SOURCES:
            if source_name not in sources_to_run:
                continue
            if source_name in self._cancelled_sources:
                self._results[source_name] = {"status": "SKIPPED", "reason": "Cancelled by operator"}
                continue

            await workflow.wait_condition(lambda: not self._paused)
            self._current_source = source_name
            workflow.logger.info("[Agent 1] Ingesting registry source: %s", source_name)

            source_cfg = config.get(source_name, {"mode": "incremental"})
            try:
                res = await workflow.execute_activity(
                    activity_fn,
                    args=[source_cfg],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(hours=4),
                    retry_policy=REGISTRY_RETRY_POLICY,
                )
                self._results[source_name] = {"status": "SUCCESS", **res}
            except Exception as exc:
                workflow.logger.error("[Agent 1] Registry source %s failed: %s", source_name, exc)
                self._results[source_name] = {"status": "FAILED", "error": str(exc)}

        self._status = "COMPLETED"
        return {
            "status": self._status,
            "sources_successful": len([s for s, r in self._results.items() if r.get("status") == "SUCCESS"]),
            "sources_failed": len([s for s, r in self._results.items() if r.get("status") == "FAILED"]),
            "results": self._results,
        }

