"""
DataExtraction — Worker 7: Email Discovery & Verification
==========================================================
Queue: email-enrichment-queue
Handles: Asynchronous web crawling, obfuscation decoding, DNS MX resolution,
         and non-intrusive SMTP RCPT TO mailbox handshake verification.
Run with: python -m packages.temporal.workers.worker_email_enrichment
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
from packages.temporal.config import QUEUE_EMAIL_ENRICHMENT, WORKER_MAX_ACTIVITIES
from packages.temporal.activities.email_enrichment_activities import (
    create_enrichment_job_activity,
    fetch_pending_enrichment_batch_activity,
    enrich_email_batch_activity,
    finalize_enrichment_job_activity,
)
from packages.temporal.workflows.w7_email_enrichment_workflow import (
    EmailEnrichmentWorkflow,
    Agent7EmailEnrichmentWorkflow,
)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.email_enrichment")

TASK_QUEUE = QUEUE_EMAIL_ENRICHMENT
MAX_ACTIVITIES = WORKER_MAX_ACTIVITIES.get(QUEUE_EMAIL_ENRICHMENT, 10)


async def run_worker():
    client = await get_temporal_client()
    logger.info("Starting Worker 7 (Email Discovery & Verification) on queue: %s", TASK_QUEUE)

    activities = [
        create_enrichment_job_activity,
        fetch_pending_enrichment_batch_activity,
        enrich_email_batch_activity,
        finalize_enrichment_job_activity,
    ]
    workflows = [
        EmailEnrichmentWorkflow,
        Agent7EmailEnrichmentWorkflow,
    ]

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    logger.info("Worker 7 is online and ready for email discovery and SMTP verification jobs.")
    await worker.run()


def main():
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker 7 shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    main()

