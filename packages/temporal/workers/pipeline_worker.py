"""
DataExtraction — Pipeline & Storage Worker
==========================================
Registers pipeline + storage activities on `data-pipeline` and `storage-ops` task queues.
This single worker handles both queues to simplify deployment.
Run with: python -m packages.temporal.workers.pipeline_worker
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
from packages.temporal.activities.pipeline_activities import (
    normalize_batch_activity,
    deduplicate_batch_activity,
    validate_contacts_activity,
    validate_tax_ids_activity,
    validate_geo_activity,
    build_leads_activity,
)
from packages.temporal.activities.storage_activities import (
    fetch_dlq_records_activity,
    resolve_dlq_record_activity,
    get_dlq_stats_activity,
    storage_query_activity,
    check_gmp_budget_activity,
)
from packages.temporal.activities.osm_activities import (
    run_osm_state_extraction_activity,
    run_osm_checkpoint_recovery_activity,
    run_osm_circuit_breaker_reset_activity,
)
from packages.temporal.workflows.lead_enrichment_workflow import LeadEnrichmentWorkflow
from packages.temporal.workflows.osm_state_workflow import (
    OSMStateWorkflow,
    OSMSingleStateWorkflow,
)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.pipeline")

PIPELINE_QUEUE = "data-pipeline"
STORAGE_QUEUE  = "storage-ops"
OSM_QUEUE      = "osm-extraction"

MAX_PIPELINE = int(os.getenv("PIPELINE_WORKER_MAX_CONCURRENT_ACTIVITIES", "8"))
MAX_STORAGE  = int(os.getenv("STORAGE_WORKER_MAX_CONCURRENT_ACTIVITIES", "10"))


async def run_workers():
    client = await get_temporal_client()

    # Shared activities — registered on all queues this worker handles
    pipeline_activities = [
        normalize_batch_activity, deduplicate_batch_activity,
        validate_contacts_activity, validate_tax_ids_activity,
        validate_geo_activity, build_leads_activity,
    ]
    storage_activities = [
        fetch_dlq_records_activity, resolve_dlq_record_activity,
        get_dlq_stats_activity, storage_query_activity, check_gmp_budget_activity,
    ]
    osm_activities = [
        run_osm_state_extraction_activity, run_osm_checkpoint_recovery_activity,
        run_osm_circuit_breaker_reset_activity,
    ]

    pipeline_worker = Worker(
        client,
        task_queue=PIPELINE_QUEUE,
        workflows=[LeadEnrichmentWorkflow],
        activities=pipeline_activities + storage_activities,
        max_concurrent_activities=MAX_PIPELINE,
    )
    storage_worker = Worker(
        client,
        task_queue=STORAGE_QUEUE,
        workflows=[],
        activities=storage_activities,
        max_concurrent_activities=MAX_STORAGE,
    )
    osm_worker = Worker(
        client,
        task_queue=OSM_QUEUE,
        workflows=[OSMStateWorkflow, OSMSingleStateWorkflow],
        activities=osm_activities,
        max_concurrent_activities=int(os.getenv("OSM_WORKER_MAX_CONCURRENT_ACTIVITIES", "4")),
    )

    shutdown_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received — draining workers...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass

    logger.info("Starting pipeline/storage/osm workers...")

    async with pipeline_worker, storage_worker, osm_worker:
        logger.info(
            "Workers READY: queues=[%s, %s, %s]",
            PIPELINE_QUEUE, STORAGE_QUEUE, OSM_QUEUE,
        )
        await shutdown_event.wait()
        logger.info("Workers shutting down gracefully")


if __name__ == "__main__":
    asyncio.run(run_workers())
