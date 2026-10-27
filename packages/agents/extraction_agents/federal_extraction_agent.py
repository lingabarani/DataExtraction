"""
DataExtraction — FederalExtractionAgent
=======================================
Monitors federal source freshness, source status, and API health.
Triggers daily or emergency incremental ingestion runs when sources become stale
or when new quarterly data batches are published.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from packages.agents.base_agent import BaseAgent, AgentDecision
from packages.agents.tools.db_tool import get_source_freshness
from packages.agents.tools.temporal_tool import list_active_workflows

logger = logging.getLogger("dataextraction.agents.federal_extraction")


class FederalExtractionAgent(BaseAgent):
    """
    Supervises the 6 federal scraper datasets:
    CMS NPI, SEC EDGAR, FDIC, USAspending, ProPublica, SAM.gov.
    """

    DEFAULT_MAX_STALENESS_DAYS = 7

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(name="federal-extraction-agent", config=config or {})
        self.max_staleness_days = self.config.get(
            "max_staleness_days", self.DEFAULT_MAX_STALENESS_DAYS
        )

    async def observe(self) -> Dict[str, Any]:
        """
        Observes source timestamps and checks for running federal workflows.
        """
        freshness = await get_source_freshness()
        active_federal = await list_active_workflows("FederalIngestionWorkflow")
        return {
            "freshness": freshness,
            "has_active_federal_ingestion": len(active_federal) > 0,
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Decides whether to trigger an incremental federal ingestion workflow.
        """
        if observations.get("has_active_federal_ingestion", False):
            return AgentDecision(
                action="noop",
                rationale="Federal ingestion workflow is currently active.",
                confidence=1.0,
            )

        freshness = observations.get("freshness", {})
        stale_sources = []
        now = datetime.now(timezone.utc)

        for source_name, info in freshness.items():
            last_seen_str = info.get("last_seen")
            if last_seen_str:
                try:
                    last_seen = datetime.fromisoformat(last_seen_str)
                    if last_seen.tzinfo is None:
                        last_seen = last_seen.replace(tzinfo=timezone.utc)
                    if (now - last_seen).days >= self.max_staleness_days:
                        stale_sources.append(source_name)
                except Exception:
                    pass

        if stale_sources:
            return AgentDecision(
                action="start_workflow",
                workflow_type="FederalIngestionWorkflow",
                workflow_task_queue="federal-ingestion",
                payload={"mode": "incremental", "stale_sources": stale_sources},
                rationale=f"Stale federal sources detected ({', '.join(stale_sources)}) exceeding {self.max_staleness_days} days",
                confidence=0.90,
                requires_human_approval=self.config.get("require_human_approval", False),
            )

        return AgentDecision(
            action="noop",
            rationale="All monitored federal sources are within acceptable freshness limits.",
            confidence=1.0,
        )

