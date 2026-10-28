"""
DataExtraction — Worker 4: Executive Discovery & Contact Intelligence
=====================================================================
Queue: executive-contact-queue
Handles: Agent 4 Executive Discovery, 5-Tier Contact Validation, and Lead Builder.
Run with: python -m packages.temporal.workers.worker_executive
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
    validate_contacts_activity,
    build_leads_activity,
)
from packages.temporal.activities.storage_activities import (
    ingest_kg_person_activity,
    ingest_kg_employment_activity,
    ingest_kg_hierarchy_activity,
    ingest_kg_technology_activity,
    storage_query_activity,
)
from packages.temporal.workflows.w4_executive_workflow import Agent4ExecutiveWorkflow
from packages.temporal.workflows.lead_enrichment_workflow import LeadEnrichmentWorkflow

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.executive")

TASK_QUEUE = config_manager.QUEUE_EXECUTIVE
MAX_ACTIVITIES = int(os.getenv("EXECUTIVE_WORKER_MAX_CONCURRENT_ACTIVITIES", "10"))


async def run_worker():
    client = await get_temporal_client()
    logger.info("Starting Worker 4 (Executive & Contact Intelligence) on queue: %s", TASK_QUEUE)

    activities = [
        validate_contacts_activity,
        build_leads_activity,
        ingest_kg_person_activity,
        ingest_kg_employment_activity,
        ingest_kg_hierarchy_activity,
        ingest_kg_technology_activity,
        storage_query_activity,
    ]
    workflows = [
        Agent4ExecutiveWorkflow,
        LeadEnrichmentWorkflow,
    ]

    primary_worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    pipeline_worker = Worker(
        client,
        task_queue="data-pipeline",
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    logger.info("Worker 4 is online and polling executive intelligence tasks.")
    await asyncio.gather(primary_worker.run(), pipeline_worker.run())


def main():
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker 4 shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    main()

