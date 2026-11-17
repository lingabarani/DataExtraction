"""
Async Token Bucket Rate Limiting for Discovery Engine.
Provides per-host and per-source concurrency and burst pacing.
Slow hosts never throttle unrelated hosts.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict
from urllib.parse import urlparse


class AsyncTokenBucket:
    """Async token bucket rate limiter with burst capability."""

    def __init__(self, rate_per_second: float = 2.0, capacity: float = 5.0) -> None:
        self.rate = rate_per_second
        self.capacity = capacity
        self.tokens = capacity
        self.last_updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Wait until enough tokens are available."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_updated
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_updated = now

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                needed = tokens - self.tokens
                wait_time = needed / self.rate

            await asyncio.sleep(min(wait_time, 1.0))

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Non-blocking token acquisition."""
        now = time.monotonic()
        elapsed = now - self.last_updated
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_updated = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


_host_buckets: Dict[str, AsyncTokenBucket] = {}
_bucket_lock = asyncio.Lock()


async def get_host_bucket(url: str, default_rate: float = 2.0) -> AsyncTokenBucket:
    """Returns the dedicated token bucket for a specific domain host."""
    parsed = urlparse(url)
    host = parsed.netloc.lower() or "default"

    async with _bucket_lock:
        if host not in _host_buckets:
            _host_buckets[host] = AsyncTokenBucket(rate_per_second=default_rate, capacity=default_rate * 2)
        return _host_buckets[host]
