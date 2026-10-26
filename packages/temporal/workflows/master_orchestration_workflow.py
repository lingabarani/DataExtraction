"""
DataExtraction — Master Orchestration Workflow (Top-Level Saga)
================================================================
Coordinates the full extraction pipeline:
  Phase 1: Federal ingestion (sequential)
  Phase 2: GMaps + OSM extraction (parallel)
  Phase 3: Cross-source deduplication
  Phase 4: Lead enrichment

Supports live control via Signals and live inspection via Queries.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from packages.temporal.workflows.federal_ingestion_workflow import FederalIngestionWorkflow
    from packages.temporal.workflows.gmaps_extraction_workflow import GMapsExtractionWorkflow
    from packages.temporal.workflows.osm_state_workflow import OSMStateWorkflow
    from packages.temporal.workflows.lead_enrichment_workflow import LeadEnrichmentWorkflow
    from packages.temporal.activities.pipeline_activities import deduplicate_batch_activity


@workflow.defn(name="MasterOrchestrationWorkflow")
class MasterOrchestrationWorkflow:
    """
    Top-level Saga that coordinates all data extraction sources into a
    unified lead database.

    Run topology:
        [FederalIngestion] ──► ┐
                               ├──► [CrossDedup] ──► [LeadEnrichment]
        [GMaps] ∥ [OSM] ──────►┘

    Signals: pause, resume, cancel_phase
    Queries: get_status
    """

    def __init__(self) -> None:
        self._status:        str  = "RUNNING"
        self._phase:         str  = "INIT"
        self._paused:        bool = False
        self._cancelled:     bool = False
        self._phase_results: dict = {}

    # ── Signals ───────────────────────────────────────────────────────────────

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("PAUSE signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("RESUME signal received")
        self._paused = False

    @workflow.signal
    def cancel_phase(self, phase: str) -> None:
        workflow.logger.warning("CANCEL phase signal: %s", phase)
        self._cancelled = True  # Will be checked at next phase boundary

    # ── Queries ───────────────────────────────────────────────────────────────

    @workflow.query
    def get_status(self) -> dict:
        return {
            "workflow_id": workflow.info().workflow_id,
            "status":      self._status,
            "phase":       self._phase,
            "paused":      self._paused,
            "phases":      list(self._phase_results.keys()),
            "results":     self._phase_results,
        }

    # ── Main Execution ────────────────────────────────────────────────────────

    @workflow.run
    async def run(self, config: dict) -> dict:
        workflow.logger.info("MasterOrchestrationWorkflow started: %s",
                             workflow.info().workflow_id)

        # ── Phase 1: Federal Ingestion ────────────────────────────────────────
        self._phase = "FEDERAL"
        await workflow.wait_condition(lambda: not self._paused)

        if not self._cancelled:
            try:
                federal_result = await workflow.execute_child_workflow(
                    FederalIngestionWorkflow.run,
                    args=[config.get("federal", {})],
                    id=f"federal-{workflow.info().workflow_id}",
                    task_queue="federal-ingestion",
                    execution_timeout=timedelta(hours=24),
                )
                self._phase_results["federal"] = {
                    "status": "SUCCESS",
                    "sources_successful": federal_result.get("sources_successful", 0),
                }
            except Exception as exc:
                self._phase_results["federal"] = {"status": "FAILED", "error": str(exc)}
                workflow.logger.error("Federal phase FAILED: %s", exc)
                # Do NOT abort — extraction phases are independent

        # ── Phase 2: GMaps + OSM in Parallel ─────────────────────────────────
        self._phase = "EXTRACTION"
        await workflow.wait_condition(lambda: not self._paused)

        if not self._cancelled:
            gmaps_handle = await workflow.start_child_workflow(
                GMapsExtractionWorkflow.run,
                args=[config.get("gmaps", {})],
                id=f"gmaps-{workflow.info().workflow_id}",
                task_queue="gmaps-extraction",
                execution_timeout=timedelta(hours=24),
            )
            osm_handle = await workflow.start_child_workflow(
                OSMStateWorkflow.run,
                args=[config.get("osm", {})],
                id=f"osm-{workflow.info().workflow_id}",
                task_queue="osm-extraction",
                execution_timeout=timedelta(hours=24),
            )

            # Await both in parallel
            gmaps_result, osm_result = await asyncio.gather(
                gmaps_handle, osm_handle, return_exceptions=True
            )

            self._phase_results["gmaps"] = (
                {"status": "SUCCESS", "tiles_successful": gmaps_result.get("tiles_successful", 0)}
                if not isinstance(gmaps_result, Exception)
                else {"status": "FAILED", "error": str(gmaps_result)}
            )
            self._phase_results["osm"] = (
                {"status": "SUCCESS", "successful_states": osm_result.get("successful_states", 0)}
                if not isinstance(osm_result, Exception)
                else {"status": "FAILED", "error": str(osm_result)}
            )

        # ── Phase 3: Cross-Source Deduplication ───────────────────────────────
        self._phase = "DEDUPLICATION"
        await workflow.wait_condition(lambda: not self._paused)

        if not self._cancelled:
            try:
                dedup_result = await workflow.execute_activity(
                    deduplicate_batch_activity,
                    args=[{"table": "us_leads", "batch_size": 5000}],
                    task_queue="data-pipeline",
                    start_to_close_timeout=timedelta(hours=4),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                self._phase_results["deduplication"] = {"status": "SUCCESS", **dedup_result}
            except ActivityError as exc:
                self._phase_results["deduplication"] = {"status": "FAILED", "error": str(exc)}
                workflow.logger.error("Deduplication phase FAILED: %s", exc)

        # ── Phase 4: Lead Enrichment ──────────────────────────────────────────
        self._phase = "ENRICHMENT"
        await workflow.wait_condition(lambda: not self._paused)

        if not self._cancelled:
            try:
                enrich_result = await workflow.execute_child_workflow(
                    LeadEnrichmentWorkflow.run,
                    args=[{
                        "sources": ["federal_raw", "gmaps_raw", "osm_raw"],
                        "source_table": "us_leads_raw",
                        "target_table": "us_leads",
                    }],
                    id=f"enrich-{workflow.info().workflow_id}",
                    task_queue="data-pipeline",
                    execution_timeout=timedelta(hours=8),
                )
                self._phase_results["enrichment"] = {"status": "SUCCESS", **enrich_result}
            except Exception as exc:
                self._phase_results["enrichment"] = {"status": "FAILED", "error": str(exc)}
                workflow.logger.error("Enrichment phase FAILED: %s", exc)

        self._phase  = "COMPLETED"
        self._status = "COMPLETED" if not self._cancelled else "CANCELLED"

        workflow.logger.info(
            "MasterOrchestrationWorkflow %s: phases=%s",
            self._status, list(self._phase_results.keys()),
        )

        return {
            "status": self._status,
            "phases_run": list(self._phase_results.keys()),
            "results": self._phase_results,
        }
