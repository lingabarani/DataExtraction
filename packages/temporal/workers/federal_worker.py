"""
DataExtraction — Federal Ingestion Worker
==========================================
Registers all federal activities and workflows on the `federal-ingestion` task queue.
Run with: python -m packages.temporal.workers.federal_worker
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
    fetch_dlq_records_activity,
    resolve_dlq_record_activity,
    get_dlq_stats_activity,
    storage_query_activity,
    check_gmp_budget_activity,
)
from packages.temporal.workflows.federal_ingestion_workflow import FederalIngestionWorkflow
from packages.temporal.workflows.master_orchestration_workflow import MasterOrchestrationWorkflow
from packages.temporal.workflows.dlq_replay_workflow import DLQReplayWorkflow

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.federal")

TASK_QUEUE   = os.getenv("TEMPORAL_TASK_QUEUE_PREFIX", "federal-ingestion")
MAX_ACTIVITIES = int(os.getenv("FEDERAL_WORKER_MAX_CONCURRENT_ACTIVITIES", "3"))
MAX_WORKFLOWS  = int(os.getenv("FEDERAL_WORKER_MAX_CONCURRENT_WORKFLOW_TASKS", "10"))


async def run_worker():
    client = await get_temporal_client()
    logger.info(
        "Federal worker starting: task_queue=%s max_activities=%d",
        TASK_QUEUE, MAX_ACTIVITIES,
    )

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            FederalIngestionWorkflow,
            MasterOrchestrationWorkflow,
            DLQReplayWorkflow,
        ],
        activities=[
            run_cms_npi_activity,
            run_sec_edgar_activity,
            run_fdic_activity,
            run_usaspending_activity,
            run_propublica_activity,
            run_sam_gov_activity,
            normalize_batch_activity,
            fetch_dlq_records_activity,
            resolve_dlq_record_activity,
            get_dlq_stats_activity,
            storage_query_activity,
            check_gmp_budget_activity,
        ],
        max_concurrent_activities=MAX_ACTIVITIES,
        max_concurrent_workflow_tasks=MAX_WORKFLOWS,
    )

    # Graceful shutdown on SIGTERM / SIGINT
    shutdown_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received — draining in-flight activities...")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler for all signals

    async with worker:
        logger.info("Federal worker READY on queue: %s", TASK_QUEUE)
        await shutdown_event.wait()
        logger.info("Federal worker shutting down gracefully")


if __name__ == "__main__":
    asyncio.run(run_worker())
