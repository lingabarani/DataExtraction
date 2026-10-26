#!/usr/bin/env python3
"""
Unit and Integration Test Suite for Phase 1: Security & Configuration Hardening.

Validates:
1. Configuration resolution and environment awareness (dev vs prod).
2. Fail-fast security gates for JWT secrets, admin credentials, and database passwords in production.
3. SEC EDGAR Fair Access User-Agent compliance and regex validation.
4. AWS Secrets Manager retrieval and memory caching mock.
5. Insecure secret detection and rejection.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure paths resolve properly in DataExtraction monorepo
_backend_dir = Path(__file__).resolve().parent
_project_root = _backend_dir.parents[2]
_packages = _project_root / "packages"

for _p in [
    _packages / "pipeline",
    _packages / "infrastructure",
    _packages / "scrapers",
    _packages / "scrapers" / "federal",
    _packages / "scrapers" / "open_map",
    _packages / "api",
    _packages / "api" / "routers",
    _project_root / "scripts" / "db",
    _project_root / "scripts" / "ops",
    _project_root,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from config_manager import ConfigManager, ConfigurationError, config_manager


class TestConfigManagerSecurity(unittest.TestCase):
    """Tests environment-aware configuration and security gate enforcement."""

    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_development_mode_allows_safe_defaults(self):
        """In development mode, safe default JWT secrets and admin passwords should be allowed."""
        os.environ["ENVIRONMENT"] = "development"
        os.environ.pop("JWT_SECRET", None)
        cfg = ConfigManager()

        self.assertFalse(cfg.is_production)
        self.assertEqual(cfg.get_jwt_secret(), "oneextraction-jwt-secret-change-in-prod")
        admin_creds = cfg.get_admin_credentials()
        self.assertEqual(admin_creds["email"], "admin@oneextraction.io")

    def test_production_mode_rejects_missing_jwt_secret(self):
        """In production, missing JWT_SECRET must raise ConfigurationError."""
        os.environ["ENVIRONMENT"] = "production"
        os.environ.pop("JWT_SECRET", None)
        cfg = ConfigManager()

        self.assertTrue(cfg.is_production)
        with self.assertRaises(ConfigurationError) as ctx:
            cfg.get_jwt_secret()
        self.assertIn("JWT_SECRET environment variable is missing", str(ctx.exception))

    def test_production_mode_rejects_insecure_default_jwt_secret(self):
        """In production, default 'oneextraction-jwt-secret-change-in-prod' must raise ConfigurationError."""
        os.environ["ENVIRONMENT"] = "production"
        os.environ["JWT_SECRET"] = "oneextraction-jwt-secret-change-in-prod"
        cfg = ConfigManager()

        with self.assertRaises(ConfigurationError) as ctx:
            cfg.get_jwt_secret()
        self.assertIn("Insecure default JWT_SECRET detected", str(ctx.exception))

    def test_production_mode_rejects_short_jwt_secret(self):
        """In production, JWT_SECRET shorter than 32 chars must be rejected."""
        os.environ["ENVIRONMENT"] = "production"
        os.environ["JWT_SECRET"] = "short-secret-123456"
        cfg = ConfigManager()

        with self.assertRaises(ConfigurationError) as ctx:
            cfg.get_jwt_secret()
        self.assertIn("must be at least 32 characters", str(ctx.exception))

    def test_production_mode_accepts_strong_jwt_secret(self):
        """In production, a 32+ character unique secret succeeds."""
        os.environ["ENVIRONMENT"] = "production"
        strong_secret = "c4d7e98a12b3f45e67890123456789abcdef0123456789abcdef01234567"
        os.environ["JWT_SECRET"] = strong_secret
        cfg = ConfigManager()

        self.assertEqual(cfg.get_jwt_secret(), strong_secret)

    def test_production_mode_rejects_default_admin_password(self):
        """In production, default admin password 'admin123' must be rejected."""
        os.environ["ENVIRONMENT"] = "production"
        os.environ["API_ADMIN_PASSWORD"] = "admin123"
        cfg = ConfigManager()

        with self.assertRaises(ConfigurationError) as ctx:
            cfg.get_admin_credentials()
        self.assertIn("Insecure default API_ADMIN_PASSWORD", str(ctx.exception))

    def test_production_mode_rejects_default_db_password(self):
        """In production, default database password '7903' must be rejected."""
        os.environ["ENVIRONMENT"] = "production"
        os.environ["DATABASE_TYPE"] = "postgresql"
        os.environ["DATABASE_PASSWORD"] = "7903"
        cfg = ConfigManager()

        with self.assertRaises(ConfigurationError) as ctx:
            cfg.get_database_config()
        self.assertIn("Insecure or default DATABASE_PASSWORD", str(ctx.exception))


class TestSECUserAgentCompliance(unittest.TestCase):
    """Tests SEC EDGAR Fair Access User-Agent compliance."""

    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_valid_sec_user_agents(self):
        """Compliant User-Agents with entity name and contact email must pass."""
        cfg = ConfigManager()
        valid_examples = [
            "Sample Company Name AdminContact@domain.com",
            "OneExtraction Research admin@oneextraction.com",
            "Acme Corp research-team@acme.org",
            "Data Extraction Engine <sec-contact@mycorp.io>",
        ]
        for ua in valid_examples:
            self.assertTrue(cfg.validate_sec_user_agent(ua), f"Expected valid for: {ua}")

    def test_invalid_sec_user_agents(self):
        """Generic, crawler, or email-less User-Agents must be rejected."""
        cfg = ConfigManager()
        invalid_examples = [
            "",
            "python-requests",
            "curl/7.68.0",
            "OneExtraction/1.0",
            "JustACompanyNameWithoutEmail",
            "admin@oneextraction.com",  # Missing company name
            "Mozilla/5.0",
        ]
        for ua in invalid_examples:
            self.assertFalse(cfg.validate_sec_user_agent(ua), f"Expected invalid for: {ua}")

    def test_production_sec_user_agent_requirement(self):
        """In production, missing or invalid SEC_USER_AGENT must raise ConfigurationError."""
        os.environ["ENVIRONMENT"] = "production"
        os.environ["SEC_USER_AGENT"] = "python-requests"
        cfg = ConfigManager()

        with self.assertRaises(ConfigurationError) as ctx:
            cfg.get_sec_user_agent()
        self.assertIn("Valid SEC_USER_AGENT is required in production", str(ctx.exception))

    def test_development_sec_user_agent_fallback(self):
        """In development, a compliant fallback is returned."""
        os.environ["ENVIRONMENT"] = "development"
        os.environ.pop("SEC_USER_AGENT", None)
        cfg = ConfigManager()

        ua = cfg.get_sec_user_agent()
        self.assertTrue(cfg.validate_sec_user_agent(ua))
        self.assertIn("@", ua)


class TestAWSSecretsManagerIntegration(unittest.TestCase):
    """Tests AWS Secrets Manager loading and fallback handling."""

    def setUp(self):
        self.original_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    @patch("boto3.client")
    def test_aws_secrets_manager_successful_fetch(self, mock_boto_client):
        """Mocked AWS Secrets Manager returns JSON dictionary and populates config."""
        mock_sm = MagicMock()
        mock_sm.get_secret_value.return_value = {
            "SecretString": '{"JWT_SECRET": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0", "API_ADMIN_PASSWORD": "super-secure-production-pass-2026!"}'
        }
        mock_boto_client.return_value = mock_sm

        os.environ["AWS_SECRETS_NAME"] = "oneextraction/prod-secrets"
        os.environ["ENVIRONMENT"] = "production"
        os.environ.pop("JWT_SECRET", None)

        cfg = ConfigManager()
        secret = cfg.get_jwt_secret()

        self.assertEqual(secret, "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0")
        admin_creds = cfg.get_admin_credentials()
        self.assertEqual(admin_creds["password"], "super-secure-production-pass-2026!")


if __name__ == "__main__":
    unittest.main()
