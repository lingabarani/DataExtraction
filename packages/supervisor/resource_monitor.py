"""
DataExtraction — Platform SRE ResourceMonitor
=============================================
Supervises database connection pool utilization, system health, and external API
pressure. Issues throttling signals or pauses to running workflows if resource
boundaries are approached.
"""

import logging
from typing import Dict, Any, Optional

from packages.supervisor.base_supervisor import BaseSupervisor, AgentDecision
from packages.supervisor.tools.metrics_tool import get_current_metrics
from packages.supervisor.tools.temporal_tool import list_active_workflows

logger = logging.getLogger("dataextraction.supervisor.resource_monitor")


class ResourceMonitor(BaseSupervisor):
    """
    Autonomous SRE supervisor for platform resource allocation.
    Protects PostgreSQL from connection starvation and external APIs from HTTP 429 rate limits.
    """

    DB_POOL_THROTTLE_THRESHOLD = 0.85  # 85% utilization triggers throttling
    DB_POOL_CRITICAL_THRESHOLD = 0.95  # 95% utilization triggers pause

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(name="resource-monitor", config=config or {})
        self.throttle_threshold = float(self.config.get(
            "db_pool_throttle_threshold", self.DB_POOL_THROTTLE_THRESHOLD
        ))
        self.critical_threshold = float(self.config.get(
            "db_pool_critical_threshold", self.DB_POOL_CRITICAL_THRESHOLD
        ))

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
        active_gmaps = await list_active_workflows("Agent2GeospatialWorkflow")
        active_registry = await list_active_workflows("Agent1RegistryWorkflow")

        return {
            "metrics": metrics,
            "active_workflows": {
                "geospatial": active_gmaps,
                "registry": active_registry,
                "total_active": len(active_gmaps) + len(active_registry)
            }
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Decision matrix:
          - Utilization >= 0.95 -> Pause active workflows (CRITICAL)
          - Utilization >= 0.85 -> Signal throttle / reduce rate (WARNING)
          - Otherwise -> NOOP
        """
        metrics = observations.get("metrics", {})
        utilization = float(metrics.get("db_pool_utilization") or 0.0)
        active_wfs = observations.get("active_workflows", {})
        gmaps_candidates = observations.get("active_gmaps") or active_wfs.get("geospatial", [])

        if utilization >= self.critical_threshold:
            # Emergency circuit breaker: pause active extraction workflows
            for wf in gmaps_candidates:
                wf_id = wf if isinstance(wf, str) else wf.get("id")
                return AgentDecision(
                    action="signal_workflow",
                    workflow_id=wf_id,
                    signal_name="pause",
                    payload={"reason": f"DB pool critical utilization: {utilization * 100:.1f}%"},
                    rationale=f"Paused {wf_id} — Critical DB pool at {utilization * 100:.1f}% capacity",
                    confidence=1.0,
                    requires_human_approval=False,
                )

            return AgentDecision(
                action="alert",
                payload={"utilization": utilization, "metrics": metrics},
                rationale=f"PostgreSQL connection pool at critical saturation: {utilization * 100:.1f}%",
                confidence=1.0,
                requires_human_approval=True,
            )

        elif utilization >= self.throttle_threshold:
            # High utilization warning: throttle active extraction workflows
            for wf in gmaps_candidates:
                wf_id = wf if isinstance(wf, str) else wf.get("id")
                return AgentDecision(
                    action="signal_workflow",
                    workflow_id=wf_id,
                    signal_name="throttle",
                    payload={"reason": f"DB pool high utilization: {utilization * 100:.1f}%"},
                    rationale=f"Throttled {wf_id} — DB pool at {utilization * 100:.1f}% capacity",
                    confidence=0.90,
                    requires_human_approval=False,
                )

            return AgentDecision(
                action="alert",
                payload={"utilization": utilization, "metrics": metrics},
                rationale=f"PostgreSQL pool high: {utilization * 100:.1f}% — recommend backpressure",
                confidence=0.85,
                requires_human_approval=False,
            )

        return AgentDecision(
            action="noop",
            rationale=f"Resource levels nominal (DB pool at {utilization * 100:.1f}%)",
            confidence=1.0,
        )


# Backward-compatibility alias
ResourceManagerAgent = ResourceMonitor

__all__ = [
    "ResourceMonitor",
    "ResourceManagerAgent",
]

