"""
DataExtraction — Agent 4: Executive Discovery & Contact Intelligence Workflow
=============================================================================
Queue: executive-contact-queue
Worker: packages.temporal.workers.worker_executive

Orchestrates professional people & contact discovery:
- 5-Tier Contact Validation (Syntax, MX DNS, Disposable check, SMTP handshake, E.164 phone)
- Executive discovery & person canonicalization
- Bitemporal employment relationship mapping
- Corporate hierarchy linking (parent-subsidiary)
- Enterprise technology stack profiling
- Signals: pause, resume
- Queries: get_status
"""

from datetime import timedelta
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.pipeline_activities import (
        validate_contacts_activity,
        build_leads_activity,
    )
    from packages.temporal.activities.storage_activities import (
        ingest_kg_person_activity,
        ingest_kg_employment_activity,
        ingest_kg_hierarchy_activity,
        ingest_kg_technology_activity,
    )
    from packages.infrastructure.config_manager import config_manager

TASK_QUEUE = config_manager.QUEUE_EXECUTIVE

EXECUTIVE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError"],
)


@workflow.defn(name="Agent4ExecutiveWorkflow")
class Agent4ExecutiveWorkflow:
    """
    Agent 4 Workflow: Executive Discovery & Contact Intelligence.
    Extracts leadership, links bitemporal career graphs, and validates communication channels.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._step: str = "INIT"
        self._paused: bool = False
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 4] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 4] Resume signal received")
        self._paused = False

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 4 - Executive Discovery & Contact Intelligence",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "step": self._step,
            "paused": self._paused,
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        self._status = "RUNNING"
        table = config.get("source_table", "companies")
        limit = config.get("contact_batch_limit", 5000)

        workflow.logger.info("[Agent 4] Executive Contact Intelligence started on queue: %s", TASK_QUEUE)

        # ── Step 1: 5-Tier Contact Validation ─────────────────────────────────
        self._step = "CONTACT_VALIDATION"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            val_res = await workflow.execute_activity(
                validate_contacts_activity,
                args=[table, limit],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=2),
                retry_policy=EXECUTIVE_RETRY_POLICY,
            )
            self._results["contact_validation"] = {"status": "SUCCESS", **val_res}
        except Exception as exc:
            self._results["contact_validation"] = {"status": "FAILED", "error": str(exc)}

        # ── Step 2: Build Enriched Lead Records ────────────────────────────────
        self._step = "BUILD_LEADS"
        await workflow.wait_condition(lambda: not self._paused)
        try:
            target_table = config.get("target_table", "us_leads")
            b_res = await workflow.execute_activity(
                build_leads_activity,
                args=[table, target_table],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=3),
                retry_policy=EXECUTIVE_RETRY_POLICY,
            )
            self._results["build_leads"] = {"status": "SUCCESS", **b_res}
        except Exception as exc:
            self._results["build_leads"] = {"status": "FAILED", "error": str(exc)}

        # ── Step 3: Ingest Person Entities if provided ────────────────────────
        self._step = "PERSON_INGESTION"
        persons = config.get("persons", [])
        if persons:
            person_outcomes = []
            for p in persons:
                try:
                    p_res = await workflow.execute_activity(
                        ingest_kg_person_activity,
                        args=[p],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=EXECUTIVE_RETRY_POLICY,
                    )
                    person_outcomes.append(p_res)
                except Exception as exc:
                    person_outcomes.append({"status": "FAILED", "error": str(exc)})
            self._results["persons"] = person_outcomes

        # ── Step 4: Ingest Employment & Hierarchy Relationships ───────────────
        self._step = "RELATIONSHIP_INGESTION"
        employments = config.get("employments", [])
        if employments:
            emp_outcomes = []
            for emp in employments:
                try:
                    e_res = await workflow.execute_activity(
                        ingest_kg_employment_activity,
                        args=[emp],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=EXECUTIVE_RETRY_POLICY,
                    )
                    emp_outcomes.append(e_res)
                except Exception as exc:
                    emp_outcomes.append({"status": "FAILED", "error": str(exc)})
            self._results["employments"] = emp_outcomes

        hierarchies = config.get("hierarchies", [])
        if hierarchies:
            h_outcomes = []
            for h in hierarchies:
                try:
                    h_res = await workflow.execute_activity(
                        ingest_kg_hierarchy_activity,
                        args=[h],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=EXECUTIVE_RETRY_POLICY,
                    )
                    h_outcomes.append(h_res)
                except Exception as exc:
                    h_outcomes.append({"status": "FAILED", "error": str(exc)})
            self._results["hierarchies"] = h_outcomes

        # ── Step 5: Ingest Technology Stacks ──────────────────────────────────
        technologies = config.get("technologies", [])
        if technologies:
            tech_outcomes = []
            for t in technologies:
                try:
                    t_res = await workflow.execute_activity(
                        ingest_kg_technology_activity,
                        args=[t],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(minutes=10),
                        retry_policy=EXECUTIVE_RETRY_POLICY,
                    )
                    tech_outcomes.append(t_res)
                except Exception as exc:
                    tech_outcomes.append({"status": "FAILED", "error": str(exc)})
            self._results["technologies"] = tech_outcomes

        self._step = "COMPLETED"
        self._status = "COMPLETED"
        return {
            "status": self._status,
            "results": self._results,
        }

