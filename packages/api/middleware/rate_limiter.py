"""
DataExtraction Enterprise — Production IP Sliding-Window Rate Limiter Middleware
Protects auth routes from credential stuffing and general APIs from volumetric denial-of-service.
"""

import time
import logging
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("dataextraction.ratelimit")

# Endpoints exempt from rate limiting
EXEMPT_PATHS = {
    "/healthz",
    "/readyz",
    "/metrics",
    "/api/metrics",
    "/api/health",
    "/api/docs",
    "/api/redoc",
    "/api/openapi.json",
    "/",
}


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self):
        # ip -> list of unix timestamps
        self._auth_windows: Dict[str, List[float]] = defaultdict(list)
        self._api_windows: Dict[str, List[float]] = defaultdict(list)
        self._last_cleanup = time.time()

    def _cleanup_stale(self, now: float) -> None:
        """Evicts expired bucket entries older than 60 seconds."""
        if now - self._last_cleanup < 60.0:
            return
        self._last_cleanup = now
        cutoff = now - 60.0
        for ip in list(self._auth_windows.keys()):
            self._auth_windows[ip] = [t for t in self._auth_windows[ip] if t > cutoff]
            if not self._auth_windows[ip]:
                self._auth_windows.pop(ip, None)
        for ip in list(self._api_windows.keys()):
            self._api_windows[ip] = [t for t in self._api_windows[ip] if t > cutoff]
            if not self._api_windows[ip]:
                self._api_windows.pop(ip, None)

    def check_rate_limit(self, ip: str, path: str) -> Tuple[bool, int, int]:
        """
        Validates request against sliding window limits.
        Returns: (is_allowed, current_count, limit)
        """
        now = time.time()
        self._cleanup_stale(now)
        cutoff = now - 60.0

        if path.startswith("/api/auth"):
            limit = 15  # 15 requests per minute for auth
            window = self._auth_windows[ip] = [t for t in self._auth_windows[ip] if t > cutoff]
        else:
            limit = 180  # 180 requests per minute for general endpoints
            window = self._api_windows[ip] = [t for t in self._api_windows[ip] if t > cutoff]

        if len(window) >= limit:
            return False, len(window), limit

        window.append(now)
        return True, len(window), limit


limiter = SlidingWindowRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware applying sliding-window rate limiting per client IP."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in EXEMPT_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        # Extract client IP (handling reverse proxy X-Forwarded-For)
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "127.0.0.1"

        allowed, count, limit = limiter.check_rate_limit(client_ip, path)
        if not allowed:
            logger.warning("Rate limit exceeded for IP %s on %s (%d/%d req/min)",
                           client_ip, path, count, limit)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "detail": f"Rate limit exceeded: maximum {limit} requests per minute.",
                    "retry_after_seconds": 60,
                },
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response: Response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        return response

