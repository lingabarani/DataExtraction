"""
DataExtraction — Agent 7: Enterprise Email Discovery & Verification Workflow
=============================================================================
Queue: email-enrichment-queue
Worker: packages.temporal.workers.worker_email_enrichment

Business Rule Enforcement:
- Executes strictly post-deduplication on canonical entities (is_canonical=TRUE).
- Coordinates chunked keyset batching, web scraping, and active SMTP verification.
- Signals: pause, resume
- Queries: get_status
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.config import (
        QUEUE_EMAIL_ENRICHMENT,
        EMAIL_ENRICHMENT_RETRY_POLICY,
        STANDARD_ACTIVITY_TIMEOUT,
    )
    from packages.temporal.activities.email_enrichment_activities import (
        create_enrichment_job_activity,
        fetch_pending_enrichment_batch_activity,
        enrich_email_batch_activity,
        finalize_enrichment_job_activity,
    )

TASK_QUEUE = QUEUE_EMAIL_ENRICHMENT


@workflow.defn(name="EmailEnrichmentWorkflow")
class EmailEnrichmentWorkflow:
    """
    Enterprise Email Enrichment & SMTP Handshake Verification Workflow.
    Durable saga executing post-deduplication to discover corporate emails.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._step: str = "INIT"
        self._paused: bool = False
        self._job_id: Optional[str] = None
        self._total_processed: int = 0
        self._total_successful: int = 0
        self._total_failed: int = 0
        self._last_processed_id: Optional[str] = None

    @workflow.signal
    def pause(self) -> None:
        """Pauses enrichment execution before the next batch."""
        workflow.logger.warning("[Email Enrichment] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        """Resumes paused enrichment execution."""
        workflow.logger.info("[Email Enrichment] Resume signal received")
        self._paused = False

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """Returns real-time execution status and metrics."""
        return {
            "workflow": "Agent 7 - Email Discovery & SMTP Verification",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "step": self._step,
            "paused": self._paused,
            "job_id": self._job_id,
            "total_processed": self._total_processed,
            "total_successful": self._total_successful,
            "total_failed": self._total_failed,
            "last_processed_id": self._last_processed_id,
        }

    @workflow.run
    async def run(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = config or {}
        self._status = "RUNNING"
        self._step = "STARTING"

        batch_size = config.get("batch_size", 200)
        max_records = config.get("max_records", 5000)
        probe_smtp = config.get("probe_smtp", True)
        verify_dedup = config.get("verify_dedup_completed", True)
        target_table = config.get("target_table", "staging_dataextraction.working_organizations")

        workflow.logger.info(
            "[Email Enrichment] Workflow started (queue=%s, target=%s, max_records=%d, verify_dedup=%s)",
            TASK_QUEUE, target_table, max_records, verify_dedup,
        )

        # ── Step 1: Create Job Record ─────────────────────────────────────────
        self._step = "CREATE_JOB"
        self._job_id = await workflow.execute_activity(
            create_enrichment_job_activity,
            args=["POST_DEDUP_CANONICAL", target_table, batch_size, 50],
            task_queue=TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=EMAIL_ENRICHMENT_RETRY_POLICY,
        )

        # ── Step 2: Keyset Pagination Chunked Batch Loop ──────────────────────
        self._step = "ENRICHMENT_LOOP"
        error_msg: Optional[str] = None

        try:
            while self._total_processed < max_records:
                await workflow.wait_condition(lambda: not self._paused)

                remaining = max_records - self._total_processed
                fetch_limit = min(batch_size, remaining)

                # Fetch batch of canonical records requiring email discovery
                batch: List[Dict[str, Any]] = await workflow.execute_activity(
                    fetch_pending_enrichment_batch_activity,
                    args=[self._last_processed_id, fetch_limit, target_table],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=EMAIL_ENRICHMENT_RETRY_POLICY,
                )

                if not batch:
                    workflow.logger.info("[Email Enrichment] No further canonical records requiring discovery.")
                    break

                # Execute async crawl, domain tech analysis, and SMTP verification
                batch_res: Dict[str, Any] = await workflow.execute_activity(
                    enrich_email_batch_activity,
                    args=[batch, self._job_id, probe_smtp],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=STANDARD_ACTIVITY_TIMEOUT,
                    retry_policy=EMAIL_ENRICHMENT_RETRY_POLICY,
                )

                processed = batch_res.get("processed", 0)
                successful = batch_res.get("successful", 0)
                failed = batch_res.get("failed", 0)
                self._last_processed_id = batch_res.get("last_id") or self._last_processed_id

                self._total_processed += processed
                self._total_successful += successful
                self._total_failed += failed

                workflow.logger.info(
                    "[Email Enrichment] Batch completed: +%d processed (+%d successful, +%d failed). Total: %d",
                    processed, successful, failed, self._total_processed,
                )

                # If returned less than requested limit, end of queue reached
                if len(batch) < fetch_limit:
                    break

        except Exception as exc:
            error_msg = str(exc)
            workflow.logger.error("[Email Enrichment] Workflow failed with error: %s", exc)
            self._status = "FAILED"

        # ── Step 3: Finalize Job ───────────────────────────────────────────────
        self._step = "FINALIZE"
        if self._job_id:
            await workflow.execute_activity(
                finalize_enrichment_job_activity,
                args=[self._job_id, error_msg],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=EMAIL_ENRICHMENT_RETRY_POLICY,
            )

        if not error_msg:
            self._status = "COMPLETED"
        self._step = "DONE"

        return {
            "status": self._status,
            "job_id": self._job_id,
            "total_processed": self._total_processed,
            "total_successful": self._total_successful,
            "total_failed": self._total_failed,
            "last_processed_id": self._last_processed_id,
        }


# Standard alias for backward compatibility with 7-Agent nomenclature
Agent7EmailEnrichmentWorkflow = EmailEnrichmentWorkflow

