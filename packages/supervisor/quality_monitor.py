"""
DataExtraction — Platform SRE QualityMonitor
===========================================
Monitors Dead Letter Queue volumes and Knowledge Graph anomaly rates.
Automatically triggers replay for small backlogs.
Escalates large backlogs via alerts and human approval gating.
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

from packages.supervisor.base_supervisor import BaseSupervisor, AgentDecision
from packages.supervisor.tools.db_tool import get_dlq_stats

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "agents.yaml"
logger = logging.getLogger("dataextraction.supervisor.quality_monitor")


class QualityMonitor(BaseSupervisor):
    """
    Monitors Dead Letter Queue health and data anomalies.

    Decision policy:
    - DLQ == 0               -> NOOP
    - 0 < DLQ < auto_thresh  -> Start DLQ replay
    - DLQ >= alert_thresh    -> Alert + requires_human_approval
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if config is None:
            config = self._load_config()
        super().__init__(name="quality-monitor", config=config)
        self.auto_threshold = int(self.config.get("dlq_auto_threshold", 100))
        self.alert_threshold = int(self.config.get("dlq_alert_threshold", 1000))

    @staticmethod
    def _load_config() -> dict:
        try:
            if CONFIG_PATH.exists():
                data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
                return data.get("agents", {}).get("data_quality", {})
        except Exception as exc:
            logger.debug("Config load notice: %s", exc)
        return {}

    async def observe(self) -> Dict[str, Any]:
        """
        Fetches DLQ stats via the supervisor database inspection tool.
        """
        stats = await get_dlq_stats()
        return {
            "dlq_pending": stats.get("dlq_pending", 0),
            "oldest_age_hours": stats.get("oldest_age_hours", 0.0),
            "by_source": stats.get("by_source", {}),
            "total_replayed": stats.get("total_replayed", 0),
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Evaluates DLQ backpressure and selects appropriate operational action.
        """
        pending = int(observations.get("dlq_pending", 0))
        age_hours = float(observations.get("oldest_age_hours", 0.0))

        if pending == 0:
            return AgentDecision(
                action="noop",
                rationale="Dead Letter Queue is empty — zero processing defects",
                confidence=1.0,
            )

        if pending < self.auto_threshold:
            from packages.infrastructure.config_manager import config_manager
            return AgentDecision(
                action="start_workflow",
                workflow_type="DLQReplayWorkflow",
                workflow_task_queue=config_manager.QUEUE_SEARCH,
                payload={"batch_size": pending, "limit": pending, "dry_run": False},
                rationale=f"Auto-replaying {pending} DLQ records (below threshold {self.auto_threshold})",
                confidence=0.95,
                requires_human_approval=False,
            )

        # DLQ exceeds threshold — requires human operator intervention
        return AgentDecision(
            action="alert",
            payload=observations,
            rationale=(
                f"DLQ pending count ({pending}) exceeds auto-replay threshold "
                f"({self.auto_threshold}). Oldest record age: {age_hours:.1f}h"
            ),
            confidence=1.0,
            requires_human_approval=True,
        )


# Backward-compatibility alias
DataQualityAgent = QualityMonitor

__all__ = [
    "QualityMonitor",
    "DataQualityAgent",
]

