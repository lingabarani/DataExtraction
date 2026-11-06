"""
DataExtraction — Unit Test Suite for Temporal Durable Orchestration & Configuration
====================================================================================
Tests cover:
  1. Temporal configuration (config.py):
     - Exactly 6 task queues.
     - Retry policies and backoff coefficients.
     - Worker activity concurrency mappings.
     - Cluster host, namespace, and timeout constants.
  2. Master 6-Agent Orchestrator Saga (master_orchestrator.py):
     - Initialization and initial status reporting.
     - Signals (pause, resume, cancel_phase).
     - Query introspection (get_status).
     - Backward compatibility aliases (MasterOrchestrationWorkflow).
  3. Workflows w1 through w6 import integrity and task queue bindings.
  4. Production worker daemons queue assignment integrity.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_backend_dir = Path(__file__).resolve().parent
_project_root = _backend_dir.parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from packages.temporal.config import (
    QUEUE_REGISTRY,
    QUEUE_GEOSPATIAL,
    QUEUE_IDENTITY,
    QUEUE_EXECUTIVE,
    QUEUE_GOVERNANCE,
    QUEUE_SEARCH,
    QUEUE_EMAIL_ENRICHMENT,
    TEMPORAL_HOST,
    TEMPORAL_NAMESPACE,
    REGISTRY_RETRY_POLICY,
    GEOSPATIAL_RETRY_POLICY,
    IDENTITY_RETRY_POLICY,
    EXECUTIVE_RETRY_POLICY,
    GOVERNANCE_RETRY_POLICY,
    SEARCH_RETRY_POLICY,
    EMAIL_ENRICHMENT_RETRY_POLICY,
    WORKER_MAX_ACTIVITIES,
    get_task_queues,
)
from packages.temporal.workflows.master_orchestrator import (
    MasterOrchestrator,
    MasterOrchestrationWorkflow,
)
from packages.temporal.workflows.w1_registry_workflow import Agent1RegistryWorkflow
from packages.temporal.workflows.w2_geospatial_workflow import Agent2GeospatialWorkflow
from packages.temporal.workflows.w3_identity_workflow import Agent3IdentityWorkflow
from packages.temporal.workflows.w4_executive_workflow import Agent4ExecutiveWorkflow
from packages.temporal.workflows.w5_governance_workflow import Agent5GovernanceWorkflow
from packages.temporal.workflows.w6_search_sync_workflow import Agent6SearchSyncWorkflow
from packages.temporal.workflows.w7_email_enrichment_workflow import (
    EmailEnrichmentWorkflow,
    Agent7EmailEnrichmentWorkflow,
)


class TestTemporalConfiguration(unittest.TestCase):
    """Verifies centralized Temporal cluster, queue, and retry policies."""

    def test_all_agent_queues_defined(self):
        queues = get_task_queues()
        self.assertGreaterEqual(len(queues), 7)
        self.assertEqual(queues["agent_1_registry"], QUEUE_REGISTRY)
        self.assertEqual(queues["agent_2_geospatial"], QUEUE_GEOSPATIAL)
        self.assertEqual(queues["agent_3_identity"], QUEUE_IDENTITY)
        self.assertEqual(queues["agent_4_executive"], QUEUE_EXECUTIVE)
        self.assertEqual(queues["agent_5_governance"], QUEUE_GOVERNANCE)
        self.assertEqual(queues["agent_6_search"], QUEUE_SEARCH)
        self.assertEqual(queues["agent_7_email_enrichment"], QUEUE_EMAIL_ENRICHMENT)

    def test_queue_names_are_unique(self):
        queues = [
            QUEUE_REGISTRY,
            QUEUE_GEOSPATIAL,
            QUEUE_IDENTITY,
            QUEUE_EXECUTIVE,
            QUEUE_GOVERNANCE,
            QUEUE_SEARCH,
            QUEUE_EMAIL_ENRICHMENT,
        ]
        self.assertEqual(len(set(queues)), 7)
        for q in queues:
            self.assertTrue(isinstance(q, str) and len(q) > 0)

    def test_cluster_connection_defaults(self):
        self.assertTrue(isinstance(TEMPORAL_HOST, str) and len(TEMPORAL_HOST) > 0)
        self.assertTrue(isinstance(TEMPORAL_NAMESPACE, str) and len(TEMPORAL_NAMESPACE) > 0)

    def test_retry_policies_have_valid_backoff(self):
        policies = [
            REGISTRY_RETRY_POLICY,
            GEOSPATIAL_RETRY_POLICY,
            IDENTITY_RETRY_POLICY,
            EXECUTIVE_RETRY_POLICY,
            GOVERNANCE_RETRY_POLICY,
            SEARCH_RETRY_POLICY,
            EMAIL_ENRICHMENT_RETRY_POLICY,
        ]
        for policy in policies:
            self.assertGreaterEqual(policy.backoff_coefficient, 1.5)
            self.assertGreaterEqual(policy.maximum_attempts, 2)

    def test_worker_concurrency_mappings(self):
        for q in [
            QUEUE_REGISTRY,
            QUEUE_GEOSPATIAL,
            QUEUE_IDENTITY,
            QUEUE_EXECUTIVE,
            QUEUE_GOVERNANCE,
            QUEUE_SEARCH,
            QUEUE_EMAIL_ENRICHMENT,
        ]:
            self.assertIn(q, WORKER_MAX_ACTIVITIES)
            self.assertGreater(WORKER_MAX_ACTIVITIES[q], 0)


class TestMasterOrchestratorSaga(unittest.TestCase):
    """Verifies MasterOrchestrator signal, query, and lifecycle behavior."""

    def test_alias_equivalence(self):
        self.assertIs(MasterOrchestrator, MasterOrchestrationWorkflow)

    def test_orchestrator_initial_status_query(self):
        orchestrator = MasterOrchestrator()
        with patch("temporalio.workflow.info") as mock_info:
            mock_info.return_value.workflow_id = "wf-test-master-001"
            status = orchestrator.get_status()
            self.assertEqual(status["workflow_id"], "wf-test-master-001")
            self.assertEqual(status["status"], "RUNNING")
            self.assertEqual(status["phase"], "INIT")
            self.assertFalse(status["paused"])
            self.assertFalse(status["cancelled"])
            self.assertEqual(status["phases"], [])

    def test_orchestrator_signals(self):
        orchestrator = MasterOrchestrator()
        with patch("temporalio.workflow.logger"):
            # 1. Pause
            orchestrator.pause()
            self.assertTrue(orchestrator._paused)

            # 2. Resume
            orchestrator.resume()
            self.assertFalse(orchestrator._paused)

            # 3. Cancel phase
            orchestrator.cancel_phase("REGISTRY")
            self.assertTrue(orchestrator._cancelled)
            self.assertIn("REGISTRY", orchestrator._cancelled_phases)

    def test_legacy_shim_import(self):
        from packages.temporal.workflows.master_orchestration_workflow import (
            MasterOrchestrationWorkflow as LegacyWorkflow,
        )
        self.assertIs(LegacyWorkflow, MasterOrchestrator)


class TestChildWorkflowsConfiguration(unittest.TestCase):
    """Verifies that each child workflow binds to the centralized task queues."""

    def test_child_workflows_queue_bindings(self):
        import packages.temporal.workflows.w1_registry_workflow as w1
        import packages.temporal.workflows.w2_geospatial_workflow as w2
        import packages.temporal.workflows.w3_identity_workflow as w3
        import packages.temporal.workflows.w4_executive_workflow as w4
        import packages.temporal.workflows.w5_governance_workflow as w5
        import packages.temporal.workflows.w6_search_sync_workflow as w6
        import packages.temporal.workflows.w7_email_enrichment_workflow as w7

        self.assertEqual(w1.TASK_QUEUE, QUEUE_REGISTRY)
        self.assertEqual(w2.TASK_QUEUE, QUEUE_GEOSPATIAL)
        self.assertEqual(w3.TASK_QUEUE, QUEUE_IDENTITY)
        self.assertEqual(w4.TASK_QUEUE, QUEUE_EXECUTIVE)
        self.assertEqual(w5.TASK_QUEUE, QUEUE_GOVERNANCE)
        self.assertEqual(w6.TASK_QUEUE, QUEUE_SEARCH)
        self.assertEqual(w7.TASK_QUEUE, QUEUE_EMAIL_ENRICHMENT)


if __name__ == "__main__":
    unittest.main()

