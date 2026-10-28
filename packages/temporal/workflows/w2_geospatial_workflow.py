"""
DataExtraction — Agent 2: Geospatial & Domain Discovery Workflow
================================================================
Queue: geospatial-domain-queue
Worker: packages.temporal.workers.worker_geospatial

Orchestrates multi-channel spatial discovery:
- Google Maps Place API & quadrant tiling
- OpenStreetMap Overpass bounding box extraction
- Geographic standardization & coordinate bounding validation
- Signals: pause, resume, cancel_region
- Queries: get_status
"""

import asyncio
from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.gmaps_activities import (
        run_gmaps_collection_activity,
        run_gmaps_website_verification_activity,
    )
    from packages.temporal.activities.osm_activities import (
        run_osm_state_extraction_activity,
    )
    from packages.temporal.activities.pipeline_activities import (
        validate_geo_activity,
    )
    from packages.infrastructure.config_manager import config_manager

TASK_QUEUE = config_manager.QUEUE_GEOSPATIAL

GEOSPATIAL_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=4,
    non_retryable_error_types=["PermissionError"],
)


@workflow.defn(name="Agent2GeospatialWorkflow")
class Agent2GeospatialWorkflow:
    """
    Agent 2 Workflow: Geospatial & Domain Discovery.
    Orchestrates high-throughput physical storefront, quadrant, and state-level extraction.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._paused: bool = False
        self._cancelled_regions: set[str] = set()
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 2] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 2] Resume signal received")
        self._paused = False

    @workflow.signal
    def cancel_region(self, region: str) -> None:
        workflow.logger.warning("[Agent 2] Cancel region signal received: %s", region)
        self._cancelled_regions.add(region.upper())

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 2 - Geospatial & Domain Discovery",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "paused": self._paused,
            "cancelled_regions": list(self._cancelled_regions),
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        self._status = "RUNNING"
        workflow.logger.info("[Agent 2] Geospatial Discovery started on queue: %s", TASK_QUEUE)

        regions = config.get("regions", ["US-CA", "US-TX", "US-NY"])
        states = config.get("states", ["CA", "TX", "NY"])

        # Filter out cancelled regions
        active_regions = [r for r in regions if r.upper() not in self._cancelled_regions]
        active_states = [s for s in states if s.upper() not in self._cancelled_regions]

        await workflow.wait_condition(lambda: not self._paused)

        # ── Step 1: GMaps Collection Branch ───────────────────────────────────
        gmaps_tasks = []
        for reg in active_regions:
            task = workflow.execute_activity(
                run_gmaps_collection_activity,
                args=[reg, config.get("category", "commercial"), config.get("tile_config", {})],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=GEOSPATIAL_RETRY_POLICY,
            )
            gmaps_tasks.append(task)

        # ── Step 2: OSM State Extraction Branch ───────────────────────────────
        osm_tasks = []
        for st in active_states:
            task = workflow.execute_activity(
                run_osm_state_extraction_activity,
                args=[st, config.get("osm_config", {})],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=GEOSPATIAL_RETRY_POLICY,
            )
            osm_tasks.append(task)

        # Execute both branches concurrently
        workflow.logger.info("[Agent 2] Executing GMaps (%d regions) & OSM (%d states) in parallel",
                              len(active_regions), len(active_states))

        all_results = await asyncio.gather(*gmaps_tasks, *osm_tasks, return_exceptions=True)

        gmaps_out = all_results[:len(active_regions)]
        osm_out = all_results[len(active_regions):]

        self._results["gmaps"] = [
            r if not isinstance(r, Exception) else {"status": "FAILED", "error": str(r)}
            for r in gmaps_out
        ]
        self._results["osm"] = [
            r if not isinstance(r, Exception) else {"status": "FAILED", "error": str(r)}
            for r in osm_out
        ]

        # ── Step 3: Geographic Standardization & Validation ───────────────────
        await workflow.wait_condition(lambda: not self._paused)
        geo_validation_table = config.get("target_table", "companies")
        try:
            geo_res = await workflow.execute_activity(
                validate_geo_activity,
                args=[geo_validation_table, config.get("geo_batch_limit", 10000)],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=1),
                retry_policy=GEOSPATIAL_RETRY_POLICY,
            )
            self._results["geo_validation"] = {"status": "SUCCESS", **geo_res}
        except Exception as exc:
            self._results["geo_validation"] = {"status": "FAILED", "error": str(exc)}

        self._status = "COMPLETED"
        return {
            "status": self._status,
            "regions_processed": len(active_regions),
            "states_processed": len(active_states),
            "results": self._results,
        }
