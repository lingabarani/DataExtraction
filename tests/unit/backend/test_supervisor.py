"""
DataExtraction — Unit Test Suite: Supervisor Subsystem
=====================================================
Validates:
  1. BaseSupervisor abstract contract, cycle execution, and audit logging.
  2. ResourceMonitor decision policies (critical pause, warning alert, nominal noop).
  3. QualityMonitor decision policies (DLQ empty noop, auto-replay start, alert escalation).
  4. Platform SRE tools (db_tool, metrics_tool, temporal_tool).
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from packages.supervisor.base_supervisor import BaseSupervisor, AgentDecision, BaseAgent
from packages.supervisor.resource_monitor import ResourceMonitor, ResourceManagerAgent
from packages.supervisor.quality_monitor import QualityMonitor, DataQualityAgent
from packages.supervisor.tools.db_tool import get_dlq_stats, get_table_counts
from packages.supervisor.tools.metrics_tool import get_current_metrics
from packages.supervisor.tools.temporal_tool import list_active_workflows


def _run(coro):
    return asyncio.run(coro)


class ConcreteTestSupervisor(BaseSupervisor):
    """Minimal concrete supervisor for testing base lifecycle."""

    async def observe(self) -> dict:
        return {"observed_value": 42}

    async def decide(self, observations: dict) -> AgentDecision:
        val = observations.get("observed_value", 0)
        if val > 100:
            return AgentDecision(action="alert", rationale="Value exceeded 100")
        return AgentDecision(action="noop", rationale="Value within parameters", confidence=1.0)


class TestBaseSupervisor(unittest.TestCase):
    """Test suite for BaseSupervisor lifecycle."""

    def test_supervisor_cycle_execution(self):
        sup = ConcreteTestSupervisor(name="test-sup")
        res = _run(sup.run_cycle())
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["action"], "noop")
        self.assertEqual(res["rationale"], "Value within parameters")
        self.assertIn("cycle_id", res)

    def test_backward_compatibility_alias(self):
        self.assertIs(BaseAgent, BaseSupervisor)
        self.assertIs(ResourceManagerAgent, ResourceMonitor)
        self.assertIs(DataQualityAgent, QualityMonitor)


class TestResourceMonitor(unittest.TestCase):
    """Test suite for ResourceMonitor decisions."""

    def setUp(self):
        self.monitor = ResourceMonitor(config={
            "db_pool_throttle_threshold": 0.85,
            "db_pool_critical_threshold": 0.95,
        })

    def test_nominal_utilization_noop(self):
        obs = {
            "metrics": {"db_pool_utilization": 0.30},
            "active_workflows": {"geospatial": [], "registry": []},
        }
        decision = _run(self.monitor.decide(obs))
        self.assertEqual(decision.action, "noop")
        self.assertIn("nominal", decision.rationale.lower())

    def test_throttle_utilization_warning(self):
        obs = {
            "metrics": {"db_pool_utilization": 0.88},
            "active_workflows": {"geospatial": [], "registry": []},
        }
        decision = _run(self.monitor.decide(obs))
        self.assertEqual(decision.action, "alert")
        self.assertFalse(decision.requires_human_approval)
        self.assertIn("recommend backpressure", decision.rationale)

    def test_critical_utilization_pause_signal(self):
        obs = {
            "metrics": {"db_pool_utilization": 0.98},
            "active_workflows": {
                "geospatial": [{"id": "wf-gmaps-999"}],
                "registry": [],
            },
        }
        decision = _run(self.monitor.decide(obs))
        self.assertEqual(decision.action, "signal_workflow")
        self.assertEqual(decision.signal_name, "pause")
        self.assertEqual(decision.workflow_id, "wf-gmaps-999")


class TestQualityMonitor(unittest.TestCase):
    """Test suite for QualityMonitor decisions."""

    def setUp(self):
        self.monitor = QualityMonitor(config={
            "dlq_auto_threshold": 50,
            "dlq_alert_threshold": 500,
        })

    def test_empty_dlq_noop(self):
        obs = {"dlq_pending": 0, "oldest_age_hours": 0.0}
        decision = _run(self.monitor.decide(obs))
        self.assertEqual(decision.action, "noop")
        self.assertIn("empty", decision.rationale.lower())

    def test_small_dlq_auto_replay(self):
        obs = {"dlq_pending": 25, "oldest_age_hours": 1.2}
        decision = _run(self.monitor.decide(obs))
        self.assertEqual(decision.action, "start_workflow")
        self.assertEqual(decision.workflow_type, "DLQReplayWorkflow")
        self.assertFalse(decision.requires_human_approval)

    def test_large_dlq_escalation_alert(self):
        obs = {"dlq_pending": 150, "oldest_age_hours": 8.5}
        decision = _run(self.monitor.decide(obs))
        self.assertEqual(decision.action, "alert")
        self.assertTrue(decision.requires_human_approval)
        self.assertIn("exceeds auto-replay threshold", decision.rationale)


class TestSupervisorTools(unittest.TestCase):
    """Test suite for Supervisor SRE inspection tools."""

    @patch("packages.infrastructure.dead_letter_queue.get_dead_letter_stats")
    @patch("packages.infrastructure.db_connector.get_connection")
    @patch("packages.infrastructure.db_connector.release_connection")
    def test_get_dlq_stats_tool(self, mock_rel, mock_conn, mock_stats):
        mock_conn.return_value = MagicMock()
        mock_stats.return_value = {
            "total_pending": 12,
            "oldest_record_age_hours": 3.4,
            "pending_by_source": {"sec": 5, "gmaps": 7},
            "total_replayed": 100,
        }
        stats = _run(get_dlq_stats())
        self.assertEqual(stats["dlq_pending"], 12)
        self.assertEqual(stats["oldest_age_hours"], 3.4)
        self.assertEqual(stats["by_source"]["sec"], 5)

    def test_get_current_metrics_tool(self):
        metrics = _run(get_current_metrics(["db_pool_utilization", "unknown_metric"]))
        self.assertIn("db_pool_utilization", metrics)
        self.assertIsNone(metrics["unknown_metric"])


if __name__ == "__main__":
    unittest.main()
