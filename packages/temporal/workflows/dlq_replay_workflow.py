"""
DataExtraction — DLQ Replay Workflow
======================================
Replays failed records from the Dead Letter Queue in controlled batches.
Triggered automatically by DataQualityAgent or on-demand via the API.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.storage_activities import (
        fetch_dlq_records_activity,
        resolve_dlq_record_activity,
        get_dlq_stats_activity,
    )
    from packages.temporal.activities.federal_activities import (
        run_cms_npi_activity, run_sec_edgar_activity,
        run_fdic_activity, run_usaspending_activity,
        run_propublica_activity, run_sam_gov_activity,
    )

# Map DLQ activity names to their function references
ACTIVITY_MAP = {
    "run_cms_npi": run_cms_npi_activity,
    "run_sec_edgar": run_sec_edgar_activity,
    "run_fdic": run_fdic_activity,
    "run_usaspending": run_usaspending_activity,
    "run_propublica": run_propublica_activity,
    "run_sam_gov": run_sam_gov_activity,
}

TASK_QUEUE_MAP = {
    "run_cms_npi": "federal-ingestion",
    "run_sec_edgar": "federal-ingestion",
    "run_fdic": "federal-ingestion",
    "run_usaspending": "federal-ingestion",
    "run_propublica": "federal-ingestion",
    "run_sam_gov": "federal-ingestion",
}

DLQ_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=30),
    maximum_attempts=1,  # Single attempt per DLQ item — re-enqueue on failure
)


@workflow.defn(name="DLQReplayWorkflow")
class DLQReplayWorkflow:
    """
    Replays pending DLQ records in a controlled batch.

    For each record:
    1. Fetch from DLQ table
    2. Re-execute the original failed activity (with conservative retry)
    3. Mark RESOLVED on success, ESCALATED on repeated failure

    Agent trigger: DataQualityAgent auto-triggers when DLQ < threshold
    Manual trigger: POST /api/v1/pipelines/start?type=dlq_replay
    """

    def __init__(self) -> None:
        self._replayed: int = 0
        self._failed: int = 0
        self._escalated: int = 0

    @workflow.query
    def get_status(self) -> dict:
        return {
            "workflow_id": workflow.info().workflow_id,
            "replayed": self._replayed,
            "failed": self._failed,
            "escalated": self._escalated,
            "total_processed": self._replayed + self._failed + self._escalated,
        }

    @workflow.run
    async def run(self, config: dict) -> dict:
        limit = config.get("limit", 100)
        mode  = config.get("mode", "auto")  # "auto" | "manual"
        source_filter = config.get("source")  # Optional: filter by source

        workflow.logger.info(
            "DLQReplayWorkflow: limit=%d mode=%s source=%s",
            limit, mode, source_filter or "all",
        )

        # Fetch pending DLQ records
        records_result = await workflow.execute_activity(
            fetch_dlq_records_activity,
            args=[{"limit": limit, "status": "PENDING", "source": source_filter}],
            task_queue="storage-ops",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        records = records_result.get("records", [])
        workflow.logger.info("DLQ: fetched %d records to replay", len(records))

        for record in records:
            record_id       = record.get("id", "")
            activity_name   = record.get("source_activity", "")
            payload         = record.get("payload", {})
            retry_count     = record.get("retry_count", 0)
            task_queue      = TASK_QUEUE_MAP.get(activity_name, "federal-ingestion")
            activity_fn     = ACTIVITY_MAP.get(activity_name)

            if not activity_fn:
                workflow.logger.warning("Unknown DLQ activity: %s — escalating", activity_name)
                await workflow.execute_activity(
                    resolve_dlq_record_activity,
                    args=[record_id, "ESCALATED", f"Unknown activity: {activity_name}"],
                    task_queue="storage-ops",
                    start_to_close_timeout=timedelta(seconds=30),
                )
                self._escalated += 1
                continue

            try:
                await workflow.execute_activity(
                    activity_fn,
                    args=[payload],
                    task_queue=task_queue,
                    start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=DLQ_RETRY,
                )
                await workflow.execute_activity(
                    resolve_dlq_record_activity,
                    args=[record_id, "RESOLVED", "Auto-replayed successfully"],
                    task_queue="storage-ops",
                    start_to_close_timeout=timedelta(seconds=30),
                )
                self._replayed += 1
                workflow.logger.info("DLQ record %s RESOLVED: %s", record_id, activity_name)

            except ActivityError as exc:
                self._failed += 1
                if retry_count >= 2:
                    await workflow.execute_activity(
                        resolve_dlq_record_activity,
                        args=[record_id, "ESCALATED",
                              f"Failed after {retry_count + 1} replay attempts: {exc}"],
                        task_queue="storage-ops",
                        start_to_close_timeout=timedelta(seconds=30),
                    )
                    self._escalated += 1
                    workflow.logger.error("DLQ record %s ESCALATED after %d attempts",
                                         record_id, retry_count + 1)
                else:
                    workflow.logger.error("DLQ record %s replay failed (attempt %d): %s",
                                         record_id, retry_count + 1, exc)

        return {
            "mode": mode,
            "records_fetched": len(records),
            "replayed": self._replayed,
            "failed": self._failed,
            "escalated": self._escalated,
        }
