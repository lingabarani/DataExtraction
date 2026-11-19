"""
Async HTTP client for LinkedIn public pages and optional authenticated Voyager endpoints.
Implements:
  - Default public-only policy using httpx (HTTP/2)
  - Per-host async token bucket pacing with jitter
  - Circuit breaker tripping on 999 / 429 responses
  - Explicit error classification (Blocked, RateLimited, AuthExpired, Transient)
  - Optional curl_cffi Chrome impersonation (lazy-loaded, wrapped in asyncio.to_thread)
    gated by LINKEDIN_AUTH_ENABLED=true and credentials from Key Vault
"""

import asyncio
from collections import deque
import json
import logging
import os
import random
import time
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse
import httpx

from packages.infrastructure.key_vault import get_secrets_manager

logger = logging.getLogger("dataextraction.scrapers.linkedin")


class LinkedInScraperError(Exception):
    """Base exception for LinkedIn scraper errors."""


class Blocked(LinkedInScraperError):
    """LinkedIn anti-bot blocking (HTTP 999)."""


class RateLimited(LinkedInScraperError):
    """LinkedIn rate limiting (HTTP 429)."""


class AuthExpired(LinkedInScraperError):
    """LinkedIn authentication expired, unauthorized, or authwall redirect (401/403/redirect)."""


class Transient(LinkedInScraperError):
    """Transient network error, timeout, or server error (5xx)."""


class AsyncTokenBucket:
    """Async token bucket for per-host rate limiting."""

    def __init__(self, rate_per_second: float = 0.5, burst_capacity: int = 2):
        self.rate = rate_per_second
        self.capacity = burst_capacity
        self.tokens = float(burst_capacity)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(float(self.capacity), self.tokens + elapsed * self.rate)

            if self.tokens < 1.0:
                sleep_needed = (1.0 - self.tokens) / self.rate
                # Add slight random jitter (0.1 to 0.4s)
                sleep_needed += random.uniform(0.1, 0.4)
                await asyncio.sleep(sleep_needed)
                self.last_update = time.monotonic()
                self.tokens = 0.0
            else:
                self.tokens -= 1.0


class LinkedInHttpClient:
    """Async HTTP client for LinkedIn operations."""

    def __init__(
        self,
        rate_per_second: float = 0.33,  # ~1 req per 3s default
        breaker_window: int = 20,
        breaker_threshold: float = 0.25,
        max_attempts: int = 3,
        timeout_seconds: float = 20.0,
    ):
        self.rate_per_second = rate_per_second
        self.breaker_window = breaker_window
        self.breaker_threshold = breaker_threshold
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds

        self._token_buckets: Dict[str, AsyncTokenBucket] = {}
        self._status_window: deque[int] = deque(maxlen=breaker_window)
        self._client: Optional[httpx.AsyncClient] = None

    def _get_bucket(self, host: str) -> AsyncTokenBucket:
        if host not in self._token_buckets:
            self._token_buckets[host] = AsyncTokenBucket(
                rate_per_second=self.rate_per_second,
                burst_capacity=2,
            )
        return self._token_buckets[host]

    def _record_status(self, status: int) -> None:
        self._status_window.append(status)

    def is_breaker_tripped(self) -> bool:
        """Returns True if circuit breaker has observed too many blocks (999 or 429)."""
        if not self._status_window:
            return False
        blocked_count = sum(1 for s in self._status_window if s in (999, 429))
        ratio = blocked_count / len(self._status_window)
        return ratio >= self.breaker_threshold

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/128.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
            }
            try:
                import h2  # noqa: F401
                use_http2 = True
            except ImportError:
                use_http2 = False
            self._client = httpx.AsyncClient(
                http2=use_http2,
                headers=headers,
                timeout=self.timeout_seconds,
                follow_redirects=False,
            )
        return self._client

    async def get_public_page(self, url: str) -> str:
        """Fetch a public LinkedIn profile or company page politely with token-bucket pacing."""
        if self.is_breaker_tripped():
            raise Blocked("LinkedIn circuit breaker tripped: excessive 999 or 429 responses")

        parsed = urlparse(url)
        host = parsed.netloc or "www.linkedin.com"
        bucket = self._get_bucket(host)

        client = await self._get_client()

        for attempt in range(1, self.max_attempts + 1):
            await bucket.acquire()
            try:
                resp = await client.get(url)
                status = resp.status_code
                self._record_status(status)

                if status == 200:
                    text = resp.text
                    if "authwall" in resp.headers.get("location", "") or "Join LinkedIn" in text and "Sign in" in text and "profile-unavailable" in text:
                        # Soft login wall
                        logger.warning("LinkedIn public profile authwall encountered for %s", url)
                    return text

                if status in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location", "")
                    if any(x in loc for x in ("/authwall", "/login", "checkpoint")):
                        raise AuthExpired(f"Redirected to LinkedIn authwall/login: {loc}")
                    # Follow one non-auth redirect, and only inside linkedin.com
                    target = urljoin(url, loc)
                    if not (urlparse(target).hostname or "").endswith("linkedin.com"):
                        raise AuthExpired(f"Refusing redirect outside linkedin.com: {target}")
                    return await self.get_public_page(target)

                if status == 999:
                    logger.warning("LinkedIn anti-bot HTTP 999 on %s", url)
                    if attempt == self.max_attempts or self.is_breaker_tripped():
                        raise Blocked(f"Blocked by LinkedIn (HTTP 999) after {attempt} attempts")
                    await asyncio.sleep(2.0 * attempt + random.uniform(0.5, 1.5))
                    continue

                if status == 429:
                    logger.warning("LinkedIn rate limit HTTP 429 on %s", url)
                    if attempt == self.max_attempts or self.is_breaker_tripped():
                        raise RateLimited(f"Rate limited by LinkedIn (HTTP 429) after {attempt} attempts")
                    await asyncio.sleep(3.0 * attempt + random.uniform(1.0, 2.0))
                    continue

                if status in (401, 403):
                    raise AuthExpired(f"LinkedIn HTTP {status} access denied for {url}")

                if status >= 500:
                    if attempt == self.max_attempts:
                        raise Transient(f"LinkedIn server error HTTP {status} after {attempt} attempts")
                    await asyncio.sleep(1.0 * attempt)
                    continue

                # 404 or other 4xx
                return ""

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                self._record_status(0)
                if attempt == self.max_attempts:
                    raise Transient(f"LinkedIn request failed: {exc}") from exc
                await asyncio.sleep(1.0 * attempt)

        raise Transient(f"Failed to fetch {url} after {self.max_attempts} attempts")

    @staticmethod
    def is_auth_enabled() -> bool:
        """Checks if authenticated LinkedIn scraping is explicitly enabled via environment."""
        val = os.getenv("LINKEDIN_AUTH_ENABLED", "false").strip().lower()
        return val in ("1", "true", "yes", "on")

    @classmethod
    def get_auth_cookies(cls) -> Optional[Dict[str, str]]:
        """Retrieves LinkedIn cookies from Key Vault (provider='linkedin'). Never reads from plain files."""
        if not cls.is_auth_enabled():
            return None
        try:
            mgr = get_secrets_manager()
            key_rec = mgr.get_active_key("linkedin")
            if not key_rec or not key_rec.value:
                return None
            try:
                payload = json.loads(key_rec.value)
                if isinstance(payload, dict) and "li_at" in payload:
                    return payload
            except json.JSONDecodeError:
                # Value may be li_at token directly
                return {"li_at": key_rec.value.strip()}
        except Exception as exc:
            logger.debug("Failed to retrieve LinkedIn credentials from Key Vault: %s", exc)
        return None

    async def get_authenticated(self, url: str) -> Dict[str, Any]:
        """Fetch Voyager or authenticated endpoint using curl_cffi in background thread.
        Strictly gated behind LINKEDIN_AUTH_ENABLED=true and Key Vault credentials.
        """
        if not self.is_auth_enabled():
            raise AuthExpired("LINKEDIN_AUTH_ENABLED is false; authenticated requests disabled.")

        cookies = self.get_auth_cookies()
        if not cookies or not cookies.get("li_at"):
            raise AuthExpired("No LinkedIn credentials found in Key Vault (provider='linkedin').")

        # Lazy import curl_cffi to avoid requiring it in public-only environments
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError as exc:
            raise RuntimeError("curl_cffi is required for authenticated LinkedIn mode.") from exc

        def _do_cffi_request():
            li_at = cookies.get("li_at", "")
            jsessionid = cookies.get("JSESSIONID") or cookies.get("jsessionid", "")

            session = cffi_requests.Session(impersonate="chrome")
            session.headers.update({
                "x-restli-protocol-version": "2.0.0",
                "accept": "application/json",
                "x-li-lang": "en_US",
                "referer": "https://www.linkedin.com/",
                "accept-language": "en-US,en;q=0.9",
            })
            if jsessionid:
                clean_csrf = jsessionid.strip("\"' ")
                session.headers["csrf-token"] = clean_csrf
            session.cookies.set("li_at", li_at, domain=".linkedin.com")
            if jsessionid:
                session.cookies.set("JSESSIONID", jsessionid, domain=".linkedin.com")

            resp = session.get(url, timeout=self.timeout_seconds)
            status = resp.status_code
            if status in (401, 403):
                raise AuthExpired(f"LinkedIn authenticated session expired: HTTP {status}")
            if status == 999:
                raise Blocked("LinkedIn anti-bot HTTP 999 received on authenticated request.")
            if status == 429:
                raise RateLimited("LinkedIn rate limited (HTTP 429) on authenticated request.")
            if status != 200:
                raise Transient(f"LinkedIn HTTP {status} on {url}")
            return resp.json()

        return await asyncio.to_thread(_do_cffi_request)

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
