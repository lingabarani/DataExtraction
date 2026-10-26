"""
DataExtraction — PipelineCoordinatorAgent
==========================================
Monitors workflow completion events and automatically triggers downstream
enrichment and deduplication pipelines when upstream extractions finish.
"""

import logging
from typing import Dict, Any, List
from packages.agents.base_agent import BaseAgent, AgentDecision
from packages.agents.tools.temporal_tool import list_completed_workflows, list_active_workflows

logger = logging.getLogger("dataextraction.agents.pipeline_coordinator")


class PipelineCoordinatorAgent(BaseAgent):
    """
    Orchestrates automated chaining between extraction workflows and downstream processing.
    Ensures that when a federal or regional extraction completes, the LeadEnrichmentWorkflow
    or deduplication phase is queued safely without duplicate executions.
    """

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(name="pipeline-coordinator", config=config or {})
        self._processed_runs: set = set()

    async def observe(self) -> Dict[str, Any]:
        """
        Observes completed workflows and currently active workflows.
        """
        completed_federal = await list_completed_workflows("FederalIngestionWorkflow", limit=20)
        completed_gmaps = await list_completed_workflows("GMapsExtractionWorkflow", limit=20)
        active_enrichment = await list_active_workflows("LeadEnrichmentWorkflow")

        return {
            "completed_federal_ids": [wf["id"] for wf in completed_federal],
            "completed_gmaps_ids": [wf["id"] for wf in completed_gmaps],
            "active_enrichment_count": len(active_enrichment),
        }

    async def decide(self, observations: Dict[str, Any]) -> AgentDecision:
        """
        Determines if any newly completed extraction workflow needs downstream enrichment.
        """
        active_count = observations.get("active_enrichment_count", 0)
        if active_count > 0:
            return AgentDecision(
                action="noop",
                rationale=f"Downstream enrichment already active ({active_count} running).",
                confidence=1.0,
            )

        # Check for untriggered federal extractions
        completed_federal = observations.get("completed_federal_ids", [])
        for wf_id in completed_federal:
            if wf_id not in self._processed_runs:
                self._processed_runs.add(wf_id)
                return AgentDecision(
                    action="start_workflow",
                    workflow_type="LeadEnrichmentWorkflow",
                    workflow_task_queue="data-pipeline",
                    payload={"trigger_source": wf_id, "mode": "incremental"},
                    rationale=f"Triggering lead enrichment for completed federal run: {wf_id}",
                    confidence=0.95,
                    requires_human_approval=self.config.get("require_human_approval", False),
                )

        # Check for untriggered gmaps extractions
        completed_gmaps = observations.get("completed_gmaps_ids", [])
        for wf_id in completed_gmaps:
            if wf_id not in self._processed_runs:
                self._processed_runs.add(wf_id)
                return AgentDecision(
                    action="start_workflow",
                    workflow_type="LeadEnrichmentWorkflow",
                    workflow_task_queue="data-pipeline",
                    payload={"trigger_source": wf_id, "mode": "gmaps_enrichment"},
                    rationale=f"Triggering lead enrichment for completed gmaps run: {wf_id}",
                    confidence=0.95,
                    requires_human_approval=self.config.get("require_human_approval", False),
                )

        return AgentDecision(
            action="noop",
            rationale="All completed extraction runs have been enriched or already queued.",
            confidence=1.0,
        )
