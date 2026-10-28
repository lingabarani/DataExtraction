"""
DataExtraction — Phase 9 Unit & Integration Tests: 6-Agent Orchestration Fleet
=============================================================================
Verifies:
1. Standardized 6-Agent Task Queue configurations in ConfigManager.
2. Agent 1: Official Registry Ingestion Workflow (Agent1RegistryWorkflow).
3. Agent 2: Geospatial & Domain Discovery Workflow (Agent2GeospatialWorkflow).
4. Agent 3: Identity Resolution & Clustering Workflow (Agent3IdentityWorkflow).
5. Agent 4: Executive Discovery & Contact Intelligence Workflow (Agent4ExecutiveWorkflow).
6. Agent 5: Governance, Quality & Confidence Engine Workflow (Agent5GovernanceWorkflow).
7. Agent 6: Persistence, CDC & Search Synchronization Workflow (Agent6SearchSyncWorkflow).
8. MasterOrchestrationWorkflow 6-Agent end-to-end saga execution.
"""

import asyncio
from datetime import timedelta
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure"), str(REPO_ROOT / "packages" / "temporal")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.config_manager import config_manager
from packages.temporal.workflows.w1_registry_workflow import Agent1RegistryWorkflow
from packages.temporal.workflows.w2_geospatial_workflow import Agent2GeospatialWorkflow
from packages.temporal.workflows.w3_identity_workflow import Agent3IdentityWorkflow
from packages.temporal.workflows.w4_executive_workflow import Agent4ExecutiveWorkflow
from packages.temporal.workflows.w5_governance_workflow import Agent5GovernanceWorkflow
from packages.temporal.workflows.w6_search_sync_workflow import Agent6SearchSyncWorkflow
from packages.temporal.workflows.master_orchestration_workflow import MasterOrchestrationWorkflow


class TestEnterpriseOrchestrationFleet(unittest.IsolatedAsyncioTestCase):
    """Test suite for the 6 autonomous orchestration agents and task queues."""

    def test_01_standardized_task_queues(self):
        """Verifies all 6 Agent task queues are properly registered in ConfigManager."""
        queues = config_manager.get_temporal_queues()
        self.assertEqual(queues["agent_1_registry"], "registry-ingestion-queue")
        self.assertEqual(queues["agent_2_geospatial"], "geospatial-domain-queue")
        self.assertEqual(queues["agent_3_identity"], "identity-clustering-queue")
        self.assertEqual(queues["agent_4_executive"], "executive-contact-queue")
        self.assertEqual(queues["agent_5_governance"], "governance-quality-queue")
        self.assertEqual(queues["agent_6_search"], "search-persistence-queue")

    async def test_02_agent1_registry_workflow_signals_and_run(self):
        """Verifies Agent 1 handles pause, resume, cancel_source signals and execution."""
        wf = Agent1RegistryWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value={"source": "CMS_NPI", "exit_code": 0})):

            mock_info.return_value.workflow_id = "test-agent1-wf-001"
            st = wf.get_status()
            self.assertEqual(st["status"], "INITIALIZED")
            self.assertFalse(st["paused"])

            wf.pause()
            self.assertTrue(wf._paused)
            wf.resume()
            self.assertFalse(wf._paused)

            wf.cancel_source("sec_edgar")
            self.assertIn("sec_edgar", wf._cancelled_sources)

            res = await wf.run({"sources": ["cms_npi", "sec_edgar"]})
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["results"]["sec_edgar"]["status"], "SKIPPED")
            self.assertEqual(res["results"]["cms_npi"]["status"], "SUCCESS")

    async def test_03_agent2_geospatial_workflow_signals_and_run(self):
        """Verifies Agent 2 handles spatial region signals and parallel execution."""
        wf = Agent2GeospatialWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value={"status": "SUCCESS", "collected": 42})):

            mock_info.return_value.workflow_id = "test-agent2-wf-001"
            wf.pause()
            self.assertTrue(wf._paused)
            wf.resume()
            self.assertFalse(wf._paused)

            wf.cancel_region("US-NY")
            self.assertIn("US-NY", wf._cancelled_regions)

            res = await wf.run({
                "regions": ["US-CA", "US-NY"],
                "states": ["CA"],
                "target_table": "companies",
            })
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["regions_processed"], 1)  # US-NY was cancelled
            self.assertIn("gmaps", res["results"])
            self.assertIn("osm", res["results"])
            self.assertIn("geo_validation", res["results"])

    async def test_04_agent3_identity_workflow_unmerge_and_clustering(self):
        """Verifies Agent 3 handles deduplication, clustering, and dynamic unmerges."""
        wf = Agent3IdentityWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value={"status": "SUCCESS", "merged": 5})):

            mock_info.return_value.workflow_id = "test-agent3-wf-001"
            # Signal operator dispute unmerge
            wf.unmerge_member({"member_id": "mem_001", "reason": "False positive match"})
            st = wf.get_status()
            self.assertEqual(st["pending_unmerges"], 1)

            res = await wf.run({
                "source": "REGISTRY_MERGED",
                "target_table": "companies",
                "cluster_records": [{"canonical_id": "c1", "source_name": "SEC"}],
            })
            self.assertEqual(res["status"], "COMPLETED")
            self.assertIn("normalization", res["results"])
            self.assertIn("tax_validation", res["results"])
            self.assertIn("deduplication", res["results"])
            self.assertIn("cluster_membership", res["results"])
            self.assertIn("unmerges_executed", res["results"])

    async def test_05_agent4_executive_workflow_contacts_and_hierarchy(self):
        """Verifies Agent 4 handles 5-tier contact validation and graph entities."""
        wf = Agent4ExecutiveWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value={"status": "SUCCESS", "validated": 100})):

            mock_info.return_value.workflow_id = "test-agent4-wf-001"
            res = await wf.run({
                "source_table": "companies",
                "target_table": "us_leads",
                "persons": [{"full_name": "Jane Doe", "primary_email": "jane@example.com"}],
                "employments": [{"person_id": "p1", "org_id": "o1", "job_title": "CEO"}],
                "hierarchies": [{"parent_org_id": "p_org", "child_org_id": "c_org"}],
                "technologies": [{"org_id": "o1", "tech_name": "Kubernetes"}],
            })
            self.assertEqual(res["status"], "COMPLETED")
            self.assertIn("contact_validation", res["results"])
            self.assertIn("build_leads", res["results"])
            self.assertIn("persons", res["results"])
            self.assertIn("employments", res["results"])
            self.assertIn("hierarchies", res["results"])
            self.assertIn("technologies", res["results"])

    async def test_06_agent5_governance_workflow_quality_and_dlq(self):
        """Verifies Agent 5 computes Bayesian quality scores and audits DLQ."""
        wf = Agent5GovernanceWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value={"total": 0, "quality_score": 92.5})):

            mock_info.return_value.workflow_id = "test-agent5-wf-001"
            wf.replay_dlq()
            self.assertTrue(wf._replay_dlq_requested)

            res = await wf.run({
                "quality_evaluations": [{
                    "entity_type": "organization",
                    "entity_data": {"tax_id": "12-3456789"},
                    "contributing_sources": ["SEC_EDGAR"],
                }],
                "auto_resolve_dlq": True,
            })
            self.assertEqual(res["status"], "COMPLETED")
            self.assertIn("dlq_stats", res["results"])
            self.assertIn("quality_scores", res["results"])

    async def test_07_agent6_search_sync_workflow_partitions_and_cdc(self):
        """Verifies Agent 6 maintains partitions and syncs CDC to OpenSearch."""
        wf = Agent6SearchSyncWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value={"status": "SUCCESS", "synced_records": 250})):

            mock_info.return_value.workflow_id = "test-agent6-wf-001"
            wf.force_sync()
            self.assertTrue(wf._force_sync_requested)

            res = await wf.run({
                "run_partitions": True,
                "run_search_sync": True,
                "sync_batch_limit": 500,
            })
            self.assertEqual(res["status"], "COMPLETED")
            self.assertIn("partitions", res["results"])
            self.assertIn("opensearch_sync", res["results"])

    async def test_08_master_orchestrator_6agent_saga(self):
        """Verifies MasterOrchestrationWorkflow coordinates all 6 agents cleanly in sequence."""
        wf = MasterOrchestrationWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_child_workflow", new=AsyncMock(return_value={"status": "SUCCESS"})):

            mock_info.return_value.workflow_id = "test-master-6agent-wf"

            config = {
                "agent_1": {"sources": ["cms_npi"]},
                "agent_2": {"regions": ["US-CA"]},
                "agent_3": {"target_table": "companies"},
                "agent_4": {"source_table": "companies"},
                "agent_5": {"run_governance": True},
                "agent_6": {"run_search_sync": True},
            }

            res = await wf.run(config)
            self.assertEqual(res["status"], "COMPLETED")
            self.assertIn("federal", res["results"])
            self.assertIn("gmaps", res["results"])
            self.assertIn("deduplication", res["results"])
            self.assertIn("enrichment", res["results"])
            self.assertIn("governance", res["results"])
            self.assertIn("search_sync", res["results"])


if __name__ == "__main__":
    unittest.main()
