"""
Unit Tests for OpenSearch CDC High-Watermark Safety & DLQ Routing
================================================================
Verifies that:
1. Watermark advances monotonically on successful bulk indexing.
2. In partial failure batches, watermark halts strictly before the first failed document.
3. If the first document fails, watermark does not advance at all (prevents skipping).
4. Failed item payloads are enqueued to the Dead-Letter Queue (DLQ).
5. Cluster network errors abort watermark updates when offline stubbing is disabled.
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from packages.infrastructure.opensearch_cdc_sync import OpenSearchCDCSyncClient


class TestOpenSearchCDCWatermarkSafety(unittest.TestCase):

    def setUp(self):
        self.config = {
            "base_url": "http://127.0.0.1:9200",
            "index_companies": "test_companies",
            "index_people": "test_people",
            "user": "admin",
            "password": "secret_password",
            "verify_certs": False,
            "timeout": 5,
            "allow_offline": False,
        }
        self.client = OpenSearchCDCSyncClient(self.config)

    def _create_mock_row(self, org_id: str, name: str, sync_version: int):
        # 16-tuple matching kg_search.company_search_projection select columns
        # (org_id, jurisdiction, legal_name, display_name, primary_domain,
        #  all_domains, all_aliases, industry_naics, employee_count,
        #  annual_revenue_usd, technologies, latitude, longitude,
        #  quality_score, sync_version, last_projected_at)
        return (
            org_id,
            "us_delaware",
            f"{name} Inc",
            name,
            f"{name.lower()}.com",
            [f"{name.lower()}.com"],
            [name],
            "541511",
            150,
            25000000.0,
            ["Python", "PostgreSQL"],
            37.7749,
            -122.4194,
            95,
            sync_version,
            datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc),
        )

    @patch("packages.infrastructure.dead_letter_queue.enqueue_dead_letter")
    def test_watermark_advances_fully_on_clean_batch(self, mock_dlq):
        """When all items succeed, watermark updates to max_version and status is SUCCESS."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # Initial watermark: version 100, timestamp 2026-11-04 09:00:00, total 50
        mock_cur.fetchone.return_value = (
            100,
            datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc),
            50,
        )

        # 3 batch rows: versions 101, 102, 103
        rows = [
            self._create_mock_row("org-1", "Alpha", 101),
            self._create_mock_row("org-2", "Beta", 102),
            self._create_mock_row("org-3", "Gamma", 103),
        ]
        mock_cur.fetchall.return_value = rows

        # OpenSearch _bulk success response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "took": 15,
            "errors": False,
            "items": [
                {"index": {"_id": "org-1", "status": 201}},
                {"index": {"_id": "org-2", "status": 201}},
                {"index": {"_id": "org-3", "status": 201}},
            ],
        }

        with patch.object(self.client.session, "post", return_value=mock_resp):
            result = self.client.sync_companies_cdc(mock_conn, batch_limit=10)

        self.assertEqual(result["status"], "synced")
        self.assertEqual(result["records_synced"], 3)
        self.assertEqual(result["failed_count"], 0)
        self.assertEqual(result["max_version"], 103)
        mock_dlq.assert_not_called()

        # Check DB update args
        update_call = [c for c in mock_cur.execute.call_args_list if "UPDATE kg_search.cdc_watermarks" in c[0][0]]
        self.assertEqual(len(update_call), 1)
        args = update_call[0][0][1]
        self.assertEqual(args[0], 103)  # safe_watermark_version
        self.assertEqual(args[2], 53)   # new_total (50 + 3)
        self.assertEqual(args[4], "SUCCESS")

    @patch("packages.infrastructure.dead_letter_queue.enqueue_dead_letter")
    def test_watermark_stops_before_first_failed_item(self, mock_dlq):
        """When item 1 fails, watermark advances ONLY up to item 0 (version 101), and item 1 is routed to DLQ."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = (
            100,
            datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc),
            50,
        )

        rows = [
            self._create_mock_row("org-1", "Alpha", 101),
            self._create_mock_row("org-2", "Beta", 102),
            self._create_mock_row("org-3", "Gamma", 103),
        ]
        mock_cur.fetchall.return_value = rows

        # OpenSearch _bulk partial failure: item 1 (Beta) fails with 400
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "took": 22,
            "errors": True,
            "items": [
                {"index": {"_id": "org-1", "status": 201}},
                {"index": {"_id": "org-2", "status": 400, "error": {"type": "mapper_parsing_exception", "reason": "failed to parse field"}}},
                {"index": {"_id": "org-3", "status": 201}},
            ],
        }

        with patch.object(self.client.session, "post", return_value=mock_resp):
            result = self.client.sync_companies_cdc(mock_conn, batch_limit=10)

        self.assertEqual(result["status"], "partial_failure")
        self.assertEqual(result["records_synced"], 1)  # Only row 0
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["max_version"], 101)   # Halted at row 0's version!

        # DLQ should have received row 1 (org-2)
        mock_dlq.assert_called_once()
        dlq_kwargs = mock_dlq.call_args[1]
        self.assertEqual(dlq_kwargs["source_name"], "opensearch_cdc")
        self.assertEqual(dlq_kwargs["failed_stage"], "SEARCH_INDEXING")
        self.assertEqual(dlq_kwargs["payload"]["org_id"], "org-2")

        # Watermark DB update should have committed version 101 with PARTIAL_FAILURE
        update_call = [c for c in mock_cur.execute.call_args_list if "UPDATE kg_search.cdc_watermarks" in c[0][0]]
        self.assertEqual(len(update_call), 1)
        args = update_call[0][0][1]
        self.assertEqual(args[0], 101)  # Safe watermark halted at 101
        self.assertEqual(args[2], 51)   # 50 + 1
        self.assertEqual(args[4], "PARTIAL_FAILURE")

    @patch("packages.infrastructure.dead_letter_queue.enqueue_dead_letter")
    def test_watermark_does_not_advance_when_first_item_fails(self, mock_dlq):
        """When row 0 fails, watermark must stay at last_version (100) to ensure retry on next cycle."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = (
            100,
            datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc),
            50,
        )

        rows = [
            self._create_mock_row("org-1", "Alpha", 101),
            self._create_mock_row("org-2", "Beta", 102),
        ]
        mock_cur.fetchall.return_value = rows

        # OpenSearch _bulk: row 0 fails
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "took": 10,
            "errors": True,
            "items": [
                {"index": {"_id": "org-1", "status": 500, "error": {"type": "cluster_block_exception"}}},
                {"index": {"_id": "org-2", "status": 201}},
            ],
        }

        with patch.object(self.client.session, "post", return_value=mock_resp):
            result = self.client.sync_companies_cdc(mock_conn, batch_limit=10)

        self.assertEqual(result["status"], "partial_failure")
        self.assertEqual(result["records_synced"], 0)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["max_version"], 100)  # Preserved at initial watermark!

        # Check DB update
        update_call = [c for c in mock_cur.execute.call_args_list if "UPDATE kg_search.cdc_watermarks" in c[0][0]]
        self.assertEqual(len(update_call), 1)
        args = update_call[0][0][1]
        self.assertEqual(args[0], 100)  # Watermark remained 100
        self.assertEqual(args[2], 50)   # Total remained 50
        self.assertEqual(args[4], "PARTIAL_FAILURE")

    def test_abort_watermark_on_connection_error_without_offline_stub(self):
        """When cluster is unreachable and allow_offline is False, raises RuntimeError without updating watermark."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = (
            100,
            datetime(2026, 11, 4, 9, 0, 0, tzinfo=timezone.utc),
            50,
        )

        rows = [self._create_mock_row("org-1", "Alpha", 101)]
        mock_cur.fetchall.return_value = rows

        with patch.object(self.client.session, "post", side_effect=Exception("Connection refused")):
            with self.assertRaises(RuntimeError) as ctx:
                self.client.sync_companies_cdc(mock_conn, batch_limit=10)
            self.assertIn("OpenSearch CDC push failed", str(ctx.exception))

        # Crucial invariant: UPDATE kg_search.cdc_watermarks must NEVER have run!
        update_calls = [c for c in mock_cur.execute.call_args_list if "UPDATE kg_search.cdc_watermarks" in c[0][0]]
        self.assertEqual(len(update_calls), 0)


if __name__ == "__main__":
    unittest.main()
