"""
DataExtraction — Worker 6: Persistence, CDC & Search Synchronization
====================================================================
Queue: search-persistence-queue
Handles: Agent 6 Knowledge Graph partition maintenance and OpenSearch 2.x CDC sync.
Run with: python -m packages.temporal.workers.worker_search
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from temporalio.worker import Worker

REPO_ROOT = Path(__file__).resolve().parents[3]
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.temporal.client import get_temporal_client
from packages.infrastructure.config_manager import config_manager
from packages.temporal.activities.storage_activities import (
    maintain_kg_partitions_activity,
    sync_opensearch_cdc_activity,
    storage_query_activity,
)
from packages.temporal.workflows.w6_search_sync_workflow import Agent6SearchSyncWorkflow

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.search")

TASK_QUEUE = config_manager.QUEUE_SEARCH
MAX_ACTIVITIES = int(os.getenv("SEARCH_WORKER_MAX_CONCURRENT_ACTIVITIES", "4"))


async def run_worker():
    client = await get_temporal_client()
    logger.info("Starting Worker 6 (Persistence, CDC & Search Synchronization) on queue: %s", TASK_QUEUE)

    activities = [
        maintain_kg_partitions_activity,
        sync_opensearch_cdc_activity,
        storage_query_activity,
    ]
    workflows = [
        Agent6SearchSyncWorkflow,
    ]

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    logger.info("Worker 6 is online and ready for partition maintenance & CDC sync jobs.")
    await worker.run()


def main():
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker 6 shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    main()

