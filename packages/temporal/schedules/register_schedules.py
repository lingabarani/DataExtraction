"""
DataExtraction — Schedule Registration
========================================
Registers all Temporal cron schedules on startup.
Reads schedule definitions from config/schedules.yaml.

Run once at deployment:
    python -m packages.temporal.schedules.register_schedules

Run to list active schedules:
    python -m packages.temporal.schedules.register_schedules --list

Run to delete all schedules (use with caution):
    python -m packages.temporal.schedules.register_schedules --delete-all
"""

import asyncio
import logging
import sys
from pathlib import Path

import yaml
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleSpec,
    ScheduleAlreadyRunningError,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from packages.temporal.client import get_temporal_client
from packages.temporal.workflows.federal_ingestion_workflow import FederalIngestionWorkflow
from packages.temporal.workflows.gmaps_extraction_workflow import GMapsExtractionWorkflow
from packages.temporal.workflows.osm_state_workflow import OSMStateWorkflow
from packages.temporal.workflows.dlq_replay_workflow import DLQReplayWorkflow

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s")
logger = logging.getLogger("dataextraction.schedules")

CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "schedules.yaml"

WORKFLOW_MAP = {
    "FederalIngestionWorkflow":  FederalIngestionWorkflow,
    "GMapsExtractionWorkflow":   GMapsExtractionWorkflow,
    "OSMStateWorkflow":          OSMStateWorkflow,
    "DLQReplayWorkflow":         DLQReplayWorkflow,
}

TASK_QUEUE_MAP = {
    "FederalIngestionWorkflow":  "federal-ingestion",
    "GMapsExtractionWorkflow":   "gmaps-extraction",
    "OSMStateWorkflow":          "osm-extraction",
    "DLQReplayWorkflow":         "storage-ops",
}


async def register_schedules(client: Client, config: dict) -> None:
    schedules = config.get("schedules", {})

    for schedule_key, sched_cfg in schedules.items():
        schedule_id   = sched_cfg["id"]
        workflow_name = sched_cfg["workflow"]
        cron_expr     = sched_cfg["cron"]
        input_data    = sched_cfg.get("input", {})
        paused        = sched_cfg.get("paused", False)

        workflow_class = WORKFLOW_MAP.get(workflow_name)
        task_queue     = TASK_QUEUE_MAP.get(workflow_name, "federal-ingestion")

        if not workflow_class:
            logger.warning("Unknown workflow '%s' in schedule '%s' — skipping",
                           workflow_name, schedule_key)
            continue

        try:
            await client.create_schedule(
                schedule_id,
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        workflow_class.run,
                        input_data,
                        id=f"{schedule_id}-auto",
                        task_queue=task_queue,
                    ),
                    spec=ScheduleSpec(cron_expressions=[cron_expr]),
                    state=type(
                        "ScheduleState", (),
                        {"paused": paused, "notes": f"Auto-registered by register_schedules.py"}
                    )(),
                ),
            )
            logger.info("✅ Registered schedule: %s [%s] → %s",
                        schedule_id, cron_expr, workflow_name)

        except ScheduleAlreadyRunningError:
            logger.info("⏭  Schedule already exists: %s — skipping", schedule_id)
        except Exception as exc:
            logger.error("❌ Failed to register schedule %s: %s", schedule_id, exc)


async def list_schedules(client: Client) -> None:
    print("\nActive Temporal Schedules:")
    print(f"{'ID':40} {'NEXT RUN':30} {'STATUS'}")
    print("─" * 85)
    async for sched in await client.list_schedules():
        next_run = str(sched.info.next_action_times[0]) if sched.info.next_action_times else "N/A"
        status   = "PAUSED" if sched.info.paused else "ACTIVE"
        print(f"{sched.id:40} {next_run:30} {status}")


async def delete_all_schedules(client: Client) -> None:
    deleted = 0
    async for sched in await client.list_schedules():
        handle = client.get_schedule_handle(sched.id)
        await handle.delete()
        logger.info("Deleted schedule: %s", sched.id)
        deleted += 1
    logger.info("Deleted %d schedules", deleted)


async def main():
    mode = "--list" if "--list" in sys.argv else (
        "--delete-all" if "--delete-all" in sys.argv else "register"
    )

    client = await get_temporal_client()

    if mode == "--list":
        await list_schedules(client)
        return

    if mode == "--delete-all":
        confirm = input("⚠  Delete ALL schedules? Type 'yes' to confirm: ")
        if confirm == "yes":
            await delete_all_schedules(client)
        else:
            print("Aborted.")
        return

    # Default: register
    if not CONFIG_PATH.exists():
        logger.error("Schedule config not found: %s", CONFIG_PATH)
        sys.exit(1)

    config = yaml.safe_load(CONFIG_PATH.read_text())
    await register_schedules(client, config)
    logger.info("Schedule registration complete.")


if __name__ == "__main__":
    asyncio.run(main())
