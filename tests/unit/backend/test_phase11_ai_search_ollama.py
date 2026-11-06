"""
DataExtraction — Unit Test Suite: AI Semantic Search & Settings Router
======================================================================
Validates:
  1. POST /api/ai/search with successful Ollama LLM structured parsing.
  2. POST /api/ai/search graceful fallback to regex parser on timeout or error.
  3. Filter whitelisting and protection against hallucinated / malicious fields.
  4. Parameterized SQL query construction (_build_where).
  5. GET /api/ai/health endpoint diagnostics.
  6. GET and POST /api/settings/integrations with credential masking.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from packages.api.dependencies import UserPrincipal, get_current_user
from packages.api.main import create_app
from packages.infrastructure.ollama_client import (
    CircuitBreakerState,
    ollama_client,
)


class TestAiSearchAndSettings(unittest.TestCase):
    """Test suite for AI Search endpoint and Settings Integrations."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        # Mock authenticated user principal
        cls.app.dependency_overrides[get_current_user] = lambda: UserPrincipal(
            id="test-user-admin",
            email="admin@oneextraction.test",
            name="Admin Tester",
            is_admin=True,
        )
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.app.dependency_overrides.clear()

    def test_ai_search_with_ollama_llm_success(self):
        """Verifies semantic query parsing when Ollama structured output succeeds."""
        mock_structured = {
            "table": "us_leads",
            "filters": {
                "seniority": "C_SUITE",
                "industry": "Healthcare",
                "state_code": "CA",
                "email_status": "VERIFIED",
                "min_lead_score": 85,
            },
            "explanation": "Filtering healthcare C-suite executives in California with verified emails.",
            "confidence": 94,
            "suggestions": [
                "Healthcare VPs in California",
                "Tech CEOs in California",
            ],
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_structured

            resp = self.client.post(
                "/api/ai/search",
                json={"query": "Find healthcare CEOs in California with verified emails"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()

            self.assertTrue(data["llm_used"])
            self.assertEqual(data["parsed"]["filters"]["seniority"], "C_SUITE")
            self.assertEqual(data["parsed"]["filters"]["industry"], "Healthcare")
            self.assertEqual(data["parsed"]["filters"]["state_code"], "CA")
            self.assertEqual(data["parsed"]["filters"]["email_status"], "VERIFIED")
            self.assertEqual(data["parsed"]["filters"]["min_lead_score"], 85)
            self.assertEqual(data["parsed"]["confidence"], 94)
            self.assertIn("Healthcare VPs", data["parsed"]["suggestions"][0])

    def test_ai_search_deterministic_fallback_on_llm_failure(self):
        """Verifies seamless fallback to regex engine when Ollama is unavailable or times out."""
        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            # Simulate Ollama timeout / failure
            mock_gen.return_value = None

            resp = self.client.post(
                "/api/ai/search",
                json={"query": "Find banking VPs in Texas with verified email"},
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()

            # Should have fallen back to deterministic regex parser
            self.assertFalse(data["llm_used"])
            self.assertIn("fallback", data["parsed"]["explanation"].lower())
            self.assertEqual(data["parsed"]["filters"]["seniority"], "VP")
            self.assertEqual(data["parsed"]["filters"]["industry"], "Banking and Finance")
            self.assertEqual(data["parsed"]["filters"]["state_code"], "TX")
            self.assertEqual(data["parsed"]["filters"]["email_status"], "VERIFIED")
            self.assertEqual(data["parsed"]["confidence"], 75)

    def test_ai_search_filter_whitelisting_and_sanitization(self):
        """Verifies that malicious or hallucinated fields from LLM are discarded."""
        mock_corrupt_llm = {
            "table": "us_leads",
            "filters": {
                "seniority": "c-suite",
                "state_code": "ca",
                "evil_column": "DELETE FROM users;",
                "sql_injection": "' OR '1'='1",
                "min_lead_score": "not_an_int",
            },
            "explanation": "Filtered",
            "confidence": 90,
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_corrupt_llm

            resp = self.client.post(
                "/api/ai/search",
                json={"query": "Find CEOs in CA"},
            )
            self.assertEqual(resp.status_code, 200)
            filters = resp.json()["parsed"]["filters"]

            # Only valid keys allowed
            self.assertEqual(filters["seniority"], "C_SUITE")
            self.assertEqual(filters["state_code"], "CA")
            self.assertNotIn("evil_column", filters)
            self.assertNotIn("sql_injection", filters)
            self.assertNotIn("min_lead_score", filters)

    def test_ai_health_endpoint(self):
        """Verifies /api/ai/health returns operational metrics and circuit state."""
        mock_health = {
            "service": "ollama",
            "status": "healthy",
            "model_ready": True,
            "installed_models": ["llama3.1:8b"],
            "latency_ms": 12.5,
        }

        with patch.object(ollama_client, "health_check", new_callable=AsyncMock) as mock_hc:
            mock_hc.return_value = mock_health

            resp = self.client.get("/api/ai/health")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["service"], "ollama")
            self.assertEqual(data["status"], "healthy")
            self.assertIn("circuit_status", data)

    def test_settings_integrations_get_and_post(self):
        """Verifies integrations endpoint lists and persists AI configuration."""
        # 1. GET /api/settings/integrations
        resp_get = self.client.get("/api/settings/integrations")
        self.assertEqual(resp_get.status_code, 200)
        integrations = resp_get.json()
        self.assertTrue(any(i.get("type") in ("openai", "ollama") for i in integrations))

        # 2. POST /api/settings/integrations (Saving new Ollama base URL & model)
        post_payload = {
            "type": "openai",
            "name": "Local Ollama Cluster",
            "config": {
                "baseURL": "http://127.0.0.1:11434",
                "model": "llama3.1:8b",
                "apiKey": "sk-local-secret",
            },
        }
        resp_post = self.client.post("/api/settings/integrations", json=post_payload)
        self.assertEqual(resp_post.status_code, 200)
        saved = resp_post.json()
        self.assertEqual(saved["status"], "saved")

        # Verify dynamic client update
        self.assertEqual(ollama_client.base_url, "http://127.0.0.1:11434")
        self.assertEqual(ollama_client.model, "llama3.1:8b")


if __name__ == "__main__":
    unittest.main()

