"""
DataExtraction — Unit Test Suite: OneReach Delivery Service
===========================================================
Validates:
  1. HMAC-SHA256 signature computation and constant-time verification
  2. OneReach delivery dispatch in dry_run mode
  3. Successful HTTP dispatch with HMAC headers
  4. Exponential backoff retry logic (up to max_retries)
  5. Exhausted retries failover routing to Dead-Letter Queue (DLQ)
  6. Delivery audit logging to master_dataextraction.onereach_delivery_log
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from packages.domain.onereach_delivery_service import (
    OneReachDeliveryService,
    compute_hmac_signature,
    verify_hmac_signature,
)


class TestOneReachDeliveryService(unittest.TestCase):

    def setUp(self):
        self.secret = "test-onereach-secret-key-12345"
        self.webhook_url = "https://mock-onereach.ai/v1/leads"
        self.service = OneReachDeliveryService({
            "webhook_url": self.webhook_url,
            "secret_token": self.secret,
            "timeout": 2.0,
            "max_retries": 3,
        })
        self.sample_lead = {
            "id": "comp-test-001",
            "name": "Apollo Global Enterprise",
            "domain": "apollo-enterprise.io",
            "email": "contact@apollo-enterprise.io",
            "data_quality_score": 96,
        }

    def test_hmac_signature_computation_and_verification(self):
        """Verifies HMAC-SHA256 signature generation and constant-time verification."""
        payload_bytes = json.dumps(self.sample_lead).encode("utf-8")
        sig = compute_hmac_signature(payload_bytes, self.secret)

        self.assertIsInstance(sig, str)
        self.assertEqual(len(sig), 64)  # 256 bits = 64 hex characters

        # Verification succeeds with matching secret
        self.assertTrue(verify_hmac_signature(payload_bytes, self.secret, sig))

        # Verification fails with invalid/tampered secret
        self.assertFalse(verify_hmac_signature(payload_bytes, "wrong-secret", sig))

        # Verification fails with tampered payload
        tampered_bytes = json.dumps({"tampered": True}).encode("utf-8")
        self.assertFalse(verify_hmac_signature(tampered_bytes, self.secret, sig))

        # Verification fails with empty signature
        self.assertFalse(verify_hmac_signature(payload_bytes, self.secret, ""))

    @patch.object(OneReachDeliveryService, "log_delivery_attempt")
    def test_dispatch_dry_run_simulation(self, mock_log):
        """Verifies dry-run dispatch computes signature and returns SIMULATED without HTTP request."""
        res = self.service.dispatch_payload(
            payload_data=dict(self.sample_lead),
            dry_run=True,
        )
        self.assertEqual(res["status"], "SIMULATED")
        self.assertTrue(res["dry_run"])
        self.assertEqual(len(res["signature"]), 64)
        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args[1]["status"], "SIMULATED")

    @patch.object(OneReachDeliveryService, "log_delivery_attempt")
    def test_dispatch_success_first_attempt(self, mock_log):
        """Verifies clean HTTP 200 response results in DELIVERED status and audit logging."""
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"success": true, "received": 1}'
        mock_session.post.return_value = mock_resp

        res = self.service.dispatch_payload(
            payload_data=dict(self.sample_lead),
            session=mock_session,
        )

        self.assertEqual(res["status"], "DELIVERED")
        self.assertEqual(res["http_status"], 200)
        self.assertEqual(res["attempts"], 1)

        # Verify headers sent
        headers_sent = mock_session.post.call_args[1]["headers"]
        self.assertIn("X-OneReach-Signature", headers_sent)
        self.assertIn("X-OneReach-Signature-256", headers_sent)
        self.assertEqual(headers_sent["X-OneReach-Signature-256"], res["signature"])

        mock_log.assert_called_once()
        self.assertEqual(mock_log.call_args[1]["status"], "DELIVERED")

    @patch("time.sleep")
    @patch.object(OneReachDeliveryService, "log_delivery_attempt")
    def test_dispatch_retries_with_backoff_and_eventual_success(self, mock_log, mock_sleep):
        """Verifies service retries on HTTP 500 and succeeds on subsequent attempt."""
        mock_session = MagicMock()
        fail_resp = MagicMock()
        fail_resp.status_code = 503
        fail_resp.text = "Service Unavailable"

        success_resp = MagicMock()
        success_resp.status_code = 201
        success_resp.text = "Created"

        mock_session.post.side_effect = [fail_resp, success_resp]

        res = self.service.dispatch_payload(
            payload_data=dict(self.sample_lead),
            session=mock_session,
        )

        self.assertEqual(res["status"], "DELIVERED")
        self.assertEqual(res["http_status"], 201)
        self.assertEqual(res["attempts"], 2)
        mock_sleep.assert_called_once_with(0.2)  # Initial backoff

    @patch("time.sleep")
    @patch("packages.domain.onereach_delivery_service.enqueue_dead_letter")
    @patch.object(OneReachDeliveryService, "log_delivery_attempt")
    def test_dispatch_permanent_exhaustion_routes_to_dlq(self, mock_log, mock_dlq, mock_sleep):
        """Verifies that upon exhausting all 3 retries, the failed payload is enqueued to DLQ."""
        mock_session = MagicMock()
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        fail_resp.text = "Internal Server Error"
        mock_session.post.return_value = fail_resp

        res = self.service.dispatch_payload(
            payload_data=dict(self.sample_lead),
            session=mock_session,
        )

        self.assertEqual(res["status"], "FAILED")
        self.assertEqual(res["attempts"], 3)
        self.assertTrue(res["routed_to_dlq"])

        # DLQ routing assertion
        mock_dlq.assert_called_once()
        dlq_kwargs = mock_dlq.call_args[1]
        self.assertEqual(dlq_kwargs["source_name"], "onereach_delivery")
        self.assertEqual(dlq_kwargs["failed_stage"], "ONEREACH_DELIVERY")
        self.assertEqual(dlq_kwargs["error_type"], "OneReachDeliveryExhausted")


if __name__ == "__main__":
    unittest.main()

