"""
DataExtraction — GMaps Extraction Workflow
==========================================
3-phase pipeline: Collection (parallel regions) → Website Verification → Crawl.
Child workflow per region/category tile runs concurrently.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.gmaps_activities import (
        run_gmaps_collection_activity,
        run_gmaps_website_verification_activity,
        run_gmaps_website_crawl_activity,
        run_gmaps_export_activity,
    )
    from packages.temporal.activities.storage_activities import check_gmp_budget_activity

GMAPS_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=30),
    maximum_attempts=3,
)

DEFAULT_REGIONS = [
    "US-CA", "US-TX", "US-NY", "US-FL", "US-IL",
    "US-PA", "US-OH", "US-GA", "US-NC", "US-MI",
]
DEFAULT_CATEGORIES = [
    "restaurant", "hotel", "retail",
    "healthcare", "professional_services",
]


@workflow.defn(name="GMapsRegionWorkflow")
class GMapsRegionWorkflow:
    """Child workflow: single region + category tile collection."""

    @workflow.run
    async def run(self, config: dict) -> dict:
        region   = config["region"]
        category = config["category"]
        tile_cfg = config.get("tile_config", {})

        result = await workflow.execute_activity(
            run_gmaps_collection_activity,
            args=[region, category, tile_cfg],
            task_queue="gmaps-extraction",
            start_to_close_timeout=timedelta(hours=4),
            heartbeat_timeout=timedelta(minutes=10),
            retry_policy=GMAPS_RETRY,
        )
        return result


@workflow.defn(name="GMapsExtractionWorkflow")
class GMapsExtractionWorkflow:
    """
    Top-level GMaps workflow.

    Phase 1: Parallel region × category collection (N child workflows)
    Phase 2: Website URL verification batch
    Phase 3: Website crawl batch (extract emails/phones)
    Phase 4 (optional): GMP enrichment if budget authorized
    """

    def __init__(self) -> None:
        self._phase: str = "INIT"
        self._collection_results: list = []
        self._paused: bool = False

    @workflow.signal
    def pause(self) -> None:
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        self._paused = False

    @workflow.signal
    def throttle(self, config: dict) -> None:
        """Reduce concurrency — called by ResourceManagerAgent when DB pool is strained."""
        workflow.logger.warning("THROTTLE signal received: config=%s", config)
        # Future: propagate to child workflows

    @workflow.query
    def get_status(self) -> dict:
        return {
            "workflow_id": workflow.info().workflow_id,
            "phase": self._phase,
            "paused": self._paused,
            "collection_results": len(self._collection_results),
        }

    @workflow.run
    async def run(self, config: dict) -> dict:
        regions    = config.get("regions") or DEFAULT_REGIONS
        if regions == "all":
            regions = DEFAULT_REGIONS
        categories = config.get("categories") or DEFAULT_CATEGORIES
        batch_id   = workflow.info().workflow_id

        workflow.logger.info(
            "GMapsExtractionWorkflow: %d regions × %d categories",
            len(regions), len(categories),
        )

        # ── Phase 1: Parallel collection ────────────────────────────────────
        self._phase = "COLLECTION"
        await workflow.wait_condition(lambda: not self._paused)

        child_handles = []
        for region in regions:
            for category in categories:
                handle = await workflow.start_child_workflow(
                    GMapsRegionWorkflow.run,
                    args=[{"region": region, "category": category,
                           "tile_config": config.get("tile_config", {})}],
                    id=f"gmaps-region-{region}-{category}-{batch_id[:8]}",
                    task_queue="gmaps-extraction",
                )
                child_handles.append((region, category, handle))

        # Gather all child workflow results (allow individual failures)
        for region, category, handle in child_handles:
            try:
                result = await handle
                self._collection_results.append({"region": region, "category": category,
                                                  "status": "SUCCESS", **result})
            except Exception as exc:
                self._collection_results.append({"region": region, "category": category,
                                                  "status": "FAILED", "error": str(exc)})
                workflow.logger.error("Region %s/%s failed: %s", region, category, exc)

        # ── Phase 2: Website Verification ────────────────────────────────────
        self._phase = "VERIFICATION"
        await workflow.wait_condition(lambda: not self._paused)

        try:
            verification_result = await workflow.execute_activity(
                run_gmaps_website_verification_activity,
                args=[batch_id, config.get("verification_limit", 10000)],
                task_queue="gmaps-extraction",
                start_to_close_timeout=timedelta(hours=8),
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=GMAPS_RETRY,
            )
        except ActivityError as exc:
            workflow.logger.error("Website verification failed: %s", exc)
            verification_result = {"status": "FAILED", "error": str(exc)}

        # ── Phase 3: Website Crawl ───────────────────────────────────────────
        self._phase = "CRAWL"
        await workflow.wait_condition(lambda: not self._paused)

        try:
            crawl_result = await workflow.execute_activity(
                run_gmaps_website_crawl_activity,
                args=[batch_id],
                task_queue="gmaps-extraction",
                start_to_close_timeout=timedelta(hours=12),
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=GMAPS_RETRY,
            )
        except ActivityError as exc:
            workflow.logger.error("Website crawl failed: %s", exc)
            crawl_result = {"status": "FAILED", "error": str(exc)}

        # ── Phase 4: Optional GMP Enrichment ─────────────────────────────────
        self._phase = "ENRICHMENT"
        enrichment_result = {"authorized": False, "reason": "Budget check skipped"}
        try:
            budget = await workflow.execute_activity(
                check_gmp_budget_activity,
                args=[{}],
                task_queue="storage-ops",
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            enrichment_result = {"authorized": budget.get("authorized", False),
                                 "budget_remaining_usd": budget.get("budget_remaining_usd", 0)}
        except ActivityError:
            pass  # Enrichment is optional — never fail the workflow for budget check

        self._phase = "COMPLETED"
        successful = sum(1 for r in self._collection_results if r["status"] == "SUCCESS")
        return {
            "batch_id": batch_id,
            "regions": len(regions),
            "categories": len(categories),
            "tiles_successful": successful,
            "tiles_failed": len(self._collection_results) - successful,
            "verification": verification_result,
            "crawl": crawl_result,
            "enrichment": enrichment_result,
        }
