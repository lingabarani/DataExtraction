"""
Shared HTTP layer for the Discovery Engine.

* One pooled `httpx.AsyncClient` per (source, event loop) so tests, Temporal workers and the API never share a
  client across loops. HTTP/2 is used when the `h2` package is installed. TLS verification is always on.
* `paced_request` waits on a per-source async token bucket whose rate comes from config/rate_limits.yaml.
* `cached_json` adds an in-process TTL cache with in-flight coalescing (identical concurrent calls = one fetch).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import httpx
import yaml

from packages.discovery.cache import default_cache
from packages.discovery.ratelimit import AsyncTokenBucket

logger = logging.getLogger("discovery.http")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
BOT_USER_AGENT = "DataExtractionBot/1.0 (+public business data research)"

_CLIENTS: Dict[Tuple[str, int], httpx.AsyncClient] = {}
_TRANSPORTS: Dict[str, httpx.AsyncBaseTransport] = {}   # test hook: per-source transport (mock servers)
_BUCKETS: Dict[Tuple[str, int], AsyncTokenBucket] = {}
_RATE_CFG: Optional[Dict[str, Any]] = None
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "rate_limits.yaml"


def _loop_id() -> int:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return 0


def source_rate_config(source_name: str) -> Dict[str, Any]:
    """Rate limit block for `source_name` from config/rate_limits.yaml (empty dict when absent)."""
    global _RATE_CFG
    if _RATE_CFG is None:
        try:
            _RATE_CFG = (yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}).get("rate_limits", {}) or {}
        except Exception as exc:
            logger.warning("Could not read rate limits config: %s", exc)
            _RATE_CFG = {}
    return dict(_RATE_CFG.get(source_name, {}) or {})


def set_transport_override(source_name: str, transport: Optional[httpx.AsyncBaseTransport]) -> None:
    """Test hook: route a source through `transport` (e.g. httpx.MockTransport). Pass None to remove."""
    if transport is None:
        _TRANSPORTS.pop(source_name, None)
    else:
        _TRANSPORTS[source_name] = transport
    for key in [k for k in _CLIENTS if k[0] == source_name]:
        _CLIENTS.pop(key, None)


def get_http_client(
    source_name: str,
    timeout: float = 10.0,
    max_connections: int = 20,
    max_keepalive_connections: int = 10,
    user_agent: Optional[str] = None,
) -> httpx.AsyncClient:
    """Returns or creates the pooled client for `source_name` on the running event loop."""
    key = (source_name, _loop_id())
    client = _CLIENTS.get(key)
    if client is None or client.is_closed:
        http2_enabled = False
        try:
            import h2  # noqa: F401
            http2_enabled = True
        except ImportError:
            pass
        client = httpx.AsyncClient(
            headers={
                "User-Agent": user_agent or DEFAULT_USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, text/html, */*",
            },
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_keepalive_connections,
                                keepalive_expiry=30.0),
            timeout=httpx.Timeout(timeout, connect=5.0),
            http2=http2_enabled and source_name not in _TRANSPORTS,
            follow_redirects=True,
            verify=True,
            transport=_TRANSPORTS.get(source_name),
        )
        _CLIENTS[key] = client
    return client


def get_bucket(source_name: str) -> AsyncTokenBucket:
    key = (source_name, _loop_id())
    bucket = _BUCKETS.get(key)
    if bucket is None:
        cfg = source_rate_config(source_name)
        rate = float(cfg.get("requests_per_second", 2.0))
        burst = float(cfg.get("burst", max(1.0, rate * 2)))
        bucket = AsyncTokenBucket(rate_per_second=rate, capacity=burst)
        _BUCKETS[key] = bucket
    return bucket


async def paced_request(source_name: str, method: str, url: str, *, timeout: float = 10.0, **kwargs: Any) -> httpx.Response:
    """Rate-limited request through the pooled client for `source_name`."""
    await get_bucket(source_name).acquire()
    client = get_http_client(source_name, timeout=timeout)
    return await client.request(method, url, timeout=timeout, **kwargs)


async def cached_json(key: str, fetcher: Callable[[], Awaitable[Any]], ttl_seconds: float) -> Any:
    """TTL cache with in-flight coalescing. Exceptions are not cached."""
    return await default_cache.get_or_coalesce(key, fetcher, ttl_seconds=ttl_seconds)


async def close_all_clients() -> None:
    """Closes all cached HTTP clients cleanly."""
    for name, client in list(_CLIENTS.items()):
        try:
            if not client.is_closed:
                await client.aclose()
        except Exception as exc:
            logger.debug("Error closing client %s: %s", name, exc)
    _CLIENTS.clear()
    _BUCKETS.clear()
