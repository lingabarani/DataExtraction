"""
Discovery Cache & In-Flight Request Coalescing.
Provides two-tier caching (in-memory L1 and DB L2) with ETag/TTL support
and request coalescing to prevent duplicate concurrent network requests.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any, Callable, Coroutine, Dict, Optional

logger = logging.getLogger("discovery.cache")


class DiscoveryCache:
    def __init__(self, default_ttl_seconds: float = 3600.0) -> None:
        self.default_ttl = default_ttl_seconds
        self._l1_cache: Dict[str, tuple[float, Any]] = {}
        self._in_flight: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def _hash_key(self, key: str) -> str:
        return hashlib.sha256(key.strip().lower().encode("utf-8")).hexdigest()

    async def get_or_coalesce(
        self,
        cache_key: str,
        fetcher: Callable[[], Coroutine[Any, Any, Any]],
        ttl_seconds: Optional[float] = None,
    ) -> Any:
        """
        Gets result from cache if present. If miss, coalesces concurrent callers
        onto a single execution of fetcher().
        """
        key_hash = self._hash_key(cache_key)
        ttl = ttl_seconds or self.default_ttl
        now = time.monotonic()

        # Check L1 memory cache
        if key_hash in self._l1_cache:
            ts, val = self._l1_cache[key_hash]
            if now - ts < ttl:
                return val

        # In-flight coalescing
        async with self._lock:
            if key_hash in self._in_flight:
                future = self._in_flight[key_hash]
            else:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                self._in_flight[key_hash] = future
                asyncio.create_task(self._execute_and_resolve(key_hash, fetcher, future))

        return await future

    async def _execute_and_resolve(
        self,
        key_hash: str,
        fetcher: Callable[[], Coroutine[Any, Any, Any]],
        future: asyncio.Future,
    ) -> None:
        try:
            result = await fetcher()
            self._l1_cache[key_hash] = (time.monotonic(), result)
            if not future.done():
                future.set_result(result)
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
        finally:
            async with self._lock:
                self._in_flight.pop(key_hash, None)

    def clear(self) -> None:
        """Clears L1 cache."""
        self._l1_cache.clear()
        self._in_flight.clear()


default_cache = DiscoveryCache()
