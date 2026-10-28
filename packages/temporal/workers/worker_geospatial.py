"""
DataExtraction — Worker 2: Geospatial & Domain Intelligence
===========================================================
Queue: geospatial-domain-queue
Handles: Agent 2 Geospatial & Domain Discovery activities and workflows.
Run with: python -m packages.temporal.workers.worker_geospatial
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from temporalio.worker import Worker

REPO_ROOT = Path(__file__).resolve().parents[3]
GMAPS_SRC = REPO_ROOT / "packages" / "scrapers" / "google_maps" / "src"
OSM_SRC = REPO_ROOT / "packages" / "scrapers" / "open_map" / "src"
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure"), str(GMAPS_SRC), str(OSM_SRC)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.temporal.client import get_temporal_client
from packages.infrastructure.config_manager import config_manager
from packages.temporal.activities.gmaps_activities import (
    run_gmaps_collection_activity,
    run_gmaps_website_verification_activity,
    run_gmaps_website_crawl_activity,
    run_gmaps_export_activity,
)
from packages.temporal.activities.osm_activities import (
    run_osm_state_extraction_activity,
    run_osm_checkpoint_recovery_activity,
    run_osm_circuit_breaker_reset_activity,
)
from packages.temporal.activities.pipeline_activities import validate_geo_activity
from packages.temporal.activities.storage_activities import (
    ingest_kg_observation_activity,
    check_gmp_budget_activity,
    storage_query_activity,
)
from packages.temporal.workflows.w2_geospatial_workflow import Agent2GeospatialWorkflow
from packages.temporal.workflows.gmaps_extraction_workflow import GMapsExtractionWorkflow
from packages.temporal.workflows.osm_state_workflow import OSMStateWorkflow, OSMSingleStateWorkflow

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.geospatial")

TASK_QUEUE = config_manager.QUEUE_GEOSPATIAL
MAX_ACTIVITIES = int(os.getenv("GEOSPATIAL_WORKER_MAX_CONCURRENT_ACTIVITIES", "12"))


async def run_worker():
    client = await get_temporal_client()
    logger.info("Starting Worker 2 (Geospatial & Domain Intelligence) on queue: %s", TASK_QUEUE)

    activities = [
        run_gmaps_collection_activity,
        run_gmaps_website_verification_activity,
        run_gmaps_website_crawl_activity,
        run_gmaps_export_activity,
        run_osm_state_extraction_activity,
        run_osm_checkpoint_recovery_activity,
        run_osm_circuit_breaker_reset_activity,
        validate_geo_activity,
        ingest_kg_observation_activity,
        check_gmp_budget_activity,
        storage_query_activity,
    ]
    workflows = [
        Agent2GeospatialWorkflow,
        GMapsExtractionWorkflow,
        OSMStateWorkflow,
        OSMSingleStateWorkflow,
    ]

    primary_worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    gmaps_worker = Worker(
        client,
        task_queue="gmaps-extraction",
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    osm_worker = Worker(
        client,
        task_queue="osm-extraction",
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    logger.info("Worker 2 is online and polling tasks across spatial queues.")
    await asyncio.gather(primary_worker.run(), gmaps_worker.run(), osm_worker.run())


def main():
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker 2 shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    main()
