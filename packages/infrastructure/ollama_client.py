"""
DataExtraction — Enterprise Async Ollama Client
================================================
Production-hardened asynchronous client for Ollama LLM integration (Llama 3.1 8B).

Features:
  1. Connection Pooling: Reuses HTTP/1.1 keep-alive connections via httpx.AsyncClient.
  2. Three-State Circuit Breaker: Automatically trips to OPEN after consecutive SLA
     timeouts or failures, protecting API workers from CPU starvation.
  3. Structured Output: Native integration with Ollama's grammar constraint (`format="json"`).
  4. Heartbeat Warmup: Prevents model weight RAM eviction with configurable keep-alive.
  5. Telemetry & Metrics: Integrated with structured logging and performance tracking.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("infrastructure.ollama")


class CircuitBreakerState:
    """State constants for the Ollama circuit breaker."""
    CLOSED = "CLOSED"      # Normal operation: all traffic routed to Ollama
    OPEN = "OPEN"          # Tripped: all traffic rejected instantly to avoid blocking
    HALF_OPEN = "HALF_OPEN"# Canary probe: single request tests service recovery


class OllamaClient:
    """
    Enterprise-grade asynchronous client for local or cluster-hosted Ollama LLM instances.
    Enforces strict timeouts, connection pooling, and circuit breaker protection.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._cfg = config or config_manager.get_ollama_config()
        self.base_url: str = self._cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self.model: str = self._cfg.get("model", "llama3.1:8b")
        self.timeout: float = float(self._cfg.get("timeout_seconds", 5.0))
        self.batch_timeout: float = float(self._cfg.get("batch_timeout_seconds", 30.0))
        self.keep_alive: str = self._cfg.get("keep_alive", "30m")
        self.enabled: bool = bool(self._cfg.get("enabled", True))

        # Circuit breaker settings
        self._state: str = CircuitBreakerState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._failure_threshold: int = int(self._cfg.get("circuit_breaker_threshold", 3))
        self._recovery_timeout: float = float(self._cfg.get("circuit_breaker_recovery_seconds", 60.0))
        self._last_state_change: float = time.time()
        self._last_error: Optional[str] = None
        self._last_latency_ms: float = 0.0

        # Shared client instance
        self._client: Optional[httpx.AsyncClient] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        """Returns or initializes the shared, connection-pooled httpx.AsyncClient."""
        if self._client is None or getattr(self._client, "is_closed", False) is True:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=2.0),
                limits=httpx.Limits(
                    max_keepalive_connections=20,
                    max_connections=50,
                    keepalive_expiry=30.0,
                ),
            )
        return self._client

    async def close(self) -> None:
        """Gracefully closes HTTP connection pool."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.debug("Closed Ollama HTTP client pool.")

    # ── Circuit Breaker Mechanics ─────────────────────────────────────────────

    @property
    def state(self) -> str:
        """Returns current circuit breaker state, handling automatic transitions."""
        if self._state == CircuitBreakerState.OPEN:
            elapsed = time.time() - self._last_state_change
            if elapsed >= self._recovery_timeout:
                self._state = CircuitBreakerState.HALF_OPEN
                self._last_state_change = time.time()
                logger.info(
                    "Ollama circuit breaker transitioned from OPEN to HALF_OPEN after %.1fs",
                    elapsed,
                )
        return self._state

    def is_available(self) -> bool:
        """Checks if Ollama service is enabled and circuit breaker allows requests."""
        if not self.enabled:
            return False
        current_state = self.state
        return current_state in (CircuitBreakerState.CLOSED, CircuitBreakerState.HALF_OPEN)

    def _record_success(self, duration_ms: float) -> None:
        """Records a successful request, resetting failure counters."""
        self._last_latency_ms = duration_ms
        if self._state == CircuitBreakerState.HALF_OPEN:
            logger.info("Ollama canary probe succeeded. Circuit breaker reset to CLOSED.")
            self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_state_change = time.time()
            self._last_error = None
        else:
            self._failure_count = 0
            self._success_count += 1

    def _record_failure(self, error: Exception) -> None:
        """Records a failed request or SLA timeout, advancing circuit breaker state."""
        self._last_error = str(error)
        self._failure_count += 1
        logger.warning(
            "Ollama call failed (failure #%d/%d): %s",
            self._failure_count,
            self._failure_threshold,
            error,
        )

        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.OPEN
            self._last_state_change = time.time()
            logger.error("Ollama canary probe failed. Circuit breaker tripped back to OPEN.")
        elif self._failure_count >= self._failure_threshold and self._state == CircuitBreakerState.CLOSED:
            self._state = CircuitBreakerState.OPEN
            self._last_state_change = time.time()
            logger.error(
                "Ollama circuit breaker TRIPPED to OPEN after %d consecutive failures. "
                "All LLM requests will fail fast for %.0fs.",
                self._failure_count,
                self._recovery_timeout,
            )

    # ── Operational Capabilities ──────────────────────────────────────────────

    async def health_check(self) -> Dict[str, Any]:
        """
        Probes the Ollama daemon for operational readiness, available models,
        and current circuit breaker status.
        """
        t0 = time.time()
        status_info: Dict[str, Any] = {
            "service": "ollama",
            "base_url": self.base_url,
            "configured_model": self.model,
            "circuit_breaker_state": self.state,
            "enabled": self.enabled,
            "last_error": self._last_error,
            "status": "degraded" if self.state == CircuitBreakerState.OPEN else "ready",
        }

        if not self.enabled:
            status_info["status"] = "disabled"
            return status_info

        try:
            client = await self.get_http_client()
            resp = await client.get("/api/tags", timeout=3.0)
            resp.raise_for_status()
            data = resp.json()
            models = [m.get("name") for m in data.get("models", [])]
            model_installed = any(self.model in m for m in models)

            latency_ms = (time.time() - t0) * 1000
            self._record_success(latency_ms)

            status_info.update({
                "status": "healthy" if model_installed else "model_missing",
                "installed_models": models,
                "model_ready": model_installed,
                "latency_ms": round(latency_ms, 2),
            })
            return status_info

        except Exception as exc:
            self._record_failure(exc)
            status_info.update({
                "status": "unreachable",
                "error": str(exc),
                "model_ready": False,
            })
            return status_info

    async def ping_warmup(self) -> bool:
        """
        Sends a 0-token warmup prompt with configured keep_alive to ensure the model
        remains loaded in memory without blocking during active work hours.
        """
        if not self.is_available():
            return False

        try:
            client = await self.get_http_client()
            resp = await client.post(
                "/api/generate",
                json={
                    "model": self.model,
                    "prompt": "",
                    "keep_alive": self.keep_alive,
                },
                timeout=5.0,
            )
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("Ollama warmup ping failed: %s", exc)
            return False

    async def generate_structured(
        self,
        prompt: str,
        system: Optional[str] = None,
        timeout: Optional[float] = None,
        temperature: float = 0.1,
    ) -> Optional[Dict[str, Any]]:
        """
        Executes a prompt against the Ollama model with strict JSON formatting.
        Guarantees structured output parsing or returns None on failure.

        Args:
            prompt: User-provided text prompt.
            system: Optional system instructions/schema guidelines.
            timeout: Optional SLA timeout override (seconds).
            temperature: Sampling temperature (default 0.1 for deterministic extraction).

        Returns:
            Parsed JSON dictionary, or None if the request failed or circuit breaker is open.
        """
        if not self.is_available():
            logger.debug("Ollama generation skipped: circuit breaker is %s", self.state)
            return None

        t0 = time.time()
        req_timeout = timeout or self.timeout
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": 256,
            },
        }
        if system:
            payload["system"] = system

        try:
            client = await self.get_http_client()
            resp = await client.post("/api/generate", json=payload, timeout=req_timeout)
            resp.raise_for_status()

            duration_ms = (time.time() - t0) * 1000
            data = resp.json()
            raw_response = data.get("response", "{}")

            parsed = json.loads(raw_response)
            if not isinstance(parsed, dict):
                logger.warning("Ollama response was valid JSON but not a dictionary: %s", raw_response)
                return None

            self._record_success(duration_ms)
            logger.info("Ollama structured inference succeeded in %.2fms", duration_ms)
            return parsed

        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            self._record_failure(exc)
            logger.warning("Ollama structured generation timed out after %.2fs", req_timeout)
            return None
        except json.JSONDecodeError as exc:
            self._record_failure(exc)
            logger.warning("Ollama returned invalid JSON: %s", exc)
            return None
        except Exception as exc:
            self._record_failure(exc)
            logger.warning("Ollama generation failed: %s", exc)
            return None

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.2,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """
        Executes multi-turn chat completion against the Ollama model.

        Args:
            messages: List of message objects e.g. [{"role": "user", "content": "..."}].
            temperature: Sampling temperature.
            timeout: Optional timeout override (seconds).

        Returns:
            Assistant response string, or None if unavailable.
        """
        if not self.is_available():
            return None

        t0 = time.time()
        req_timeout = timeout or self.batch_timeout
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
            },
        }

        try:
            client = await self.get_http_client()
            resp = await client.post("/api/chat", json=payload, timeout=req_timeout)
            resp.raise_for_status()

            duration_ms = (time.time() - t0) * 1000
            data = resp.json()
            message = data.get("message", {}).get("content", "")
            self._record_success(duration_ms)
            return message

        except Exception as exc:
            self._record_failure(exc)
            logger.warning("Ollama chat completion failed: %s", exc)
            return None

    def get_status(self) -> Dict[str, Any]:
        """Returns instantaneous runtime state and metrics."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "state": self.state,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_latency_ms": self._last_latency_ms,
            "last_error": self._last_error,
            "enabled": self.enabled,
        }


# Global singleton instance
ollama_client = OllamaClient()

__all__ = ["OllamaClient", "CircuitBreakerState", "ollama_client"]
