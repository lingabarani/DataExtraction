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
        populate_working_organizations_activity,
    )
    from packages.temporal.activities.storage_activities import (
        resolve_cluster_membership_activity,
        unmerge_cluster_member_activity,
        ingest_working_organization_activity,
        ingest_kg_organization_activity,
    )
    from packages.temporal.config import QUEUE_IDENTITY, IDENTITY_RETRY_POLICY

TASK_QUEUE = QUEUE_IDENTITY


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
        try:
            wf_id = workflow.info().workflow_id
        except Exception:
            wf_id = "test-env"
        return {
            "agent": "Agent 3 - Identity Resolution & Deduplication",
            "workflow_id": wf_id,
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
        target_table = config.get("target_table", "staging_dataextraction.staging_companies")
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

        # ── Step 4: Populate Pre-Master Working Organizations Canvas ──────────
        # Sprint 2 Redirection: Canonical entities are materialized directly into
        # staging_dataextraction.working_organizations with PENDING verification statuses.
        # Master database receives 0 writes here.
        self._step = "POPULATE_WORKING_LAYER"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            pop_res = await workflow.execute_activity(
                populate_working_organizations_activity,
                args=[target_table, batch_size],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=IDENTITY_RETRY_POLICY,
            )
            self._results["populate_working_layer"] = {"status": "SUCCESS", **pop_res}
        except Exception as exc:
            self._results["populate_working_layer"] = {"status": "FAILED", "error": str(exc)}

        # ── Step 5: Identity Cluster Membership & Canonical Working Record ────
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
                    # Also stage working organization
                    await workflow.execute_activity(
                        ingest_working_organization_activity,
                        args=[rec],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=IDENTITY_RETRY_POLICY,
                    )
                except Exception as exc:
                    cluster_outcomes.append({"status": "FAILED", "error": str(exc)})
            self._results["cluster_membership"] = cluster_outcomes

        # ── Step 6: Process Any Dynamic Operator Unmerge Signals ───────────────
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

        # ── Final Outcome Computation ──────────────────────────────────────────
        dedup_info = self._results.get("deduplication", {})
        norm_info = self._results.get("normalization", {})
        pop_info = self._results.get("populate_working_layer", {})

        clusters_count = (
            dedup_info.get("clusters_resolved")
            or dedup_info.get("merged")
            or dedup_info.get("splink_matches")
            or len(self._results.get("cluster_membership", []))
            or 0
        )

        step_statuses = [
            v.get("status") for v in self._results.values() if isinstance(v, dict) and "status" in v
        ]
        if step_statuses and all(s == "FAILED" for s in step_statuses):
            self._status = "FAILED"
            self._step = "FAILED"
        else:
            self._status = "COMPLETED"
            self._step = "COMPLETED"

        return {
            "status": self._status,
            "clusters_resolved": clusters_count,
            "records_normalized": norm_info.get("normalized", 0),
            "records_deduped": dedup_info.get("merged", 0) + dedup_info.get("splink_matches", 0),
            "organizations_staged": pop_info.get("populated", 0),
            "results": self._results,
        }

