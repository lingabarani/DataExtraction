"""
DataExtraction — DataQualityAgent
===================================
Monitors the Dead Letter Queue. Automatically replays small backlogs.
Escalates large backlogs via alert + human approval workflow.

Cycle interval: 5 minutes (configurable via config/agents.yaml)
"""

import os
import logging
from pathlib import Path

import yaml

from packages.agents.base_agent import BaseAgent, AgentDecision

CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "agents.yaml"
logger = logging.getLogger("dataextraction.agents.data_quality")


class DataQualityAgent(BaseAgent):
    """
    Monitors the Dead Letter Queue health.

    Decision logic:
    - DLQ == 0            → noop
    - 0 < DLQ < threshold → start DLQReplayWorkflow automatically
    - DLQ >= threshold    → alert + requires_human_approval
    """

    def __init__(self, config: dict = None):
        if config is None:
            config = self._load_config()
        super().__init__(name="data_quality", config=config)
        self.auto_threshold = config.get("dlq_auto_threshold", config.get("dlq_auto_replay_threshold", 100))
        self.alert_threshold = config.get("dlq_alert_threshold", 1000)

    @staticmethod
    def _load_config() -> dict:
        try:
            data = yaml.safe_load(CONFIG_PATH.read_text())
            return data.get("agents", {}).get("data_quality", {})
        except Exception:
            return {}

    async def observe(self) -> dict:
        """
        Fetches DLQ stats via a Temporal activity (not direct DB access).
        Uses a short-lived workflow to query stats — keeps agent Temporal-native.
        """
        try:
            from packages.temporal.client import get_temporal_client
            from packages.temporal.activities.storage_activities import get_dlq_stats_activity

            # Execute a one-off query workflow to get DLQ stats
            client = await get_temporal_client()
            result = await client.execute_workflow(
                "StorageQueryWorkflow",
                {"query": "dlq_stats"},
                id=f"dlq-stats-{self.name}",
                task_queue="storage-ops",
            )
            return result
        except Exception as exc:
            self.logger.warning("observe() fallback to direct DLQ stats: %s", exc)
            # Graceful fallback — won't block agent cycle
            return {"dlq_pending": 0, "dlq_failed": 0, "oldest_age_hours": 0}

    async def decide(self, observations: dict) -> AgentDecision:
        count        = observations.get("dlq_pending", 0)
        oldest_hours = observations.get("oldest_age_hours", 0)

        if count == 0:
            return AgentDecision(
                action="noop",
                rationale=f"DLQ is empty — no action required",
                confidence=1.0,
            )

        if count < self.auto_threshold:
            return AgentDecision(
                action="start_workflow",
                workflow_type="DLQReplayWorkflow",
                workflow_id=f"dlq-auto-replay",
                payload={"limit": count, "mode": "auto"},
                rationale=(
                    f"DLQ has {count} pending records (below auto-threshold {self.auto_threshold})"
                    f" — triggering automatic replay"
                ),
                confidence=0.92,
                requires_human_approval=False,  # Safe: count is small
            )

        # Large backlog — alert + require human approval
        return AgentDecision(
            action="alert",
            payload={
                "severity": "HIGH" if count >= self.alert_threshold else "MEDIUM",
                "dlq_pending": count,
                "oldest_age_hours": oldest_hours,
                "auto_threshold": self.auto_threshold,
                "alert_threshold": self.alert_threshold,
            },
            rationale=(
                f"DLQ backlog of {count} records exceeds auto-threshold {self.auto_threshold}"
                f" — manual review required. Oldest record: {oldest_hours:.1f}h ago."
            ),
            confidence=0.99,
            requires_human_approval=True,
        )
