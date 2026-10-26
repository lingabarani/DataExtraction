"""
DataExtraction — Federal Ingestion Workflow
============================================
Orchestrates all 6 federal registry scrapers sequentially with
per-source error isolation, pause/resume signals, and live status queries.
"""

import asyncio
import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.federal_activities import (
        run_cms_npi_activity,
        run_sec_edgar_activity,
        run_fdic_activity,
        run_usaspending_activity,
        run_propublica_activity,
        run_sam_gov_activity,
    )
    from packages.temporal.activities.pipeline_activities import (
        normalize_batch_activity,
    )

logger = logging.getLogger("dataextraction.workflows.federal")

FEDERAL_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError"],
)


@workflow.defn(name="FederalIngestionWorkflow")
class FederalIngestionWorkflow:
    """
    Durable workflow that runs all 6 federal registry scrapers.

    Features:
    - Sequential execution (respects API rate limits)
    - Per-source error isolation (one failure does NOT stop others)
    - Signal: pause() / resume() for live operational control
    - Query: get_status() for live progress inspection without side effects
    - Auto-triggers normalization on successful sources
    """

    SOURCES = [
        ("run_cms_npi",     run_cms_npi_activity,     "federal-ingestion"),
        ("run_sec_edgar",   run_sec_edgar_activity,   "federal-ingestion"),
        ("run_fdic",        run_fdic_activity,         "federal-ingestion"),
        ("run_usaspending", run_usaspending_activity,  "federal-ingestion"),
        ("run_propublica",  run_propublica_activity,   "federal-ingestion"),
        ("run_sam_gov",     run_sam_gov_activity,      "federal-ingestion"),
    ]

    def __init__(self) -> None:
        self._results: dict[str, dict] = {}
        self._paused: bool = False
        self._current_source: str = ""

    # ── Signals ───────────────────────────────────────────────────────────────

    @workflow.signal
    def pause(self) -> None:
        """Pause execution after the current source completes."""
        workflow.logger.warning("PAUSE signal received — will pause after current source")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        """Resume a paused workflow."""
        workflow.logger.info("RESUME signal received")
        self._paused = False

    # ── Queries ───────────────────────────────────────────────────────────────

    @workflow.query
    def get_status(self) -> dict:
        """Return live workflow state without side effects."""
        completed = [s for s, r in self._results.items() if r.get("status") == "SUCCESS"]
        failed    = [s for s, r in self._results.items() if r.get("status") == "FAILED"]
        return {
            "workflow_id": workflow.info().workflow_id,
            "current_source": self._current_source,
            "paused": self._paused,
            "completed_sources": completed,
            "failed_sources": failed,
            "total_sources": len(self.SOURCES),
            "progress_pct": round(len(self._results) / len(self.SOURCES) * 100, 1),
            "results": self._results,
        }

    # ── Main Execution ────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, config: dict) -> dict:
        mode = config.get("mode", "incremental")
        workflow.logger.info("FederalIngestionWorkflow started: mode=%s", mode)

        for activity_name, activity_fn, task_queue in self.SOURCES:
            # Respect pause signal between sources
            await workflow.wait_condition(lambda: not self._paused)
            self._current_source = activity_name

            try:
                result = await workflow.execute_activity(
                    activity_fn,
                    args=[{**config.get(activity_name, {}), "mode": mode}],
                    task_queue=task_queue,
                    start_to_close_timeout=timedelta(hours=3),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=FEDERAL_RETRY_POLICY,
                )
                self._results[activity_name] = {"status": "SUCCESS", **result}
                workflow.logger.info("Source %s: SUCCESS", activity_name)

            except ActivityError as exc:
                # Per-source isolation — failure does NOT halt remaining sources
                self._results[activity_name] = {
                    "status": "FAILED",
                    "error": str(exc.cause) if exc.cause else str(exc),
                }
                workflow.logger.error("Source %s: FAILED — %s", activity_name, exc)

        self._current_source = "NORMALIZATION"

        # Run normalization for each successful source
        successful = [
            name for name, r in self._results.items() if r["status"] == "SUCCESS"
        ]
        for source in successful:
            try:
                await workflow.execute_activity(
                    normalize_batch_activity,
                    args=[{"source": source.upper(), "table": "federal_raw"}],
                    task_queue="data-pipeline",
                    start_to_close_timeout=timedelta(hours=1),
                    retry_policy=FEDERAL_RETRY_POLICY,
                )
            except ActivityError as exc:
                workflow.logger.error("Normalization failed for %s: %s", source, exc)

        self._current_source = "COMPLETED"
        workflow.logger.info(
            "FederalIngestionWorkflow complete: %d/%d sources successful",
            len(successful), len(self.SOURCES),
        )
        return {
            "mode": mode,
            "sources_run": len(self.SOURCES),
            "sources_successful": len(successful),
            "sources_failed": len(self.SOURCES) - len(successful),
            "results": self._results,
        }
