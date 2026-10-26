"""
Enterprise Circuit Breaker & Endpoint Rotator for Overpass API Mirrored Pools.

Prevents looping across failing or overloaded endpoints. Rotates dynamically
between healthy global mirrors and enforces cooldown periods when 504, 502,
or 429 errors are detected on any specific server.
"""

import time
import random
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("OSMCircuitBreaker")


@dataclass
class EndpointHealth:
    url: str
    is_healthy: bool = True
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_failure_time: float = 0.0
    cooldown_until: float = 0.0
    last_status_code: Optional[int] = None
    last_error_message: Optional[str] = None


class EndpointCircuitBreaker:
    """
    Manages a pool of Overpass API mirrors with circuit breaker protection.
    """

    def __init__(
        self,
        endpoints: List[str],
        failure_threshold: int = 2,
        cooldown_sec: float = 120.0,
    ):
        if not endpoints:
            raise ValueError("Endpoint pool cannot be empty")
        
        self.endpoints = list(endpoints)
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self._current_index = 0
        self.registry: Dict[str, EndpointHealth] = {
            url: EndpointHealth(url=url) for url in self.endpoints
        }

    def get_active_endpoint(self) -> str:
        """
        Returns the best healthy endpoint from the pool.
        If all endpoints are currently in cooldown, falls back to the one whose
        cooldown expires soonest.
        """
        now = time.time()
        
        # Check if any in-cooldown endpoint has recovered
        for health in self.registry.values():
            if not health.is_healthy and now >= health.cooldown_until:
                health.is_healthy = True
                health.consecutive_failures = 0
                logger.info(f"[CIRCUIT BREAKER] Endpoint {health.url} cooldown expired. Marked HEALTHY.")

        # Try healthy endpoints starting from current index
        total = len(self.endpoints)
        for offset in range(total):
            idx = (self._current_index + offset) % total
            candidate = self.endpoints[idx]
            if self.registry[candidate].is_healthy:
                self._current_index = idx
                return candidate

        # All endpoints in cooldown: pick the one closest to expiry
        best_candidate = min(
            self.registry.values(),
            key=lambda h: h.cooldown_until
        )
        logger.warning(
            f"[CIRCUIT BREAKER] All {total} endpoints in cooldown! "
            f"Falling back to earliest recovering endpoint: {best_candidate.url} "
            f"(cooldown ends in {max(0.0, best_candidate.cooldown_until - now):.1f}s)"
        )
        return best_candidate.url

    def rotate_endpoint(self) -> str:
        """Advances current index and returns next healthy endpoint."""
        self._current_index = (self._current_index + 1) % len(self.endpoints)
        return self.get_active_endpoint()

    def record_success(self, url: str) -> None:
        """Records a successful request, resetting failure counters."""
        if url in self.registry:
            h = self.registry[url]
            h.is_healthy = True
            h.consecutive_failures = 0
            h.total_successes += 1
            h.last_status_code = 200

    def record_failure(
        self,
        url: str,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None
    ) -> Tuple[bool, float]:
        """
        Records an endpoint failure. Trips the circuit breaker if threshold reached.
        Returns (tripped_circuit, cooldown_sec).
        """
        if url not in self.registry:
            self.registry[url] = EndpointHealth(url=url)
            self.endpoints.append(url)

        h = self.registry[url]
        h.consecutive_failures += 1
        h.total_failures += 1
        h.last_failure_time = time.time()
        h.last_status_code = status_code
        h.last_error_message = error_message

        # Heavy server overload (504, 502, 503) or rate limit (429) trips immediately
        immediate_trip = status_code in (429, 502, 503, 504)
        
        if immediate_trip or h.consecutive_failures >= self.failure_threshold:
            h.is_healthy = False
            # Dynamic cooldown: longer cooldown if multiple failures
            cooldown = self.cooldown_sec * min(3.0, 1.0 + (h.consecutive_failures * 0.5))
            h.cooldown_until = time.time() + cooldown
            logger.warning(
                f"[CIRCUIT BREAKER] TRIPPED for {url}! "
                f"Status={status_code}, Failures={h.consecutive_failures}. "
                f"Isolated for {cooldown:.1f}s."
            )
            return True, cooldown

        return False, 0.0

    @staticmethod
    def calculate_jittered_backoff(attempt: int, base_backoff: float = 1.5, max_delay: float = 45.0) -> float:
        """Calculates exponential backoff with full randomized jitter."""
        exponential = min(max_delay, (base_backoff ** attempt) * 2.0)
        # Full jitter: random uniform between 0.5 * exp and 1.0 * exp
        jittered = random.uniform(exponential * 0.5, exponential)
        return round(max(2.0, min(max_delay, jittered)), 2)
