"""
DataExtraction — Lead Enrichment Workflow
==========================================
Post-ingestion pipeline: normalize → deduplicate → validate → build leads.
Triggered automatically after federal/gmaps/osm workflows complete.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.pipeline_activities import (
        normalize_batch_activity,
        deduplicate_batch_activity,
        validate_contacts_activity,
        validate_tax_ids_activity,
        validate_geo_activity,
        build_leads_activity,
    )

PIPELINE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=3,
)


@workflow.defn(name="LeadEnrichmentWorkflow")
class LeadEnrichmentWorkflow:
    """
    Runs the full data enrichment pipeline for specified source tables.

    Pipeline:
        1. Normalize raw records (field standardization)
        2. Deduplicate (fuzzy merge across sources)
        3. Validate contacts (phone + email)
        4. Validate tax IDs (EIN/TIN)
        5. Validate geography (lat/lng, ZIP)
        6. Build enriched lead records

    Triggered by: PipelineCoordinatorAgent or MasterOrchestrationWorkflow
    """

    def __init__(self) -> None:
        self._phase: str = "INIT"
        self._results: dict = {}

    @workflow.query
    def get_status(self) -> dict:
        return {
            "workflow_id": workflow.info().workflow_id,
            "phase": self._phase,
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict) -> dict:
        sources      = config.get("sources", ["federal_raw"])
        source_table = config.get("source_table", "federal_raw")
        target_table = config.get("target_table", "us_leads")
        batch_size   = config.get("batch_size", 5000)
        limit        = config.get("limit", 100000)

        workflow.logger.info(
            "LeadEnrichmentWorkflow: sources=%s %s → %s",
            sources, source_table, target_table,
        )

        # ── Step 1: Normalize ─────────────────────────────────────────────────
        self._phase = "NORMALIZE"
        for source in sources:
            try:
                result = await workflow.execute_activity(
                    normalize_batch_activity,
                    args=[{"source": source.upper(), "table": source_table,
                           "batch_size": batch_size}],
                    task_queue="data-pipeline",
                    start_to_close_timeout=timedelta(hours=2),
                    retry_policy=PIPELINE_RETRY,
                )
                self._results[f"normalize_{source}"] = result
            except ActivityError as exc:
                workflow.logger.error("Normalization failed for %s: %s", source, exc)

        # ── Step 2: Deduplicate ──────────────────────────────────────────────
        self._phase = "DEDUPLICATE"
        try:
            dedup = await workflow.execute_activity(
                deduplicate_batch_activity,
                args=[{"table": source_table, "batch_size": batch_size}],
                task_queue="data-pipeline",
                start_to_close_timeout=timedelta(hours=4),
                retry_policy=PIPELINE_RETRY,
            )
            self._results["deduplicate"] = dedup
        except ActivityError as exc:
            workflow.logger.error("Deduplication failed: %s", exc)

        # ── Step 3: Validate Contacts ─────────────────────────────────────────
        self._phase = "VALIDATE_CONTACTS"
        try:
            contacts = await workflow.execute_activity(
                validate_contacts_activity,
                args=[{"table": source_table, "limit": limit}],
                task_queue="data-pipeline",
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=PIPELINE_RETRY,
            )
            self._results["validate_contacts"] = contacts
        except ActivityError as exc:
            workflow.logger.error("Contact validation failed: %s", exc)

        # ── Step 4: Validate Tax IDs ──────────────────────────────────────────
        self._phase = "VALIDATE_TAX"
        try:
            tax = await workflow.execute_activity(
                validate_tax_ids_activity,
                args=[{"table": source_table, "limit": limit}],
                task_queue="data-pipeline",
                start_to_close_timeout=timedelta(hours=1),
                retry_policy=PIPELINE_RETRY,
            )
            self._results["validate_tax"] = tax
        except ActivityError as exc:
            workflow.logger.error("Tax ID validation failed: %s", exc)

        # ── Step 5: Validate Geography ────────────────────────────────────────
        self._phase = "VALIDATE_GEO"
        try:
            geo = await workflow.execute_activity(
                validate_geo_activity,
                args=[{"table": source_table, "limit": limit}],
                task_queue="data-pipeline",
                start_to_close_timeout=timedelta(hours=1),
                retry_policy=PIPELINE_RETRY,
            )
            self._results["validate_geo"] = geo
        except ActivityError as exc:
            workflow.logger.error("Geo validation failed: %s", exc)

        # ── Step 6: Build Leads ───────────────────────────────────────────────
        self._phase = "BUILD_LEADS"
        try:
            leads = await workflow.execute_activity(
                build_leads_activity,
                args=[{"source_table": source_table, "target_table": target_table}],
                task_queue="data-pipeline",
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=PIPELINE_RETRY,
            )
            self._results["build_leads"] = leads
        except ActivityError as exc:
            workflow.logger.error("Lead building failed: %s", exc)

        self._phase = "COMPLETED"
        return {
            "sources": sources,
            "source_table": source_table,
            "target_table": target_table,
            "phases_completed": list(self._results.keys()),
            "results": self._results,
        }
