"""
DataExtraction — Unit Test Suite: Ollama LLaMA 3.1:8B Client & Circuit Breaker
==============================================================================
Validates:
  1. OllamaClient configuration resolution from ConfigManager.
  2. Health check probe and model readiness detection.
  3. Structured JSON generation via Ollama format="json".
  4. Three-state circuit breaker mechanics (CLOSED -> OPEN -> HALF_OPEN -> CLOSED).
  5. Timeout SLA enforcement and error recording.
  6. Resilience against malformed JSON or HTTP errors.
"""

import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

import httpx

from packages.infrastructure.ollama_client import (
    CircuitBreakerState,
    OllamaClient,
)


class TestOllamaClient(unittest.IsolatedAsyncioTestCase):
    """Test suite for asynchronous OllamaClient and circuit breaker."""

    async def asyncSetUp(self):
        self.custom_config = {
            "base_url": "http://mock-ollama:11434",
            "model": "llama3.1:8b",
            "timeout_seconds": 1.0,
            "batch_timeout_seconds": 5.0,
            "keep_alive": "15m",
            "circuit_breaker_threshold": 3,
            "circuit_breaker_recovery_seconds": 0.5,
            "enabled": True,
        }
        self.client = OllamaClient(config=self.custom_config)

    async def asyncTearDown(self):
        await self.client.close()

    def test_initial_state_and_config(self):
        """Verifies initialization and closed circuit breaker."""
        self.assertEqual(self.client.base_url, "http://mock-ollama:11434")
        self.assertEqual(self.client.model, "llama3.1:8b")
        self.assertEqual(self.client.state, CircuitBreakerState.CLOSED)
        self.assertTrue(self.client.is_available())

    async def test_health_check_healthy(self):
        """Verifies health check when Ollama reports model is installed."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "llama3.1:8b", "size": 4920753328}]
        }

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get.return_value = mock_resp
        self.client._client = mock_http

        res = await self.client.health_check()
        self.assertEqual(res["status"], "healthy")
        self.assertTrue(res["model_ready"])
        self.assertEqual(self.client.state, CircuitBreakerState.CLOSED)

    async def test_health_check_model_missing(self):
        """Verifies health check when target model is not in daemon catalog."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "mistral:latest"}]
        }

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.get.return_value = mock_resp
        self.client._client = mock_http

        res = await self.client.health_check()
        self.assertEqual(res["status"], "model_missing")
        self.assertFalse(res["model_ready"])

    async def test_generate_structured_success(self):
        """Verifies structured generation successfully parses JSON output."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "response": json.dumps({
                "table": "us_leads",
                "filters": {"seniority": "C_SUITE", "industry": "Healthcare"},
                "explanation": "Filtering healthcare C-suite",
                "confidence": 95,
            })
        }

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.post.return_value = mock_resp
        self.client._client = mock_http

        res = await self.client.generate_structured(
            prompt="Find healthcare CEOs",
            system="Extract JSON",
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.get("table"), "us_leads")
        self.assertEqual(res.get("filters", {}).get("seniority"), "C_SUITE")
        self.assertEqual(self.client.state, CircuitBreakerState.CLOSED)

    async def test_circuit_breaker_trips_to_open_after_consecutive_failures(self):
        """Verifies circuit breaker trips to OPEN after 3 consecutive failures."""
        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.post.side_effect = httpx.TimeoutException("Connection timed out")
        self.client._client = mock_http

        # Failure 1
        res1 = await self.client.generate_structured("query 1")
        self.assertIsNone(res1)
        self.assertEqual(self.client.state, CircuitBreakerState.CLOSED)

        # Failure 2
        res2 = await self.client.generate_structured("query 2")
        self.assertIsNone(res2)
        self.assertEqual(self.client.state, CircuitBreakerState.CLOSED)

        # Failure 3 -> Trips to OPEN
        res3 = await self.client.generate_structured("query 3")
        self.assertIsNone(res3)
        self.assertEqual(self.client.state, CircuitBreakerState.OPEN)
        self.assertFalse(self.client.is_available())

        # Attempt 4 when OPEN should fail fast without calling HTTP post
        mock_http.post.reset_mock()
        res4 = await self.client.generate_structured("query 4")
        self.assertIsNone(res4)
        mock_http.post.assert_not_called()

    async def test_circuit_breaker_recovers_via_half_open(self):
        """Verifies circuit transitions to HALF_OPEN after recovery window and resets to CLOSED."""
        # 1. Force state to OPEN
        self.client._state = CircuitBreakerState.OPEN
        self.client._last_state_change = time.time() - 1.0  # past recovery timeout (0.5s)

        # State should automatically transition to HALF_OPEN
        self.assertEqual(self.client.state, CircuitBreakerState.HALF_OPEN)
        self.assertTrue(self.client.is_available())

        # 2. Canary probe succeeds
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": json.dumps({"status": "ok"})}
        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.post.return_value = mock_resp
        self.client._client = mock_http

        res = await self.client.generate_structured("probe query")
        self.assertIsNotNone(res)
        self.assertEqual(self.client.state, CircuitBreakerState.CLOSED)
        self.assertEqual(self.client._failure_count, 0)

    async def test_malformed_json_response_handling(self):
        """Verifies that non-JSON string from Ollama is safely caught without crashing."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "This is plain text, not JSON"}

        mock_http = AsyncMock()
        mock_http.is_closed = False
        mock_http.post.return_value = mock_resp
        self.client._client = mock_http

        res = await self.client.generate_structured("query")
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
