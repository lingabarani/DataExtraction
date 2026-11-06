"""
DataExtraction — Federal Open Data Ingestion Workflow
======================================================
Durable Temporal workflow orchestrating all 8 US Federal and Open Data registries:
- SAM.gov (Vendor Registry & POC Executives)
- US Census CBP (County Business Patterns & Industry Sizing)
- openFDA (Regulated Life Sciences & Medical Facilities)
- Bureau of Labor Statistics (BLS Timeseries & Employment Benchmarks)
- Bureau of Economic Analysis (BEA Regional GDP)
- Energy Information Administration (EIA Commercial Energy Providers)
- USGS Water Resources (Active Infrastructure Monitoring Facilities)
- Data.gov (Higher Education & Institutional Facilities)

Enterprise Capabilities:
- Sequential execution with API rate limiting protection
- Per-source error isolation (one source failure doesn't block others)
- Signal controls: pause() and resume()
- Non-blocking live status queries: get_status()
- Direct OneExtraction PostgreSQL persistence
"""

import logging
from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.open_data_activities import (
        run_sam_gov_extraction_activity,
        run_census_cbp_extraction_activity,
        run_openfda_extraction_activity,
        run_bls_extraction_activity,
        run_bea_extraction_activity,
        run_eia_extraction_activity,
        run_usgs_extraction_activity,
        run_datagov_extraction_activity,
    )

logger = logging.getLogger("dataextraction.workflows.open_data")

OPEN_DATA_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError"],
)


@workflow.defn(name="OpenDataIngestionWorkflow")
class OpenDataIngestionWorkflow:
    """
    Durable workflow that coordinates 8 US Federal Open Data registries.
    """

    SOURCES = [
        ("run_sam_gov_extraction", run_sam_gov_extraction_activity, "federal-ingestion"),
        ("run_census_cbp_extraction", run_census_cbp_extraction_activity, "federal-ingestion"),
        ("run_openfda_extraction", run_openfda_extraction_activity, "federal-ingestion"),
        ("run_bls_extraction", run_bls_extraction_activity, "federal-ingestion"),
        ("run_bea_extraction", run_bea_extraction_activity, "federal-ingestion"),
        ("run_eia_extraction", run_eia_extraction_activity, "federal-ingestion"),
        ("run_usgs_extraction", run_usgs_extraction_activity, "federal-ingestion"),
        ("run_datagov_extraction", run_datagov_extraction_activity, "federal-ingestion"),
    ]

    def __init__(self) -> None:
        self._results: Dict[str, Dict[str, Any]] = {}
        self._paused: bool = False
        self._current_source: str = ""

    # ── Signals ───────────────────────────────────────────────────────────────

    @workflow.signal
    def pause(self) -> None:
        """Pause execution after the current source completes."""
        workflow.logger.warning("PAUSE signal received — pausing after current source")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        """Resume paused workflow execution."""
        workflow.logger.info("RESUME signal received")
        self._paused = False

    # ── Queries ───────────────────────────────────────────────────────────────

    @workflow.query
    def get_status(self) -> dict:
        """Return live workflow state without side effects."""
        completed = [s for s, r in self._results.items() if r.get("status") == "SUCCESS"]
        failed = [s for s, r in self._results.items() if r.get("status") == "FAILED"]
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
        dry_run = bool(config.get("dry_run", False))
        selected_sources = config.get("sources", None)  # Optional list of activity names to run

        workflow.logger.info("OpenDataIngestionWorkflow started: mode=%s, dry_run=%s", mode, dry_run)

        for activity_name, activity_fn, task_queue in self.SOURCES:
            if selected_sources and activity_name not in selected_sources:
                continue

            await workflow.wait_condition(lambda: not self._paused)
            self._current_source = activity_name

            source_args = {**config.get(activity_name, {}), "mode": mode, "dry_run": dry_run}

            try:
                result = await workflow.execute_activity(
                    activity_fn,
                    args=[source_args],
                    task_queue=task_queue,
                    start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=OPEN_DATA_RETRY_POLICY,
                )
                self._results[activity_name] = {"status": "SUCCESS", **result}
                workflow.logger.info("Open Data Source %s: SUCCESS", activity_name)

            except ActivityError as exc:
                self._results[activity_name] = {
                    "status": "FAILED",
                    "error": str(exc.cause) if exc.cause else str(exc),
                }
                workflow.logger.error("Open Data Source %s: FAILED — %s", activity_name, exc)

        self._current_source = "COMPLETED"
        successful = [name for name, r in self._results.items() if r.get("status") == "SUCCESS"]

        workflow.logger.info(
            "OpenDataIngestionWorkflow finished: %d/%d sources successful",
            len(successful), len(self._results),
        )

        return {
            "mode": mode,
            "dry_run": dry_run,
            "sources_run": len(self._results),
            "sources_successful": len(successful),
            "sources_failed": len(self._results) - len(successful),
            "results": self._results,
        }

