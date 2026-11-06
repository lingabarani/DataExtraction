"""
DataExtraction — Unit Test Suite: Prometheus Metrics & Telemetry Exporter
========================================================================
Validates:
  1. Prometheus metric generation & serialization
  2. Registration of HTTP request counters and duration histograms
  3. Dynamic update of connection pool and DLQ gauges
  4. Both dataextraction_* and oneextraction_* naming compatibility
  5. /metrics FastAPI response format and status 200
"""

import unittest
from unittest.mock import MagicMock, patch

from packages.infrastructure.metrics import (
    get_metrics_response,
    record_request_metrics,
    update_system_gauges,
    DATAEXTRACTION_DB_POOL_ACTIVE_CONNECTIONS,
    DATAEXTRACTION_DB_POOL_CAPACITY,
    DATAEXTRACTION_DLQ_PENDING_RECORDS,
    DATAEXTRACTION_DLQ_ALERT_STATUS,
    PROMETHEUS_AVAILABLE,
)


class TestPrometheusMetrics(unittest.TestCase):

    def test_prometheus_installed_and_available(self):
        """Verifies prometheus_client is installed and active in environment."""
        self.assertTrue(PROMETHEUS_AVAILABLE, "prometheus_client must be installed")

    def test_record_request_metrics(self):
        """Verifies request metrics recorder operates without exception on paths."""
        record_request_metrics("GET", "/api/leads/123", 200, 0.025)
        record_request_metrics("POST", "/api/campaigns/456", 201, 0.050)
        record_request_metrics("GET", "/metrics", 200, 0.005)

    @patch("packages.infrastructure.dead_letter_queue.get_dlq_stats")
    def test_update_system_gauges(self, mock_dlq_stats):
        """Verifies update_system_gauges synchronizes gauges with mock pool and DLQ stats."""
        mock_dlq_stats.return_value = {"pending_count": 42}

        update_system_gauges()

        self.assertEqual(DATAEXTRACTION_DLQ_PENDING_RECORDS._value.get(), 42)
        self.assertEqual(DATAEXTRACTION_DLQ_ALERT_STATUS._value.get(), 0)

        # Trigger critical alert (> 100)
        mock_dlq_stats.return_value = {"pending_count": 150}
        update_system_gauges()
        self.assertEqual(DATAEXTRACTION_DLQ_ALERT_STATUS._value.get(), 1)

    @patch("packages.infrastructure.dead_letter_queue.get_dlq_stats")
    def test_get_metrics_response(self, mock_dlq_stats):
        """Verifies get_metrics_response returns HTTP 200 response with prometheus payload."""
        mock_dlq_stats.return_value = {"pending_count": 5}

        resp = get_metrics_response()
        self.assertEqual(resp.status_code, 200)
        content = resp.body.decode("utf-8")

        # Verify key metrics are present
        self.assertIn("http_requests_total", content)
        self.assertIn("dataextraction_dlq_pending_records", content)
        self.assertIn("oneextraction_dlq_pending_records", content)
        self.assertIn("dataextraction_db_pool_active_connections", content)


if __name__ == "__main__":
    unittest.main()

