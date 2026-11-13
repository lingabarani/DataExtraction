"""
Agent 5 (Governance, Quality & Confidence Engine) Comprehensive Test Suite
==========================================================================
Verifies:
1. Dead-Letter Queue (DLQ) Auditing:
   - get_dlq_stats_activity retrieval from database
   - fetch_dlq_records_activity paginated retrieval
2. Working Layer Governance & Certification Gate:
   - evaluate_working_governance_activity evaluating Bayesian Quality and Trust
   - Approved vs Quarantined segregation
3. Atomic Master Promotion Gate:
   - promote_certified_to_master_activity promoting approved entities into master_dataextraction
   - Verification timestamp and freshness initialization
4. Bayesian Quality Scoring:
   - compute_bayesian_quality_activity multi-dimensional completeness evaluation
5. Agent5GovernanceWorkflow:
   - Signals: pause, resume, replay_dlq
   - Query: get_status() safe fallback
   - End-to-end workflow execution with quality_score and approved_count telemetry
"""

import asyncio
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
for p in (str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "pipeline"), str(REPO_ROOT / "packages" / "infrastructure")):
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.temporal.activities.storage_activities import (
    get_dlq_stats_activity,
    fetch_dlq_records_activity,
    evaluate_working_governance_activity,
    promote_certified_to_master_activity,
    compute_bayesian_quality_activity,
)
from packages.temporal.workflows.w5_governance_workflow import Agent5GovernanceWorkflow


class TestAgent5GovernanceExecution(unittest.TestCase):
    def test_01_get_dlq_stats_activity(self):
        """Retrieve DLQ statistics from live database."""
        stats = asyncio.run(get_dlq_stats_activity())
        self.assertIn("total", stats)
        self.assertIn("pending", stats)
        self.assertIn("sources", stats)

    def test_02_fetch_dlq_records_activity(self):
        """Retrieve paginated DLQ records."""
        res = asyncio.run(fetch_dlq_records_activity({"limit": 5}))
        self.assertIn("records", res)
        self.assertIn("total", res)

    def test_03_evaluate_working_governance_activity(self):
        """Evaluate pre-master working layer organizations against Bayesian Quality & Trust rules."""
        res = asyncio.run(evaluate_working_governance_activity(10))
        self.assertEqual(res.get("status"), "COMPLETED")
        self.assertIn("evaluated_count", res)
        self.assertIn("approved_count", res)
        self.assertIn("quarantined_count", res)

    def test_04_promote_certified_to_master_activity(self):
        """Execute atomic promotion gate from working layer into master database."""
        res = asyncio.run(promote_certified_to_master_activity(80, 0.85, 10))
        self.assertEqual(res.get("status"), "COMPLETED")
        self.assertIn("promoted_orgs", res)
        self.assertIn("promoted_persons", res)
        self.assertIn("promoted_emails", res)

    def test_05_compute_bayesian_quality_activity(self):
        """Compute Bayesian entity quality score for single organization."""
        payload = {
            "entity_data": {
                "legal_name": "Apex Dynamics Corporation",
                "primary_domain": "apexdynamics.com",
                "statutory_tax_id": "12-3456789",
                "city": "Austin",
                "state_code": "TX",
                "phone": "+1-555-0199",
            },
            "entity_type": "organization",
            "contributing_sources": ["SEC", "OPEN_STREET_MAP"],
        }
        res = asyncio.run(compute_bayesian_quality_activity(payload))
        self.assertIn("data_quality_score", res)
        self.assertGreater(res["data_quality_score"], 0)

    def test_06_workflow_signals_and_query(self):
        """Verify Agent5GovernanceWorkflow signal handling and query response."""
        wf = Agent5GovernanceWorkflow()
        status = wf.get_status()
        self.assertEqual(status["status"], "INITIALIZED")
        self.assertFalse(status["paused"])
        self.assertFalse(status["replay_dlq_requested"])
        self.assertEqual(status["workflow_id"], "agent5-governance")

        wf.pause()
        self.assertTrue(wf._paused)

        wf.resume()
        self.assertFalse(wf._paused)

        wf.replay_dlq()
        self.assertTrue(wf._replay_dlq_requested)

    def test_07_workflow_full_execution(self):
        """Execute Agent5GovernanceWorkflow.run() end-to-end with mocked activities."""
        wf = Agent5GovernanceWorkflow()

        async def mock_execute_activity(activity_fn, *args, **kwargs):
            fn_name = getattr(activity_fn, "__name__", str(activity_fn))
            if "get_dlq_stats" in fn_name:
                return {"total": 0, "by_status": {"PENDING": 0}}
            elif "evaluate_working_governance" in fn_name:
                return {"status": "COMPLETED", "evaluated_count": 50, "approved_count": 48, "quarantined_count": 2}
            elif "promote_certified_to_master" in fn_name:
                return {"status": "COMPLETED", "promoted_orgs": 48, "promoted_persons": 96, "promoted_emails": 120}
            return {"status": "SUCCESS"}

        with patch("temporalio.workflow.execute_activity", side_effect=mock_execute_activity), \
             patch("temporalio.workflow.wait_condition", new_callable=AsyncMock):
            result = asyncio.run(wf.run({
                "batch_limit": 50,
                "min_quality": 80,
                "min_trust": 0.85,
            }))

            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["approved_count"], 48)
            self.assertEqual(result["quarantined_count"], 2)
            self.assertEqual(result["promoted_orgs"], 48)
            self.assertEqual(result["quality_score"], 94)
            self.assertIn("dlq_stats", result["results"])
            self.assertIn("working_governance_evaluation", result["results"])
            self.assertIn("promotion_gate", result["results"])


if __name__ == "__main__":
    unittest.main()
