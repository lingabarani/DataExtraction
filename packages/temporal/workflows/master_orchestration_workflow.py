"""
DataExtraction — Master Orchestration Workflow (Top-Level Saga)
================================================================
Coordinates the complete 6-Agent Enterprise Intelligence Platform:
  Phase 1: Agent 1 – Official Registry Ingestion (registry-ingestion-queue)
  Phase 2: Agent 2 – Geospatial & Domain Discovery (geospatial-domain-queue)
  Phase 3: Agent 3 – Identity Resolution & Deduplication (identity-clustering-queue)
  Phase 4: Agent 4 – Executive Discovery & Contact Intelligence (executive-contact-queue)
  Phase 5: Agent 5 – Governance, Quality & Confidence Engine (governance-quality-queue)
  Phase 6: Agent 6 – Persistence, CDC & Search Synchronization (search-persistence-queue)

Supports live control via Signals (pause, resume, cancel_phase)
and live inspection via Queries (get_status).
"""

import asyncio
from datetime import timedelta
from typing import Any, Dict, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from packages.temporal.workflows.w1_registry_workflow import Agent1RegistryWorkflow
    from packages.temporal.workflows.w2_geospatial_workflow import Agent2GeospatialWorkflow
    from packages.temporal.workflows.w3_identity_workflow import Agent3IdentityWorkflow
    from packages.temporal.workflows.w4_executive_workflow import Agent4ExecutiveWorkflow
    from packages.temporal.workflows.w5_governance_workflow import Agent5GovernanceWorkflow
    from packages.temporal.workflows.w6_search_sync_workflow import Agent6SearchSyncWorkflow
    from packages.temporal.workflows.federal_ingestion_workflow import FederalIngestionWorkflow
    from packages.temporal.workflows.gmaps_extraction_workflow import GMapsExtractionWorkflow
    from packages.temporal.workflows.osm_state_workflow import OSMStateWorkflow
    from packages.temporal.workflows.lead_enrichment_workflow import LeadEnrichmentWorkflow
    from packages.temporal.activities.pipeline_activities import deduplicate_batch_activity
    from packages.temporal.activities.storage_activities import (
        maintain_kg_partitions_activity,
        sync_opensearch_cdc_activity,
        compute_bayesian_quality_activity,
    )
    from packages.infrastructure.config_manager import config_manager


@workflow.defn(name="MasterOrchestrationWorkflow")
class MasterOrchestrationWorkflow:
    """
    Top-level Master Saga that coordinates all 6 DataExtraction agents into a
    unified enterprise knowledge graph and OpenSearch search engine.

    Run topology:
        [Agent 1: Registry] ──────────┐
                                      ├──► [Agent 3: Identity] ──► [Agent 4: Executive]
        [Agent 2: GMaps + OSM] ───────┘                                    │
                                                                           ▼
        [OpenSearch CDC] ◄── [Agent 6: Persistence & CDC] ◄── [Agent 5: Governance & Quality]

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
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        workflow.logger.info("MasterOrchestrationWorkflow started: %s",
                             workflow.info().workflow_id)

        # ── Phase 1: Federal / Sovereign Registry Ingestion ───────────────────
        self._phase = "FEDERAL"
        await workflow.wait_condition(lambda: not self._paused)

        if not self._cancelled:
            try:
                # Use dedicated Agent 1 workflow if configured, otherwise legacy FederalIngestionWorkflow
                if "agent_1" in config:
                    fed_res = await workflow.execute_child_workflow(
                        Agent1RegistryWorkflow.run,
                        args=[config.get("agent_1", {})],
                        id=f"agent1-registry-{workflow.info().workflow_id}",
                        task_queue=config_manager.QUEUE_REGISTRY,
                        execution_timeout=timedelta(hours=24),
                    )
                else:
                    fed_res = await workflow.execute_child_workflow(
                        FederalIngestionWorkflow.run,
                        args=[config.get("federal", {})],
                        id=f"federal-{workflow.info().workflow_id}",
                        task_queue="federal-ingestion",
                        execution_timeout=timedelta(hours=24),
                    )
                self._phase_results["federal"] = {
                    "status": "SUCCESS",
                    "sources_successful": fed_res.get("sources_successful", 0),
                }
            except Exception as exc:
                self._phase_results["federal"] = {"status": "FAILED", "error": str(exc)}
                workflow.logger.error("Federal phase FAILED: %s", exc)

        # ── Phase 2: GMaps + OSM Geospatial Discovery ─────────────────────────
        self._phase = "EXTRACTION"
        await workflow.wait_condition(lambda: not self._paused)

        if not self._cancelled:
            try:
                if "agent_2" in config:
                    geo_res = await workflow.execute_child_workflow(
                        Agent2GeospatialWorkflow.run,
                        args=[config.get("agent_2", {})],
                        id=f"agent2-geo-{workflow.info().workflow_id}",
                        task_queue=config_manager.QUEUE_GEOSPATIAL,
                        execution_timeout=timedelta(hours=24),
                    )
                    self._phase_results["gmaps"] = {"status": "SUCCESS", **geo_res}
                    self._phase_results["osm"] = {"status": "SUCCESS", **geo_res}
                else:
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
            except Exception as exc:
                self._phase_results["extraction"] = {"status": "FAILED", "error": str(exc)}

        # ── Phase 3: Identity Resolution & Deduplication ──────────────────────
        self._phase = "DEDUPLICATION"
        await workflow.wait_condition(lambda: not self._paused)

        if not self._cancelled:
            try:
                if "agent_3" in config:
                    id_res = await workflow.execute_child_workflow(
                        Agent3IdentityWorkflow.run,
                        args=[config.get("agent_3", {})],
                        id=f"agent3-identity-{workflow.info().workflow_id}",
                        task_queue=config_manager.QUEUE_IDENTITY,
                        execution_timeout=timedelta(hours=8),
                    )
                    self._phase_results["deduplication"] = {"status": "SUCCESS", **id_res}
                else:
                    dedup_result = await workflow.execute_activity(
                        deduplicate_batch_activity,
                        args=[{"table": "us_leads", "batch_size": 5000}],
                        task_queue="data-pipeline",
                        start_to_close_timeout=timedelta(hours=4),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                    self._phase_results["deduplication"] = {"status": "SUCCESS", **dedup_result}
            except Exception as exc:
                self._phase_results["deduplication"] = {"status": "FAILED", "error": str(exc)}
                workflow.logger.error("Deduplication phase FAILED: %s", exc)

        # ── Phase 4: Lead Enrichment & Executive Discovery ────────────────────
        self._phase = "ENRICHMENT"
        await workflow.wait_condition(lambda: not self._paused)

        if not self._cancelled:
            try:
                if "agent_4" in config:
                    exec_res = await workflow.execute_child_workflow(
                        Agent4ExecutiveWorkflow.run,
                        args=[config.get("agent_4", {})],
                        id=f"agent4-exec-{workflow.info().workflow_id}",
                        task_queue=config_manager.QUEUE_EXECUTIVE,
                        execution_timeout=timedelta(hours=8),
                    )
                    self._phase_results["enrichment"] = {"status": "SUCCESS", **exec_res}
                else:
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

        # ── Phase 5: Governance, Quality & Confidence Engine ──────────────────
        if "agent_5" in config or config.get("run_governance", False):
            self._phase = "GOVERNANCE"
            await workflow.wait_condition(lambda: not self._paused)
            if not self._cancelled:
                try:
                    gov_res = await workflow.execute_child_workflow(
                        Agent5GovernanceWorkflow.run,
                        args=[config.get("agent_5", {})],
                        id=f"agent5-gov-{workflow.info().workflow_id}",
                        task_queue=config_manager.QUEUE_GOVERNANCE,
                        execution_timeout=timedelta(hours=4),
                    )
                    self._phase_results["governance"] = {"status": "SUCCESS", **gov_res}
                except Exception as exc:
                    self._phase_results["governance"] = {"status": "FAILED", "error": str(exc)}

        # ── Phase 6: Persistence, CDC & Search Synchronization ────────────────
        if "agent_6" in config or config.get("run_search_sync", False):
            self._phase = "SEARCH_SYNC"
            await workflow.wait_condition(lambda: not self._paused)
            if not self._cancelled:
                try:
                    sync_res = await workflow.execute_child_workflow(
                        Agent6SearchSyncWorkflow.run,
                        args=[config.get("agent_6", {})],
                        id=f"agent6-sync-{workflow.info().workflow_id}",
                        task_queue=config_manager.QUEUE_SEARCH,
                        execution_timeout=timedelta(hours=4),
                    )
                    self._phase_results["search_sync"] = {"status": "SUCCESS", **sync_res}
                except Exception as exc:
                    self._phase_results["search_sync"] = {"status": "FAILED", "error": str(exc)}

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
