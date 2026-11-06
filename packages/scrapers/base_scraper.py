"""
DataExtraction — Base Scraper Framework
=======================================
Unified, production-grade base class for all distributed extraction engines.
Enforces:
  1. Rate Limiting & Politeness (Token bucket / configurable req/sec)
  2. Circuit Breaker Pattern (Trips on repeated 429 / 5xx / timeouts with cooldown)
  3. Compliant User-Agent Generation (SEC EDGAR Fair Access & sovereign standards)
  4. Structured Telemetry & Audit Metrics
  5. Exponential backoff and jittered retry loop
"""

import abc
import logging
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger("dataextraction.scrapers.base")


class CircuitBreakerOpenException(Exception):
    """Raised when request is attempted while the scraper's circuit breaker is OPEN."""
    pass


class BaseScraper(abc.ABC):
    """
    Abstract Base Class for statutory registries, web crawlers, and API extraction engines.
    """

    def __init__(
        self,
        name: str,
        rate_limit_per_second: float = 5.0,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_seconds: float = 60.0,
        default_timeout: float = 30.0,
        user_agent_contact: Optional[str] = None,
    ):
        self.name = name
        self.rate_limit = max(0.1, rate_limit_per_second)
        self.min_interval = 1.0 / self.rate_limit
        self.last_request_time = 0.0

        # Circuit breaker state
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.consecutive_failures = 0
        self.circuit_state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.circuit_opened_at = 0.0

        self.default_timeout = default_timeout
        self.contact = user_agent_contact or os.getenv("SCRAPER_USER_AGENT_EMAIL", "compliance@oneextraction.internal")

        # Session & metrics
        self.session = requests.Session()
        self.metrics = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "requests_throttled": 0,
            "circuit_trips": 0,
            "bytes_received": 0,
            "start_time": datetime.now(timezone.utc).isoformat(),
        }

    def get_user_agent(self) -> str:
        """
        Returns a compliant User-Agent string adhering to SEC EDGAR and general crawler ethics.
        """
        app_name = os.getenv("SCRAPER_APP_NAME", "DataExtractionPlatform/2.0")
        return f"{app_name} (Sovereign Registry Extractor; contact={self.contact})"

    def _check_circuit(self) -> None:
        """Evaluates whether the circuit breaker allows outbound requests."""
        if self.circuit_state == "OPEN":
            elapsed = time.time() - self.circuit_opened_at
            if elapsed >= self.circuit_cooldown_seconds:
                logger.info("[%s] Circuit breaker entering HALF_OPEN probe state after %.1fs", self.name, elapsed)
                self.circuit_state = "HALF_OPEN"
            else:
                remaining = self.circuit_cooldown_seconds - elapsed
                raise CircuitBreakerOpenException(
                    f"[{self.name}] Circuit is OPEN. Cooldown active for another {remaining:.1f}s"
                )

    def _record_success(self) -> None:
        """Registers a successful request and resets the failure tally."""
        self.metrics["requests_total"] += 1
        self.metrics["requests_success"] += 1
        self.consecutive_failures = 0
        if self.circuit_state == "HALF_OPEN":
            logger.info("[%s] Probe succeeded. Resetting circuit to CLOSED", self.name)
            self.circuit_state = "CLOSED"

    def _record_failure(self, error: Exception) -> None:
        """Registers a request failure and trips circuit if threshold exceeded."""
        self.metrics["requests_total"] += 1
        self.metrics["requests_failed"] += 1
        self.consecutive_failures += 1
        logger.warning(
            "[%s] Request failure (%d/%d): %s",
            self.name, self.consecutive_failures, self.circuit_failure_threshold, error
        )

        if self.consecutive_failures >= self.circuit_failure_threshold:
            self.circuit_state = "OPEN"
            self.circuit_opened_at = time.time()
            self.metrics["circuit_trips"] += 1
            logger.error(
                "[%s] Circuit breaker TRIPPED to OPEN for %.1fs after %d consecutive errors",
                self.name, self.circuit_cooldown_seconds, self.consecutive_failures
            )

    def _enforce_politeness(self) -> None:
        """Throttles execution to honor the configured rate limit."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.min_interval:
            sleep_duration = self.min_interval - elapsed
            self.metrics["requests_throttled"] += 1
            time.sleep(sleep_duration)
        self.last_request_time = time.time()

    def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        json_data: Optional[Any] = None,
        max_retries: int = 3,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        """
        Executes an HTTP request with rate-limiting, circuit breaking, and exponential backoff.
        """
        self._check_circuit()

        req_headers = {
            "User-Agent": self.get_user_agent(),
            "Accept": "*/*",
        }
        if headers:
            req_headers.update(headers)

        req_timeout = timeout or self.default_timeout
        attempt = 0

        while attempt < max_retries:
            attempt += 1
            self._enforce_politeness()
            try:
                resp = self.session.request(
                    method=method.upper(),
                    url=url,
                    headers=req_headers,
                    params=params,
                    data=data,
                    json=json_data,
                    timeout=req_timeout,
                )

                if resp.status_code in (429, 503, 504):
                    # Throttled / Server overload - retry with backoff
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else (2.0 ** attempt) + random.uniform(0.1, 0.5)
                    logger.warning(
                        "[%s] Received HTTP %d. Throttling for %.2fs before retry %d/%d",
                        self.name, resp.status_code, delay, attempt, max_retries
                    )
                    time.sleep(delay)
                    continue

                resp.raise_for_status()
                self._record_success()
                self.metrics["bytes_received"] += len(resp.content or b"")
                return resp

            except requests.exceptions.RequestException as exc:
                if attempt >= max_retries:
                    self._record_failure(exc)
                    raise
                backoff = (1.5 ** attempt) + random.uniform(0.1, 0.5)
                logger.debug("[%s] Request failed (%s). Retrying in %.2fs...", self.name, exc, backoff)
                time.sleep(backoff)

        raise RuntimeError(f"[{self.name}] Max retries exceeded fetching {url}")

    def get_metrics(self) -> Dict[str, Any]:
        """Returns runtime performance and audit telemetry."""
        return {
            **self.metrics,
            "circuit_state": self.circuit_state,
            "consecutive_failures": self.consecutive_failures,
            "rate_limit_per_second": self.rate_limit,
        }

    @abc.abstractmethod
    def scrape(self, limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
        """Core extraction workflow to be implemented by specific scrapers."""
        pass

