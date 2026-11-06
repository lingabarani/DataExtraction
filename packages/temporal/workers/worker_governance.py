"""
DataExtraction — Worker 5: Governance, Quality & Confidence Engine
==================================================================
Queue: governance-quality-queue
Handles: Agent 5 Bayesian Quality Scoring, Field Lineage, and DLQ Auditing.
Run with: python -m packages.temporal.workers.worker_governance
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
from packages.temporal.config import QUEUE_GOVERNANCE, WORKER_MAX_ACTIVITIES
from packages.temporal.activities.storage_activities import (
    compute_bayesian_quality_activity,
    fetch_dlq_records_activity,
    resolve_dlq_record_activity,
    get_dlq_stats_activity,
    storage_query_activity,
    evaluate_working_governance_activity,
    promote_certified_to_master_activity,
    apply_freshness_decay_activity,
    fetch_overdue_revalidations_activity,
    stage_overdue_for_reharvest_activity,
)
from packages.temporal.workflows.w5_governance_workflow import Agent5GovernanceWorkflow
from packages.temporal.workflows.dlq_replay_workflow import DLQReplayWorkflow
from packages.temporal.workflows.promotion_gate_workflow import PromotionGateWorkflow
from packages.temporal.workflows.revalidation_sweep_workflow import RevalidationSweepWorkflow

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger("dataextraction.worker.governance")

TASK_QUEUE = QUEUE_GOVERNANCE
MAX_ACTIVITIES = WORKER_MAX_ACTIVITIES.get(QUEUE_GOVERNANCE, 8)


async def run_worker():
    client = await get_temporal_client()
    logger.info("Starting Worker 5 (Governance, Quality & Confidence Engine) on queue: %s", TASK_QUEUE)

    activities = [
        compute_bayesian_quality_activity,
        fetch_dlq_records_activity,
        resolve_dlq_record_activity,
        get_dlq_stats_activity,
        storage_query_activity,
        evaluate_working_governance_activity,
        promote_certified_to_master_activity,
        apply_freshness_decay_activity,
        fetch_overdue_revalidations_activity,
        stage_overdue_for_reharvest_activity,
    ]
    workflows = [
        Agent5GovernanceWorkflow,
        DLQReplayWorkflow,
        PromotionGateWorkflow,
        RevalidationSweepWorkflow,
    ]

    primary_worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    storage_worker = Worker(
        client,
        task_queue="storage-ops",
        workflows=workflows,
        activities=activities,
        max_concurrent_activities=MAX_ACTIVITIES,
    )

    logger.info("Worker 5 is online and ready for quality & compliance audits.")
    await asyncio.gather(primary_worker.run(), storage_worker.run())


def main():
    try:
        asyncio.run(run_worker())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker 5 shutdown requested. Exiting cleanly.")


if __name__ == "__main__":
    main()

