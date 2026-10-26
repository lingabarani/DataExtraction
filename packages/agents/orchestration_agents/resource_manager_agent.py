"""
DataExtraction — ResourceManagerAgent
=====================================
Monitors database connection pool utilization, system health, and API rate limits.
Issues throttling signals or pauses to running workflows if resource boundaries
are approached.
"""

import logging
from typing import Dict, Any
from packages.agents.base_agent import BaseAgent, AgentDecision
from packages.agents.tools.metrics_tool import get_current_metrics
from packages.agents.tools.temporal_tool import list_active_workflows

logger = logging.getLogger("dataextraction.agents.resource_manager")


class ResourceManagerAgent(BaseAgent):
    """
    Autonomous supervisor for platform resource allocation.
    Protects PostgreSQL from connection starvation and external APIs from HTTP 429 penalties.
    """

    DB_POOL_THROTTLE_THRESHOLD = 0.85  # 85% utilization triggers throttling
    DB_POOL_CRITICAL_THRESHOLD = 0.95  # 95% utilization triggers pause

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(name="resource-manager", config=config or {})
        self.throttle_threshold = self.config.get(
            "db_pool_throttle_threshold", self.DB_POOL_THROTTLE_THRESHOLD
        )
        self.critical_threshold = self.config.get(
            "db_pool_critical_threshold", self.DB_POOL_CRITICAL_THRESHOLD
        )

    async def observe(self) -> Dict[str, Any]:
        """
        Reads connection pool utilization and active extraction workflows.
        """
        metrics = await get_current_metrics([
            "db_pool_utilization",
            "db_pool_active",
            "db_pool_capacity",
            "api_request_rate"
        ])
        active_gmaps = await list_active_workflows("GMapsExtractionWorkflow")
        active_federal = await list_active_workflows("FederalIngestionWorkflow")

        return {
            "metrics": metrics,
            "active_gmaps": [wf["id"] for wf in active_gmaps],
            "active_federal": [wf["id"] for wf in active_federal],
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Analyzes resource stress and decides whether to throttle or pause active workflows.
        """
        metrics = observations.get("metrics", {})
        pool_util = metrics.get("db_pool_utilization", 0.0)
        active_gmaps = observations.get("active_gmaps", [])
        active_federal = observations.get("active_federal", [])

        # Critical threshold reached (>95%)
        if pool_util >= self.critical_threshold:
            target_wf = active_gmaps[0] if active_gmaps else (active_federal[0] if active_federal else "")
            if target_wf:
                return AgentDecision(
                    action="signal_workflow",
                    workflow_id=target_wf,
                    signal_name="pause",
                    payload={"reason": f"CRITICAL: DB pool utilization at {pool_util:.1%}"},
                    rationale=f"DB pool critical ({pool_util:.1%}) — pausing extraction workflow {target_wf}",
                    confidence=0.99,
                    requires_human_approval=self.config.get("require_human_approval", False),
                )
            return AgentDecision(
                action="alert",
                payload={"severity": "CRITICAL", "pool_utilization": pool_util},
                rationale=f"DB connection pool at critical capacity ({pool_util:.1%}) with no active workflows to throttle",
                confidence=1.0,
            )

        # Warning/throttle threshold reached (>85%)
        if pool_util >= self.throttle_threshold:
            if active_gmaps:
                return AgentDecision(
                    action="signal_workflow",
                    workflow_id=active_gmaps[0],
                    signal_name="throttle",
                    payload={"concurrency": 2, "rate_limit_delay_sec": 2.0},
                    rationale=f"DB pool elevated ({pool_util:.1%}) — throttling gmaps workflow {active_gmaps[0]}",
                    confidence=0.88,
                )

        return AgentDecision(
            action="noop",
            rationale=f"Resource metrics nominal: DB pool utilization {pool_util:.1%}",
            confidence=1.0,
        )
