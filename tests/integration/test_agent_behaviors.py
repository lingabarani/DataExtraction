"""
DataExtraction — Agent Behavior Test Suite
==========================================
Verifies autonomous behavior, decision matrices, observe/decide/act cycles,
and human-approval barriers for all DataExtraction agents.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# Path bootstrapping
_curr = Path(__file__).resolve().parent
_root = _curr.parent.parent
for _p in [
    _root / "packages",
    _root / "packages" / "agents",
    _root / "packages" / "infrastructure",
    _root / "packages" / "pipeline",
    _root / "packages" / "temporal",
    _root,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from packages.agents.base_agent import BaseAgent, AgentDecision
from packages.agents.quality_agents.data_quality_agent import DataQualityAgent
from packages.agents.orchestration_agents.pipeline_coordinator import PipelineCoordinatorAgent
from packages.agents.orchestration_agents.resource_manager_agent import ResourceManagerAgent
from packages.agents.extraction_agents.federal_extraction_agent import FederalExtractionAgent


class TestAgentBehaviors(unittest.IsolatedAsyncioTestCase):
    """Verifies that agents follow the observe -> decide -> act contract with zero side-effects on DB."""

    async def test_data_quality_agent_empty_dlq_noop(self):
        agent = DataQualityAgent(config={"dlq_auto_threshold": 100})
        with patch.object(agent, "observe", return_value={"dlq_pending": 0, "oldest_age_hours": 0.0}):
            decision = await agent.decide({"dlq_pending": 0, "oldest_age_hours": 0.0})
            self.assertEqual(decision.action, "noop")
            self.assertIn("empty", decision.rationale.lower())

    async def test_data_quality_agent_auto_replay(self):
        agent = DataQualityAgent(config={"dlq_auto_threshold": 100})
        decision = await agent.decide({"dlq_pending": 45, "oldest_age_hours": 2.5})
        self.assertEqual(decision.action, "start_workflow")
        self.assertEqual(decision.workflow_type, "DLQReplayWorkflow")
        self.assertEqual(decision.payload.get("limit"), 45)
        self.assertFalse(decision.requires_human_approval)

    async def test_data_quality_agent_escalate_large_dlq(self):
        agent = DataQualityAgent(config={"dlq_auto_threshold": 100})
        decision = await agent.decide({"dlq_pending": 500, "oldest_age_hours": 24.0})
        self.assertEqual(decision.action, "alert")
        self.assertTrue(decision.requires_human_approval)
        self.assertIn("exceeds", decision.rationale.lower())

    async def test_pipeline_coordinator_triggers_enrichment(self):
        agent = PipelineCoordinatorAgent(config={})
        obs = {
            "completed_federal_ids": ["federal-run-123"],
            "completed_gmaps_ids": [],
            "active_enrichment_count": 0,
        }
        decision = await agent.decide(obs)
        self.assertEqual(decision.action, "start_workflow")
        self.assertEqual(decision.workflow_type, "LeadEnrichmentWorkflow")
        self.assertEqual(decision.payload.get("trigger_source"), "federal-run-123")

    async def test_pipeline_coordinator_noop_when_active(self):
        agent = PipelineCoordinatorAgent(config={})
        obs = {
            "completed_federal_ids": ["federal-run-123"],
            "completed_gmaps_ids": [],
            "active_enrichment_count": 1,
        }
        decision = await agent.decide(obs)
        self.assertEqual(decision.action, "noop")
        self.assertIn("already active", decision.rationale.lower())

    async def test_pipeline_coordinator_dedupes_completed_runs(self):
        agent = PipelineCoordinatorAgent(config={})
        agent._processed_runs.add("federal-run-123")
        obs = {
            "completed_federal_ids": ["federal-run-123"],
            "completed_gmaps_ids": [],
            "active_enrichment_count": 0,
        }
        decision = await agent.decide(obs)
        self.assertEqual(decision.action, "noop")

    async def test_resource_manager_nominal_noop(self):
        agent = ResourceManagerAgent(config={"db_pool_throttle_threshold": 0.85})
        obs = {
            "metrics": {"db_pool_utilization": 0.35},
            "active_gmaps": [],
            "active_federal": [],
        }
        decision = await agent.decide(obs)
        self.assertEqual(decision.action, "noop")
        self.assertIn("nominal", decision.rationale.lower())

    async def test_resource_manager_throttles_gmaps_on_high_pool(self):
        agent = ResourceManagerAgent(config={"db_pool_throttle_threshold": 0.85, "db_pool_critical_threshold": 0.95})
        obs = {
            "metrics": {"db_pool_utilization": 0.88},
            "active_gmaps": ["gmaps-weekly-run-1"],
            "active_federal": [],
        }
        decision = await agent.decide(obs)
        self.assertEqual(decision.action, "signal_workflow")
        self.assertEqual(decision.workflow_id, "gmaps-weekly-run-1")
        self.assertEqual(decision.signal_name, "throttle")

    async def test_resource_manager_pauses_on_critical_pool(self):
        agent = ResourceManagerAgent(config={"db_pool_throttle_threshold": 0.85, "db_pool_critical_threshold": 0.95})
        obs = {
            "metrics": {"db_pool_utilization": 0.97},
            "active_gmaps": ["gmaps-weekly-run-1"],
            "active_federal": ["federal-run-1"],
        }
        decision = await agent.decide(obs)
        self.assertEqual(decision.action, "signal_workflow")
        self.assertEqual(decision.signal_name, "pause")
        self.assertIn("critical", decision.rationale.lower())

    async def test_federal_extraction_agent_fresh_sources_noop(self):
        agent = FederalExtractionAgent(config={"max_staleness_days": 7})
        obs = {
            "freshness": {
                "cms_npi": {"last_seen": "2026-10-25T00:00:00+00:00", "record_count": 1000}
            },
            "has_active_federal_ingestion": False,
        }
        decision = await agent.decide(obs)
        self.assertEqual(decision.action, "noop")

    async def test_federal_extraction_agent_stale_source_triggers_ingestion(self):
        agent = FederalExtractionAgent(config={"max_staleness_days": 7})
        obs = {
            "freshness": {
                "cms_npi": {"last_seen": "2026-09-01T00:00:00+00:00", "record_count": 1000}
            },
            "has_active_federal_ingestion": False,
        }
        decision = await agent.decide(obs)
        self.assertEqual(decision.action, "start_workflow")
        self.assertEqual(decision.workflow_type, "FederalIngestionWorkflow")
        self.assertIn("cms_npi", decision.payload.get("stale_sources", []))

    async def test_base_agent_human_approval_blocks_act(self):
        agent = DataQualityAgent(config={"require_human_approval": True})
        decision = AgentDecision(
            action="start_workflow",
            workflow_type="DLQReplayWorkflow",
            rationale="Test approval",
            requires_human_approval=True
        )
        with patch.object(agent, "_audit_log", new_callable=AsyncMock), \
             patch.object(agent, "_persist_approval_request", new_callable=AsyncMock):
            result = await agent.act(decision)
            self.assertEqual(result.get("action"), "pending_approval")


if __name__ == "__main__":
    unittest.main()

