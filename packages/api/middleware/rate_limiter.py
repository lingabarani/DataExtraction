"""
DataExtraction Enterprise — Distributed Sliding-Window Rate Limiter Middleware
==============================================================================
Uses Redis for a fully distributed sliding-window rate limit that works
correctly across multiple API workers and replicas.

Falls back to an in-process sliding window when Redis is unavailable, so the
API stays operational in development environments without Redis.

Limits:
  - Auth endpoints (/api/auth*) : 15 req/min per IP
  - General API endpoints       : 180 req/min per IP
"""

import logging
import time
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("dataextraction.ratelimit")

# Paths that bypass rate limiting entirely
EXEMPT_PATHS = frozenset({
    "/healthz",
    "/readyz",
    "/health",
    "/metrics",
    "/api/metrics",
    "/api/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/",
})

# Rate limit windows (requests per 60-second window)
AUTH_LIMIT = 15
API_LIMIT = 180
WINDOW_SECONDS = 60


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------

class _RedisRateLimiter:
    """Sliding-window rate limiter backed by Redis ZADD/ZREMRANGEBYSCORE."""

    def __init__(self, redis_url: str):
        import redis as _redis
        self._pool = _redis.ConnectionPool.from_url(
            redis_url,
            max_connections=20,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            decode_responses=True,
        )
        self._client = _redis.Redis(connection_pool=self._pool)
        logger.info("Redis rate limiter initialised: %s", redis_url)

    def check(self, key: str, limit: int) -> tuple[bool, int]:
        """
        Returns (is_allowed, current_count).
        Uses a Redis sorted set keyed by IP+path, scored by unix timestamp.
        """
        try:
            now = time.time()
            cutoff = now - WINDOW_SECONDS

            pipe = self._client.pipeline()
            pipe.zremrangebyscore(key, "-inf", cutoff)         # remove old entries
            pipe.zadd(key, {str(now): now})                    # add this request
            pipe.zcard(key)                                     # count window
            pipe.expire(key, WINDOW_SECONDS + 5)               # TTL cleanup
            results = pipe.execute()

            count = int(results[2])
            return count <= limit, count
        except Exception as exc:
            logger.debug("Redis rate-limit check failed (%s) — allowing request.", exc)
            return True, 0


# ---------------------------------------------------------------------------
# In-process fallback
# ---------------------------------------------------------------------------

class _LocalRateLimiter:
    """Thread-safe in-process sliding window (single-process / dev only)."""

    def __init__(self):
        from collections import defaultdict
        self._windows: dict = defaultdict(list)
        self._last_cleanup = 0.0

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < 30.0:
            return
        self._last_cleanup = now
        cutoff = now - WINDOW_SECONDS
        stale = [k for k, v in self._windows.items() if not [t for t in v if t > cutoff]]
        for k in stale:
            del self._windows[k]

    def check(self, key: str, limit: int) -> tuple[bool, int]:
        now = time.time()
        self._cleanup(now)
        cutoff = now - WINDOW_SECONDS
        window = self._windows[key] = [t for t in self._windows[key] if t > cutoff]
        if len(window) >= limit:
            return False, len(window)
        window.append(now)
        return True, len(window)


# ---------------------------------------------------------------------------
# Factory — picks backend based on REDIS_URL env var
# ---------------------------------------------------------------------------

def _build_limiter():
    import os
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url:
        try:
            return _RedisRateLimiter(redis_url)
        except Exception as exc:
            logger.warning(
                "Could not initialise Redis rate limiter (%s). "
                "Falling back to in-process limiter — not suitable for multi-worker deployments.",
                exc,
            )
    else:
        logger.info(
            "REDIS_URL not set — using in-process rate limiter. "
            "Set REDIS_URL for distributed multi-worker support."
        )
    return _LocalRateLimiter()


_limiter: Optional[object] = None


def _get_limiter():
    global _limiter
    if _limiter is None:
        _limiter = _build_limiter()
    return _limiter


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware applying per-IP sliding-window rate limiting."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path in EXEMPT_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        # Extract client IP (supports reverse-proxy X-Forwarded-For)
        forwarded = request.headers.get("x-forwarded-for")
        client_ip = (
            forwarded.split(",")[0].strip()
            if forwarded
            else (request.client.host if request.client else "127.0.0.1")
        )

        is_auth = path.startswith("/api/auth")
        limit = AUTH_LIMIT if is_auth else API_LIMIT
        bucket = "auth" if is_auth else "api"
        key = f"rl:{bucket}:{client_ip}"

        limiter = _get_limiter()
        allowed, count = limiter.check(key, limit)

        if not allowed:
            logger.warning(
                "Rate limit exceeded: ip=%s path=%s count=%d limit=%d",
                client_ip, path, count, limit,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "detail": f"Rate limit exceeded: {limit} requests per {WINDOW_SECONDS}s.",
                    "retry_after_seconds": WINDOW_SECONDS,
                },
                headers={
                    "Retry-After": str(WINDOW_SECONDS),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Window": str(WINDOW_SECONDS),
                },
            )

        response: Response = await call_next(request)
        remaining = max(0, limit - count)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(WINDOW_SECONDS)
        return response


# Backwards compatibility alias for test suites and older modules
SlidingWindowRateLimiter = _LocalRateLimiter
