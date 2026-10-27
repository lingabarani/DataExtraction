"""
DataExtraction — E2E Scenario 5: Temporal Distributed Saga & Resilience
========================================================================
Comprehensive End-to-End integration test covering:
1. MasterOrchestrationWorkflow lifecycle execution.
2. Signal handling: pause, resume, cancel_phase.
3. Live query introspection (get_status).
4. Pipeline activity execution (normalization, deduplication, tax validation).
5. Storage & Dead-Letter Queue activities integration.
"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Bootstrap paths
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGES = _REPO_ROOT / "packages"

for p in [
    _PACKAGES / "temporal",
    _PACKAGES / "temporal" / "activities",
    _PACKAGES / "temporal" / "workflows",
    _PACKAGES / "pipeline",
    _PACKAGES / "infrastructure",
    _REPO_ROOT / "tests" / "e2e" / "utils",
    _REPO_ROOT,
]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from packages.temporal.activities.pipeline_activities import (
    normalize_batch_activity,
    deduplicate_batch_activity,
    validate_tax_ids_activity,
)
from packages.temporal.activities.storage_activities import (
    fetch_dlq_records_activity,
    resolve_dlq_record_activity,
    get_dlq_stats_activity,
)
from packages.temporal.workflows.master_orchestration_workflow import MasterOrchestrationWorkflow
from db_test_cleaner import EphemeralDatabaseHarness


class TestE2ETemporalSaga(unittest.IsolatedAsyncioTestCase):
    """End-to-End test suite for Temporal Sagas, Signals, and Activities."""

    @classmethod
    def setUpClass(cls):
        cls.harness = EphemeralDatabaseHarness()
        cls.conn = cls.harness.get_connection()

    def setUp(self):
        self.harness.clean_tables()

    @classmethod
    def tearDownClass(cls):
        cls.harness.close()

    async def test_e2e_master_workflow_signal_and_query_handling(self):
        """Verifies MasterOrchestrationWorkflow responds to pause, resume, and cancel_phase signals."""
        wf = MasterOrchestrationWorkflow()

        # Initial state query with mocked workflow runtime context
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"):
            mock_info.return_value.workflow_id = "test-master-wf-001"
            status = wf.get_status()
            self.assertEqual(status["status"], "RUNNING")
            self.assertEqual(status["phase"], "INIT")
            self.assertFalse(status["paused"])

            # 1. Dispatch PAUSE signal
            wf.pause()
            status = wf.get_status()
            self.assertTrue(status["paused"])

            # 2. Dispatch RESUME signal
            wf.resume()
            status = wf.get_status()
            self.assertFalse(status["paused"])

            # 3. Dispatch CANCEL PHASE signal
            wf.cancel_phase("OSM")
            self.assertTrue(wf._cancelled)

    async def test_e2e_pipeline_activity_execution(self):
        """Verifies pipeline activities execute without errors and return structured results."""
        with patch("temporalio.activity.logger"), patch("temporalio.activity.heartbeat"):
            # 1. Normalization activity
            norm_res = await normalize_batch_activity(source="CMS_NPI", table="companies", batch_size=100)
            self.assertEqual(norm_res["status"], "SUCCESS")
            self.assertEqual(norm_res["source"], "CMS_NPI")

            # 2. Deduplication activity
            dedup_res = await deduplicate_batch_activity(table="companies", batch_size=50)
            self.assertEqual(dedup_res["status"], "SUCCESS")

            # 3. Tax validation activity
            tax_res = await validate_tax_ids_activity(table="companies", limit=100)
            self.assertEqual(tax_res["status"], "SUCCESS")

    async def test_e2e_storage_and_dlq_activities(self):
        """Verifies Dead-Letter Queue fetch, resolve, and stats activities."""
        with patch("temporalio.activity.logger"):
            # 1. Get DLQ stats
            stats = await get_dlq_stats_activity()
            self.assertIn("total", stats)
            self.assertIn("pending", stats)

            # 2. Fetch DLQ records
            dlq_res = await fetch_dlq_records_activity({"limit": 10, "status": "PENDING"})
            self.assertIn("records", dlq_res)
            self.assertIn("total", dlq_res)

            # 3. Resolve DLQ record activity
            res_act = await resolve_dlq_record_activity(record_id="999", status="DISCARDED", notes="Test resolution")
            self.assertEqual(res_act["status"], "DISCARDED")
            self.assertEqual(res_act["record_id"], "999")


if __name__ == "__main__":
    unittest.main()
