"""
DataExtraction — Agent 3: Identity Resolution & Entity Clustering Workflow
==========================================================================
Queue: identity-clustering-queue
Worker: packages.temporal.workers.worker_identity

Orchestrates multi-signal identity resolution:
- Legal entity name standardization & token cleaning
- Tax identifier validation (EIN 9-digit / RFC modulo-11)
- Probabilistic deduplication & Fellegi-Sunter / Splink clustering
- Canonical organization golden record persistence
- Reversible cluster unmerging ($O(1)$ dispute handling)
- Signals: pause, resume, unmerge_member
- Queries: get_status
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.pipeline_activities import (
        normalize_batch_activity,
        deduplicate_batch_activity,
        validate_tax_ids_activity,
    )
    from packages.temporal.activities.storage_activities import (
        resolve_cluster_membership_activity,
        unmerge_cluster_member_activity,
        ingest_kg_organization_activity,
    )
    from packages.infrastructure.config_manager import config_manager

TASK_QUEUE = config_manager.QUEUE_IDENTITY

IDENTITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError"],
)


@workflow.defn(name="Agent3IdentityWorkflow")
class Agent3IdentityWorkflow:
    """
    Agent 3 Workflow: Identity Resolution & Entity Clustering.
    Binds fragmented observations into reversible identity clusters and canonical organizations.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._step: str = "INIT"
        self._paused: bool = False
        self._unmerge_requests: List[Dict[str, Any]] = []
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 3] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 3] Resume signal received")
        self._paused = False

    @workflow.signal
    def unmerge_member(self, request: dict) -> None:
        workflow.logger.warning("[Agent 3] Received unmerge member request: %s", request)
        self._unmerge_requests.append(request)

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 3 - Identity Resolution & Deduplication",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "step": self._step,
            "paused": self._paused,
            "pending_unmerges": len(self._unmerge_requests),
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        self._status = "RUNNING"
        target_table = config.get("target_table", "companies")
        batch_size = config.get("batch_size", 5000)

        workflow.logger.info("[Agent 3] Identity Resolution started on queue: %s", TASK_QUEUE)

        # ── Step 1: Legal Entity Normalization ─────────────────────────────────
        self._step = "NORMALIZATION"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            norm_res = await workflow.execute_activity(
                normalize_batch_activity,
                args=[config.get("source", "REGISTRY_MERGED"), target_table, batch_size],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=IDENTITY_RETRY_POLICY,
            )
            self._results["normalization"] = {"status": "SUCCESS", **norm_res}
        except Exception as exc:
            self._results["normalization"] = {"status": "FAILED", "error": str(exc)}

        # ── Step 2: Tax Identifier Validation (EIN/TIN/RFC) ────────────────────
        self._step = "TAX_VALIDATION"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            tax_res = await workflow.execute_activity(
                validate_tax_ids_activity,
                args=[target_table, batch_size],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=IDENTITY_RETRY_POLICY,
            )
            self._results["tax_validation"] = {"status": "SUCCESS", **tax_res}
        except Exception as exc:
            self._results["tax_validation"] = {"status": "FAILED", "error": str(exc)}

        # ── Step 3: Probabilistic Deduplication & Entity Resolution ───────────
        self._step = "DEDUPLICATION"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            dedup_res = await workflow.execute_activity(
                deduplicate_batch_activity,
                args=[target_table, batch_size],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=4),
                retry_policy=IDENTITY_RETRY_POLICY,
            )
            self._results["deduplication"] = {"status": "SUCCESS", **dedup_res}
        except Exception as exc:
            self._results["deduplication"] = {"status": "FAILED", "error": str(exc)}

        # ── Step 4: Identity Cluster Membership & Canonical Golden Record ─────
        self._step = "CLUSTER_RESOLUTION"
        cluster_records = config.get("cluster_records", [])
        if cluster_records:
            cluster_outcomes = []
            for rec in cluster_records:
                try:
                    c_res = await workflow.execute_activity(
                        resolve_cluster_membership_activity,
                        args=[rec],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(minutes=30),
                        retry_policy=IDENTITY_RETRY_POLICY,
                    )
                    cluster_outcomes.append(c_res)
                except Exception as exc:
                    cluster_outcomes.append({"status": "FAILED", "error": str(exc)})
            self._results["cluster_membership"] = cluster_outcomes

        # ── Step 5: Process Any Dynamic Operator Unmerge Signals ───────────────
        self._step = "UNMERGE_DISPUTES"
        if self._unmerge_requests:
            unmerge_results = []
            for req in self._unmerge_requests:
                try:
                    u_res = await workflow.execute_activity(
                        unmerge_cluster_member_activity,
                        args=[req],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(minutes=15),
                        retry_policy=IDENTITY_RETRY_POLICY,
                    )
                    unmerge_results.append(u_res)
                except Exception as exc:
                    unmerge_results.append({"status": "FAILED", "error": str(exc)})
            self._results["unmerges_executed"] = unmerge_results
            self._unmerge_requests.clear()

        self._step = "COMPLETED"
        self._status = "COMPLETED"
        return {
            "status": self._status,
            "results": self._results,
        }
