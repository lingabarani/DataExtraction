"""
DataExtraction — Worker 3: Identity Resolution & Entity Clustering
==================================================================
Queue: identity-clustering-queue
Handles: Agent 3 Identity Resolution, Splink clustering, tax validation, and unmerges.
Run with: python -m packages.temporal.workers.worker_identity
"""

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from temporalio.worker import Worker

REPO_ROOT = Path(__file__).resolve().parents[3]
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure"), str(REPO_ROOT / "packages" / "pipeline")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.temporal.client import get_temporal_client
from packages.infrastructure.config_manager import config_manager
from packages.temporal.activities.pipeline_activities import (
    normalize_batch_activity,
    validate_tax_ids_activity,
    deduplicate_batch_activity,
)
from packages.temporal.activities.storage_activities import (
    resolve_cluster_membership_activity,
    unmerge_cluster_member_activity,
    ingest_kg_organization_activity,
    storage_query_activity,
)
from packages.temporal.workflows.w3_identity_workflow import Agent3IdentityWorkflow

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.identity")

TASK_QUEUE = config_manager.QUEUE_IDENTITY
MAX_ACTIVITIES = int(os.getenv("IDENTITY_WORKER_MAX_CONCURRENT_ACTIVITIES", "8"))


async def run_worker():
    client = await get_temporal_client()
    logger.info("Starting Worker 3 (Identity Resolution & Entity Clustering) on queue: %s", TASK_QUEUE)

    activities = [
        normalize_batch_activity,
        validate_tax_ids_activity,
        deduplicate_batch_activity,
        resolve_cluster_membership_activity,
        unmerge_cluster_member_activity,
        ingest_kg_organization_activity,
        storage_query_activity,
    ]
    workflows = [
        Agent3IdentityWorkflow,
    ]

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    logger.info("Worker 3 is online and ready for entity resolution jobs.")
    await worker.run()


def main():
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker 3 shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    main()

