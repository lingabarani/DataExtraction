"""
DataExtraction — GMaps Extraction Worker
=========================================
Registers gmaps activities and workflows on the `gmaps-extraction` task queue.
Run with: python -m packages.temporal.workers.gmaps_worker
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from temporalio.worker import Worker

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from packages.temporal.client import get_temporal_client
from packages.temporal.activities.gmaps_activities import (
    run_gmaps_collection_activity,
    run_gmaps_website_verification_activity,
    run_gmaps_website_crawl_activity,
    run_gmaps_export_activity,
)
from packages.temporal.activities.storage_activities import check_gmp_budget_activity
from packages.temporal.workflows.gmaps_extraction_workflow import (
    GMapsExtractionWorkflow,
    GMapsRegionWorkflow,
)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.gmaps")

TASK_QUEUE     = "gmaps-extraction"
MAX_ACTIVITIES = int(os.getenv("GMAPS_WORKER_MAX_CONCURRENT_ACTIVITIES", "5"))
MAX_WORKFLOWS  = int(os.getenv("GMAPS_WORKER_MAX_CONCURRENT_WORKFLOW_TASKS", "20"))


async def run_worker():
    client = await get_temporal_client()
    logger.info("GMaps worker starting: task_queue=%s max_activities=%d",
                TASK_QUEUE, MAX_ACTIVITIES)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            GMapsExtractionWorkflow,
            GMapsRegionWorkflow,
        ],
        activities=[
            run_gmaps_collection_activity,
            run_gmaps_website_verification_activity,
            run_gmaps_website_crawl_activity,
            run_gmaps_export_activity,
            check_gmp_budget_activity,
        ],
        max_concurrent_activities=MAX_ACTIVITIES,
        max_concurrent_workflow_tasks=MAX_WORKFLOWS,
    )

    shutdown_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received — draining activities...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    async with worker:
        logger.info("GMaps worker READY on queue: %s", TASK_QUEUE)
        await shutdown_event.wait()
        logger.info("GMaps worker shutting down gracefully")


if __name__ == "__main__":
    asyncio.run(run_worker())
