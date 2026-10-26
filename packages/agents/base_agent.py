"""
DataExtraction — BaseAgent Abstract Class
==========================================
All AI agents inherit from this. Enforces the observe → decide → act loop,
human approval gating, Temporal-only side effects, and mandatory audit logging.
"""

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger("dataextraction.agents.base")


@dataclass
class AgentDecision:
    """
    Immutable decision produced by an agent's decide() method.

    Every decision MUST have a rationale — no silent actions.
    """
    action: str                             # "start_workflow" | "signal_workflow" | "alert" | "noop"
    workflow_id: str = ""                   # For signal_workflow: existing workflow ID
    workflow_type: str = ""                 # For start_workflow: Workflow class name
    workflow_task_queue: str = ""           # Task queue override (default from TASK_QUEUE_MAP)
    signal_name: str = ""                   # For signal_workflow: signal method name
    payload: dict = field(default_factory=dict)
    rationale: str = ""                     # MANDATORY — logged to audit table
    confidence: float = 0.0                 # 0.0–1.0 (informational)
    requires_human_approval: bool = False   # If True, persisted to approval queue


WORKFLOW_TASK_QUEUE_MAP = {
    "FederalIngestionWorkflow":      "federal-ingestion",
    "GMapsExtractionWorkflow":       "gmaps-extraction",
    "OSMStateWorkflow":              "osm-extraction",
    "LeadEnrichmentWorkflow":        "data-pipeline",
    "DLQReplayWorkflow":             "storage-ops",
    "MasterOrchestrationWorkflow":   "federal-ingestion",
}


class BaseAgent(ABC):
    """
    Abstract base for all DataExtraction agents.

    Rules enforced here:
    1. Agents act ONLY via Temporal SDK (no direct DB writes)
    2. Every action is logged to the agent_audit_log table
    3. requires_human_approval=True blocks automatic action
    4. All side effects are async and idempotent
    """

    def __init__(self, name: str, config: dict):
        self.name         = name
        self.config       = config
        self.logger       = logging.getLogger(f"dataextraction.agents.{name}")
        self._cycle_count = 0

    @abstractmethod
    async def observe(self) -> dict:
        """Collect current system state. Must be read-only / side-effect-free."""
        ...

    @abstractmethod
    async def decide(self, observations: dict) -> AgentDecision:
        """Analyze observations and return a typed decision with mandatory rationale."""
        ...

    async def act(self, decision: AgentDecision) -> dict:
        """
        Execute the decision via Temporal SDK.
        Blocks on human approval if requires_human_approval=True.
        """
        # Always log the decision to audit
        await self._audit_log(decision)

        if decision.action == "noop":
            self.logger.debug("NOOP: %s", decision.rationale)
            return {"action": "noop", "rationale": decision.rationale}

        if decision.requires_human_approval and self._human_approval_required():
            self.logger.warning(
                "Decision requires human approval — persisting to approval queue: %s",
                decision.rationale,
            )
            await self._persist_approval_request(decision)
            return {"action": "pending_approval", "decision_id": str(uuid4()),
                    "rationale": decision.rationale}

        from packages.temporal.client import get_temporal_client
        client = await get_temporal_client()

        if decision.action == "start_workflow":
            task_queue = (
                decision.workflow_task_queue
                or WORKFLOW_TASK_QUEUE_MAP.get(decision.workflow_type, "federal-ingestion")
            )
            wf_id = decision.workflow_id or f"{self.name}-{uuid4()}"
            handle = await client.start_workflow(
                decision.workflow_type,
                decision.payload,
                id=wf_id,
                task_queue=task_queue,
            )
            self.logger.info(
                "Started workflow %s[%s]: %s",
                decision.workflow_type, handle.id, decision.rationale,
            )
            return {"action": "started", "workflow_id": handle.id,
                    "workflow_type": decision.workflow_type}

        elif decision.action == "signal_workflow":
            await client.get_workflow_handle(decision.workflow_id).signal(
                decision.signal_name, decision.payload
            )
            self.logger.info(
                "Signaled workflow %s[%s]: %s",
                decision.workflow_id, decision.signal_name, decision.rationale,
            )
            return {"action": "signaled", "workflow_id": decision.workflow_id,
                    "signal": decision.signal_name}

        elif decision.action == "alert":
            self.logger.warning(
                "ALERT from %s (confidence=%.0f%%): %s — payload=%s",
                self.name, decision.confidence * 100, decision.rationale, decision.payload,
            )
            await self._send_alert(decision)
            return {"action": "alert_sent", "rationale": decision.rationale}

        return {"action": "unknown", "decision_action": decision.action}

    async def run_cycle(self) -> dict:
        """Single observe → decide → act cycle. Called by the agent scheduler."""
        self._cycle_count += 1
        cycle_id = f"{self.name}-cycle-{self._cycle_count}"
        self.logger.info("Starting cycle #%d", self._cycle_count)
        try:
            observations = await self.observe()
            decision     = await self.decide(observations)
            result       = await self.act(decision)
            self.logger.info("Cycle #%d complete: action=%s", self._cycle_count, decision.action)
            return {"cycle_id": cycle_id, "status": "SUCCESS", **result}
        except Exception as exc:
            self.logger.error("Cycle #%d ERROR: %s", self._cycle_count, exc, exc_info=True)
            return {"cycle_id": cycle_id, "status": "ERROR", "error": str(exc)}

    def _human_approval_required(self) -> bool:
        return self.config.get(
            "require_human_approval",
            os.getenv("AGENT_REQUIRE_HUMAN_APPROVAL", "true").lower() == "true",
        )

    async def _audit_log(self, decision: AgentDecision) -> None:
        """Log decision to audit table. Non-blocking — failures are swallowed."""
        try:
            from packages.infrastructure.structured_logger import log_agent_decision  # type: ignore
            await log_agent_decision(
                agent=self.name,
                action=decision.action,
                rationale=decision.rationale,
                confidence=decision.confidence,
                payload=decision.payload,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            self.logger.warning("Audit log failed (non-fatal): %s", exc)

    async def _persist_approval_request(self, decision: AgentDecision) -> None:
        """Persist a pending decision to the human approval queue in the DB."""
        try:
            from packages.infrastructure.db_connector import named_query  # type: ignore
            named_query("insert_approval_request", {
                "agent": self.name,
                "action": decision.action,
                "workflow_type": decision.workflow_type,
                "payload": decision.payload,
                "rationale": decision.rationale,
                "confidence": decision.confidence,
            })
        except Exception as exc:
            self.logger.error("Failed to persist approval request: %s", exc)

    async def _send_alert(self, decision: AgentDecision) -> None:
        """Dispatch an alert via configured channels (Sentry, Slack, email)."""
        try:
            import sentry_sdk
            sentry_sdk.capture_message(
                f"[DataExtraction Agent Alert] {self.name}: {decision.rationale}",
                level="warning" if decision.confidence < 0.95 else "error",
                extras=decision.payload,
            )
        except Exception:
            pass  # Sentry not configured — alert logged above
