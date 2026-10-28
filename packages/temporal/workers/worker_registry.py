"""
DataExtraction — Worker 1: Official Registry Intelligence
=========================================================
Queue: registry-ingestion-queue
Handles: Agent 1 Official Registry Ingestion activities and workflows.
Run with: python -m packages.temporal.workers.worker_registry
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
from packages.temporal.activities.federal_activities import (
    run_cms_npi_activity,
    run_sec_edgar_activity,
    run_fdic_activity,
    run_usaspending_activity,
    run_propublica_activity,
    run_sam_gov_activity,
)
from packages.temporal.activities.pipeline_activities import normalize_batch_activity
from packages.temporal.activities.storage_activities import (
    ingest_kg_observation_activity,
    storage_query_activity,
)
from packages.temporal.workflows.w1_registry_workflow import Agent1RegistryWorkflow
from packages.temporal.workflows.federal_ingestion_workflow import FederalIngestionWorkflow

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.registry")

TASK_QUEUE = config_manager.QUEUE_REGISTRY
LEGACY_QUEUE = "federal-ingestion"
MAX_ACTIVITIES = int(os.getenv("REGISTRY_WORKER_MAX_CONCURRENT_ACTIVITIES", "6"))


async def run_worker():
    client = await get_temporal_client()
    logger.info("Starting Worker 1 (Registry Intelligence) on queues: %s, %s", TASK_QUEUE, LEGACY_QUEUE)

    activities = [
        run_cms_npi_activity,
        run_sec_edgar_activity,
        run_fdic_activity,
        run_usaspending_activity,
        run_propublica_activity,
        run_sam_gov_activity,
        normalize_batch_activity,
        ingest_kg_observation_activity,
        storage_query_activity,
    ]
    workflows = [
        Agent1RegistryWorkflow,
        FederalIngestionWorkflow,
    ]

    primary_worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    legacy_worker = Worker(
        client,
        task_queue=LEGACY_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    logger.info("Worker 1 is online and polling tasks.")
    await asyncio.gather(primary_worker.run(), legacy_worker.run())


def main():
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker 1 shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    main()
