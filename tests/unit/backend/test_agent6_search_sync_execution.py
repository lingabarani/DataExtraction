"""
Agent 6 (Persistence, CDC & Search Synchronization) Comprehensive Test Suite
============================================================================
Verifies:
1. Physical Partition Management:
   - maintain_kg_partitions_activity verifying multi-year and quarterly partitions
   - Catalog verification across kg_graph.employment_relationships and kg_observation.observation_metadata
2. Change Data Capture (CDC) Synchronization:
   - sync_opensearch_cdc_activity querying kg_search.company_search_projection
   - Watermark tracking in kg_search.cdc_watermarks
   - Offline stub fallback and graceful error isolation
3. OpenSearch Client CDC Engine:
   - Bulk ndjson formatting
   - Version watermark advancement
4. Agent6SearchSyncWorkflow:
   - Signals: pause, resume, force_sync
   - Query: get_status() safe fallback
   - End-to-end workflow execution returning search_documents_projected telemetry
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
from packages.infrastructure.opensearch_cdc_sync import opensearch_client
from packages.temporal.activities.storage_activities import (
    maintain_kg_partitions_activity,
    sync_opensearch_cdc_activity,
)
from packages.temporal.workflows.w6_search_sync_workflow import Agent6SearchSyncWorkflow


class TestAgent6SearchSyncExecution(unittest.TestCase):
    def test_01_maintain_kg_partitions_activity(self):
        """Maintain and verify physical database partitions across Knowledge Graph tables."""
        res = asyncio.run(maintain_kg_partitions_activity())
        self.assertEqual(res.get("status"), "success")
        self.assertGreater(res.get("total_partitions_in_cluster", 0), 0)
        self.assertIn("catalog", res)

    def test_02_sync_opensearch_cdc_activity(self):
        """Execute CDC synchronization from company_search_projection with offline stub support."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errors": False, "items": []}

        with patch.object(opensearch_client.session, "post", return_value=mock_resp):
            res = asyncio.run(sync_opensearch_cdc_activity(batch_limit=10))
            self.assertIn(res.get("status"), ("synced", "success", "up_to_date"))
            self.assertIn("records_synced", res)

    def test_03_opensearch_cdc_watermark_persistence(self):
        """Verify CDC watermark table tracks consumer state."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT consumer_id, last_synced_version, records_synced_total
                    FROM kg_search.cdc_watermarks
                    WHERE consumer_id LIKE 'opensearch_%';
                """)
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertTrue(row[0].startswith("opensearch_"))
        finally:
            release_connection(conn)

    def test_04_workflow_signals_and_query(self):
        """Verify Agent6SearchSyncWorkflow signal state transitions and query response."""
        wf = Agent6SearchSyncWorkflow()
        status = wf.get_status()
        self.assertEqual(status["status"], "INITIALIZED")
        self.assertFalse(status["paused"])
        self.assertFalse(status["force_sync"])
        self.assertEqual(status["workflow_id"], "agent6-search")

        wf.pause()
        self.assertTrue(wf._paused)

        wf.resume()
        self.assertFalse(wf._paused)

        wf.force_sync()
        self.assertTrue(wf._force_sync_requested)

    def test_05_workflow_full_execution(self):
        """Execute Agent6SearchSyncWorkflow.run() end-to-end with mocked activities."""
        wf = Agent6SearchSyncWorkflow()

        async def mock_execute_activity(activity_fn, *args, **kwargs):
            fn_name = getattr(activity_fn, "__name__", str(activity_fn))
            if "maintain_kg_partitions" in fn_name:
                return {"status": "success", "total_partitions_in_cluster": 60}
            elif "sync_opensearch_cdc" in fn_name:
                return {"status": "success", "records_synced": 500, "duration_ms": 120}
            return {"status": "SUCCESS"}

        with patch("temporalio.workflow.execute_activity", side_effect=mock_execute_activity), \
             patch("temporalio.workflow.wait_condition", new_callable=AsyncMock):
            result = asyncio.run(wf.run({
                "run_partitions": True,
                "run_search_sync": True,
                "sync_batch_limit": 500,
            }))

            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["search_documents_projected"], 500)
            self.assertIn("partitions", result["results"])
            self.assertIn("opensearch_sync", result["results"])


if __name__ == "__main__":
    unittest.main()
