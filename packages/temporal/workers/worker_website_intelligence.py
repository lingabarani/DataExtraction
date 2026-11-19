"""
DataExtraction — Worker 8: Website Intelligence & Enrichment
============================================================
Queue: website-intelligence-queue
Handles: Agent 8 Website candidate resolution, SSRF verification,
multi-page crawling, field cross-verification, tech stack discovery,
and C-suite executive extraction.

Run with: python -m packages.temporal.workers.worker_website_intelligence
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
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure"), str(GMAPS_SRC)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.metrics import start_worker_metrics_server
from packages.infrastructure.structured_logger import get_structured_logger
from packages.temporal.client import get_temporal_client
from packages.temporal.config import QUEUE_WEBSITE_INTELLIGENCE, WORKER_MAX_ACTIVITIES
from packages.temporal.activities.website_intelligence_activities import (
    run_website_candidate_resolution_activity,
    run_website_verification_activity,
    run_website_crawl_and_enrichment_activity,
)
from packages.temporal.workflows.w8_website_intelligence_workflow import (
    Agent8WebsiteIntelligenceWorkflow,
)

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = get_structured_logger("dataextraction.worker.website_intelligence").bind(source="worker_website_intelligence")

TASK_QUEUE = QUEUE_WEBSITE_INTELLIGENCE
MAX_ACTIVITIES = WORKER_MAX_ACTIVITIES.get(QUEUE_WEBSITE_INTELLIGENCE, 8)
METRICS_PORT = int(os.getenv("WEBSITE_INTELLIGENCE_METRICS_PORT", "9108"))


async def run_worker():
    start_worker_metrics_server(METRICS_PORT)
    client = await get_temporal_client()
    logger.info("Starting Worker 8 (Website Intelligence & Enrichment) on queue: %s", TASK_QUEUE)

    activities = [
        run_website_candidate_resolution_activity,
        run_website_verification_activity,
        run_website_crawl_and_enrichment_activity,
    ]
    workflows = [
        Agent8WebsiteIntelligenceWorkflow,
    ]

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received for Worker 8")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    logger.info("Worker 8 is running and listening on queue: %s", TASK_QUEUE)
    try:
        await worker.run()
    except asyncio.CancelledError:
        logger.info("Worker 8 cancelled")
    finally:
        logger.info("Worker 8 stopped cleanly")


if __name__ == "__main__":
    asyncio.run(run_worker())
