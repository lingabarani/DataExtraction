import asyncio
import email.utils
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger("gmaps_scraper.http")

class HttpClient:
    """
    Async HTTP client tailored for Google Maps endpoints & reliable state collection:
    - Granular connection, read, and total request deadlines
    - Browser header emulation (UA, Accept-Language, Accept-Encoding)
    - Consent cookies ('CONSENT=YES+; SOCS=...')
    - Per-host rate-limiting semaphore
    - Exponential backoff with jitter on 429 / 5xx / timeouts
    - Respects HTTP 'Retry-After' headers
    - Fast-fails permanent 4xx client errors (400, 401, 403, 404, 422) without retries
    - Request counter and retry instrumentation
    - Consent cookie refresh on redirect
    """
    def __init__(
        self,
        user_agent: str,
        accept_language: str = "en-US,en;q=0.9",
        hl: str = "en",
        gl: str = "us",
        concurrency: int = 5,
        per_host_rate: float = 2.0,
        max_retries: int = 3,
        backoff_base: float = 1.5,
        connect_timeout: float = 10.0,
        read_timeout: float = 30.0,
        total_timeout: float = 45.0,
        proxies: Optional[List[str]] = None,
    ):
        self.user_agent = user_agent
        self.accept_language = accept_language
        self.hl = hl
        self.gl = gl
        self.concurrency = concurrency
        self.semaphore = asyncio.Semaphore(concurrency)
        self.per_host_rate = per_host_rate
        self.delay_between_requests = 1.0 / max(per_host_rate, 0.1)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.total_timeout = total_timeout
        self.proxies = proxies or []
        self._last_request_time = 0.0

        # Request counter instrumentation
        self.request_count = 0
        self.retry_count = 0
        self.error_count = 0

        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": self.accept_language,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/maps/",
            "Cookie": "CONSENT=YES+; SOCS=CAISHAgBEhJnd3NfMjAyNDA2MTAtMF9SQzEaAmVuIAEaBgiA_LyuBg",
        }
        proxy = self.proxies[0] if self.proxies else None
        
        # Granular connection, read, write, and total deadlines
        timeout = httpx.Timeout(
            timeout=self.total_timeout,
            connect=self.connect_timeout,
            read=self.read_timeout,
            write=10.0
        )
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            http2=False,
            proxy=proxy
        )

    async def close(self):
        await self.client.aclose()

    async def _rate_limit(self):
        loop = asyncio.get_event_loop()
        now = loop.time()
        elapsed = now - self._last_request_time
        if elapsed < self.delay_between_requests:
            sleep_time = (self.delay_between_requests - elapsed) + random.uniform(0.05, 0.15)
            await asyncio.sleep(sleep_time)
        self._last_request_time = loop.time()

    def _parse_retry_after(self, header_value: Optional[str]) -> Optional[float]:
        """Parses Retry-After header (seconds or RFC 2822 date) into seconds float."""
        if not header_value:
            return None
        val = header_value.strip()
        # 1. Integer seconds
        try:
            sec = float(val)
            return max(1.0, min(sec, 60.0))
        except ValueError:
            pass
        # 2. HTTP date
        try:
            dt = email.utils.parsedate_to_datetime(val)
            now = datetime.now(timezone.utc)
            diff = (dt - now).total_seconds()
            return max(1.0, min(diff, 60.0))
        except Exception:
            return None

    async def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> httpx.Response:
        attempts = 0
        last_exception: Optional[Exception] = None

        while attempts < self.max_retries:
            attempts += 1
            async with self.semaphore:
                await self._rate_limit()
                self.request_count += 1
                try:
                    resp = await self.client.get(url, params=params, headers=headers)

                    # Re-establish consent cookies if provided in Set-Cookie
                    if "set-cookie" in resp.headers:
                        for cookie_name, cookie_val in resp.cookies.items():
                            if cookie_name in ["CONSENT", "SOCS"]:
                                self.client.headers["Cookie"] = f"{cookie_name}={cookie_val}"

                    # Fast-fail non-retryable 4xx client errors (except 429 Rate Limit)
                    if 400 <= resp.status_code < 500 and resp.status_code != 429:
                        return resp

                    # Transient failure handling (HTTP 429 or 5xx)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        self.retry_count += 1
                        if attempts >= self.max_retries:
                            self.error_count += 1
                            return resp

                        # Check for Retry-After header
                        retry_after = self._parse_retry_after(resp.headers.get("retry-after"))
                        if retry_after is not None:
                            backoff = retry_after + random.uniform(0.1, 0.5)
                        else:
                            backoff = (self.backoff_base ** attempts) + random.uniform(0.5, 1.5)

                        logger.warning(
                            f"HTTP {resp.status_code} on {url}. Retrying ({attempts}/{self.max_retries}) in {backoff:.2f}s..."
                        )
                        await asyncio.sleep(backoff)
                        continue

                    return resp

                except (httpx.TimeoutException, httpx.RequestError) as ex:
                    last_exception = ex
                    self.retry_count += 1
                    if attempts >= self.max_retries:
                        self.error_count += 1
                        logger.error(f"Failed to fetch {url} after {self.max_retries} attempts: {ex}")
                        raise

                    backoff = (self.backoff_base ** attempts) + random.uniform(0.5, 1.5)
                    logger.warning(
                        f"Network timeout/error ({type(ex).__name__}) on {url}. "
                        f"Retrying ({attempts}/{self.max_retries}) in {backoff:.2f}s..."
                    )
                    await asyncio.sleep(backoff)

        self.error_count += 1
        if last_exception:
            raise last_exception
        raise RuntimeError(f"Failed to fetch {url} after {self.max_retries} attempts")
