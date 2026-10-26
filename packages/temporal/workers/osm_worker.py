"""
DataExtraction — OSM Extraction Worker
======================================
Registers OSM extraction activities and workflows on the `osm-extraction` task queue.
Run with: python -m packages.temporal.workers.osm_worker
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from temporalio.worker import Worker

# Resolve project root for consistent imports
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from packages.temporal.client import get_temporal_client
from packages.temporal.activities.osm_activities import (
    run_osm_state_extraction_activity,
    run_osm_checkpoint_recovery_activity,
    run_osm_circuit_breaker_reset_activity,
)
from packages.temporal.workflows.osm_state_workflow import (
    OSMStateWorkflow,
    OSMSingleStateWorkflow,
)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.osm")

TASK_QUEUE = os.getenv("OSM_TASK_QUEUE", "osm-extraction")
MAX_ACTIVITIES = int(os.getenv("OSM_WORKER_MAX_CONCURRENT_ACTIVITIES", "4"))
MAX_WORKFLOWS = int(os.getenv("OSM_WORKER_MAX_CONCURRENT_WORKFLOW_TASKS", "10"))


async def run_worker():
    client = await get_temporal_client()
    logger.info(
        "OSM worker starting: task_queue=%s max_activities=%d",
        TASK_QUEUE,
        MAX_ACTIVITIES,
    )

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            OSMStateWorkflow,
            OSMSingleStateWorkflow,
        ],
        activities=[
            run_osm_state_extraction_activity,
            run_osm_checkpoint_recovery_activity,
            run_osm_circuit_breaker_reset_activity,
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
        logger.info("OSM worker READY on queue: %s", TASK_QUEUE)
        await shutdown_event.wait()
        logger.info("OSM worker drained and stopped cleanly.")


def main():
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("OSM worker terminated.")


if __name__ == "__main__":
    main()
