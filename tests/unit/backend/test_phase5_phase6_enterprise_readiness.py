"""
DataExtraction — Unit Test Suite: Phase 5 (Scalability) & Phase 6 (Enterprise Readiness)
========================================================================================
Validates:
  1. Asymmetric RS256 JWT Authentication & Dual-Mode Key Support.
  2. SOC-2 Type II Immutable Access Audit Trail Repository.
  3. GDPR / CCPA Right-to-be-Forgotten & Consumer Suppression Engine.
  4. IP Sliding-Window Rate Limiting Middleware.
  5. Kubernetes Manifests & Autoscaling (HPA) Architecture for 7 Distributed Workers.
"""

import hashlib
import json
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from jose import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.audit_trail_repository import AuditTrailRepository
from packages.domain.compliance_manager import ComplianceManager
from packages.api.middleware.rate_limiter import SlidingWindowRateLimiter
from packages.api.dependencies import UserPrincipal, get_current_user


class TestAsymmetricRS256JWT(unittest.TestCase):
    """Verifies RS256 RSA public/private key signing and verification."""

    @classmethod
    def setUpClass(cls):
        # Generate test RSA keypair
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.priv_pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        cls.pub_pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

    def test_rs256_token_generation_and_decoding(self):
        payload = {
            "sub": "auditor@oneextraction.internal",
            "name": "Enterprise Auditor",
            "is_admin": True,
            "exp": time.time() + 3600,
            "iat": time.time(),
        }
        token = jwt.encode(payload, self.priv_pem, algorithm="RS256")
        self.assertTrue(token.startswith("ey"))

        decoded = jwt.decode(token, self.pub_pem, algorithms=["RS256"])
        self.assertEqual(decoded["sub"], "auditor@oneextraction.internal")
        self.assertEqual(decoded["name"], "Enterprise Auditor")
        self.assertTrue(decoded["is_admin"])

    def test_mismatched_key_fails_verification(self):
        # Generate another key
        other_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pub = other_priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        payload = {"sub": "user@oneextraction.internal", "exp": time.time() + 3600}
        token = jwt.encode(payload, self.priv_pem, algorithm="RS256")

        from jose.exceptions import JWTError
        with self.assertRaises(JWTError):
            jwt.decode(token, other_pub, algorithms=["RS256"])

    def test_config_manager_rsa_ephemeral_generation(self):
        """Verifies that config_manager generates and caches valid RSA keys in development."""
        priv = config_manager.get_jwt_private_key()
        pub = config_manager.get_jwt_public_key()
        self.assertIn("BEGIN PRIVATE KEY", priv)
        self.assertIn("BEGIN PUBLIC KEY", pub)


class TestAuditTrailRepository(unittest.TestCase):
    """Verifies SOC-2 Type II audit logging and query capabilities."""

    @patch("packages.infrastructure.audit_trail_repository.get_connection")
    @patch("packages.infrastructure.audit_trail_repository.release_connection")
    def test_record_access_event(self, mock_release, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        event_id = AuditTrailRepository.record_access_event(
            user_id="user-123",
            user_email="operator@oneextraction.internal",
            action="LEAD_READ",
            resource_type="leads",
            resource_id="lead-abc",
            ip_address="192.168.1.50",
            user_agent="Mozilla/5.0 Test",
            status_code=200,
            metadata={"filters": {"state": "CA"}},
        )

        self.assertTrue(len(event_id) > 10)
        mock_conn.commit.assert_called_once()
        mock_release.assert_called_once_with(mock_conn)

    @patch("packages.infrastructure.audit_trail_repository.get_connection")
    @patch("packages.infrastructure.audit_trail_repository.release_connection")
    def test_query_access_logs(self, mock_release, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            (
                "evt-1",
                "2026-11-02 10:00:00",
                "user-1",
                "user@oneextraction.internal",
                "LEAD_EXPORT",
                "export",
                "/api/export/csv",
                "127.0.0.1",
                "Agent/1.0",
                200,
                {"format": "csv"},
            )
        ]
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        logs = AuditTrailRepository.query_access_logs(limit=10, action="LEAD_EXPORT")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["action"], "LEAD_EXPORT")
        self.assertEqual(logs[0]["user_email"], "user@oneextraction.internal")


class TestComplianceManager(unittest.TestCase):
    """Verifies GDPR/CCPA suppression and right-to-be-forgotten engine."""

    def test_hash_identifier_sha256(self):
        email = " Consumer.Test@Domain.COM "
        expected = hashlib.sha256("consumer.test@domain.com".encode("utf-8")).hexdigest()
        self.assertEqual(ComplianceManager.hash_identifier(email), expected)

    @patch("packages.domain.compliance_manager.get_connection")
    @patch("packages.domain.compliance_manager.release_connection")
    @patch("packages.domain.compliance_manager.AuditTrailRepository.record_access_event")
    def test_register_suppression(self, mock_audit, mock_release, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ("suppression-uuid-123",)
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        res = ComplianceManager.register_suppression(
            identifier="optout@domain.com",
            identifier_type="email",
            reason="CCPA_OPT_OUT",
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["type"], "email")
        self.assertEqual(res["reason"], "CCPA_OPT_OUT")
        mock_conn.commit.assert_called_once()
        mock_audit.assert_called_once()

    @patch("packages.domain.compliance_manager.get_connection")
    @patch("packages.domain.compliance_manager.release_connection")
    @patch("packages.domain.compliance_manager.AuditTrailRepository.record_access_event")
    def test_execute_purge_dry_run(self, mock_audit, mock_release, mock_get_conn):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [(5,), (2,), (1,)]
        mock_conn.cursor.return_value = mock_cur
        mock_get_conn.return_value = mock_conn

        res = ComplianceManager.execute_purge(
            identifier="victim@domain.com",
            identifier_type="email",
            dry_run=True,
        )
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["status"], "SIMULATED")
        self.assertEqual(res["total_affected_records"], 8)
        # Commit must NOT be called in dry run
        mock_conn.commit.assert_not_called()


class TestRateLimiter(unittest.TestCase):
    """Verifies sliding window rate limiting logic."""

    def test_rate_limiter_allows_and_throttles(self):
        lim = SlidingWindowRateLimiter()
        ip = "192.168.10.100"

        # Under limit for auth (limit = 15)
        for i in range(15):
            allowed, count, limit = lim.check_rate_limit(ip, "/api/auth/login")
            self.assertTrue(allowed, f"Request {i+1} should be allowed")

        # 16th request must be rejected
        allowed, count, limit = lim.check_rate_limit(ip, "/api/auth/login")
        self.assertFalse(allowed)
        self.assertEqual(limit, 15)

    def test_general_api_has_higher_limit(self):
        lim = SlidingWindowRateLimiter()
        ip = "192.168.10.200"

        # General API allows up to 180 req/min
        allowed, count, limit = lim.check_rate_limit(ip, "/api/leads")
        self.assertTrue(allowed)
        self.assertEqual(limit, 180)


class TestKubernetesManifestsIntegrity(unittest.TestCase):
    """Verifies that Phase 5 & 6 Kubernetes manifests and HPAs exist and define all 7 queues."""

    def test_pgbouncer_k8s_manifest_exists(self):
        k8s_dir = Path(__file__).resolve().parents[3] / "infra" / "k8s"
        pgbouncer_file = k8s_dir / "06-pgbouncer-deployment.yaml"
        self.assertTrue(pgbouncer_file.exists(), "06-pgbouncer-deployment.yaml is missing")

        content = pgbouncer_file.read_text(encoding="utf-8")
        self.assertIn("kind: Deployment", content)
        self.assertIn("name: pgbouncer", content)
        self.assertIn("port: 6432", content)

    def test_distributed_workers_k8s_manifest_exists(self):
        k8s_dir = Path(__file__).resolve().parents[3] / "infra" / "k8s"
        workers_file = k8s_dir / "07-distributed-workers-deployment.yaml"
        self.assertTrue(workers_file.exists(), "07-distributed-workers-deployment.yaml is missing")

        content = workers_file.read_text(encoding="utf-8")
        # Verify all 7 worker deployments
        self.assertIn("name: worker-registry", content)
        self.assertIn("name: worker-geospatial", content)
        self.assertIn("name: worker-identity", content)
        self.assertIn("name: worker-executive", content)
        self.assertIn("name: worker-governance", content)
        self.assertIn("name: worker-search", content)
        self.assertIn("name: worker-email-enrichment", content)

        # Verify HPAs
        self.assertIn("kind: HorizontalPodAutoscaler", content)
        self.assertIn("name: worker-registry-hpa", content)
        self.assertIn("name: worker-identity-hpa", content)
        self.assertIn("name: worker-email-enrichment-hpa", content)


if __name__ == "__main__":
    unittest.main()

