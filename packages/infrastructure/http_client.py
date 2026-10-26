"""
OneExtraction — Unified Enterprise HTTP Client
Standardized HTTP client with:
1. Connection pooling (HTTPAdapter with pool_connections and pool_maxsize)
2. Exponential backoff with jitter and Retry-After header compliance
3. Domain-based rate limiting (e.g. SEC EDGAR 10 req/sec limit)
4. SEC Fair Access User-Agent auto-injection for *.sec.gov
5. Configurable timeouts, streaming downloads, and structured logging
"""

import logging
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

try:
    from config_manager import config_manager
    _HAS_CONFIG = True
except ImportError:
    _HAS_CONFIG = False

logger = logging.getLogger("oneextraction.http_client")

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_TIMEOUT = (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT)


class RateLimiter:
    """Thread-safe domain rate limiter enforcing minimum intervals between requests."""

    def __init__(self, max_rate_per_sec: Optional[float] = None):
        self._lock = threading.Lock()
        self._last_request_time: Dict[str, float] = {}
        # Maximum requests per second per domain (default is unthrottled or 20 rps)
        self._domain_rps_limits: Dict[str, float] = {
            "sec.gov": 8.0,          # SEC allows max 10 rps
            "data.sec.gov": 8.0,
            "api.sam.gov": 5.0,
            "api.usaspending.gov": 10.0,
            "projects.propublica.org": 5.0,
            "banks.data.fdic.gov": 10.0,
        }
        if max_rate_per_sec is not None:
            self._default_rps: Optional[float] = max_rate_per_sec
        else:
            self._default_rps = None

    def set_rate_limit(self, domain: str, max_rps: float):
        """Set custom max requests per second for a domain."""
        with self._lock:
            self._domain_rps_limits[domain.lower()] = max_rps

    def acquire(self, url_or_domain: str):
        """Alias for wait_for_slot."""
        self.wait_for_slot(url_or_domain)

    def wait_for_slot(self, url: str):
        """Throttle request if needed to satisfy domain rate limits."""
        raw_url = url if "://" in url else f"https://{url}"
        parsed = urlparse(raw_url)
        hostname = (parsed.hostname or url).lower()
        if not hostname:
            return

        # Find matching domain limit (exact or suffix)
        limit_rps = None
        for domain_pattern, rps in self._domain_rps_limits.items():
            if hostname == domain_pattern or hostname.endswith("." + domain_pattern):
                limit_rps = rps
                break

        if limit_rps is None and self._default_rps is not None:
            limit_rps = self._default_rps

        if not limit_rps or limit_rps <= 0:
            return

        min_interval = 1.0 / limit_rps

        with self._lock:
            now = time.monotonic()
            last_time = self._last_request_time.get(hostname, 0.0)
            elapsed = now - last_time
            if elapsed < min_interval:
                sleep_needed = min_interval - elapsed + random.uniform(0.01, 0.03)
                time.sleep(sleep_needed)
            self._last_request_time[hostname] = time.monotonic()


class EnterpriseHttpClient:
    """
    Production-hardened HTTP client for all OneExtraction data ingestion pipelines.
    """

    def __init__(
        self,
        max_retries: int = 4,
        backoff_factor: float = 1.5,
        pool_connections: int = 25,
        pool_maxsize: int = 50,
        default_timeout: Tuple[float, float] = DEFAULT_TIMEOUT,
    ):
        self.default_timeout = default_timeout
        self.rate_limiter = RateLimiter()
        self.session = requests.Session()

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "HEAD", "OPTIONS"],
            raise_on_status=False,
            respect_retry_after_header=True,
        )

        adapter = HTTPAdapter(
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries=retry_strategy,
        )

        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update({
            "User-Agent": "OneExtraction-DataPipeline/2.0 (+https://oneextraction.io)",
            "Accept-Encoding": "gzip, deflate",
        })

    def _prepare_headers(self, url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Inject appropriate compliance headers depending on destination host."""
        req_headers = dict(headers or {})
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        # SEC EDGAR User-Agent compliance check
        if "sec.gov" in hostname:
            if "User-Agent" not in req_headers:
                if _HAS_CONFIG:
                    req_headers["User-Agent"] = config_manager.get_sec_user_agent()
                else:
                    req_headers["User-Agent"] = "OneExtraction Corp compliance@oneextraction.io"

        return req_headers

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        """Send a GET request with rate limiting and exponential backoff."""
        self.rate_limiter.wait_for_slot(url)
        effective_headers = self._prepare_headers(url, headers)
        effective_timeout = timeout or self.default_timeout

        t0 = time.monotonic()
        try:
            resp = self.session.get(
                url,
                params=params,
                headers=effective_headers,
                timeout=effective_timeout,
                stream=stream,
                **kwargs,
            )
            elapsed = time.monotonic() - t0
            logger.debug("GET %s [%s] in %.2fs", url, resp.status_code, elapsed)
            return resp
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("GET %s failed after %.2fs: %s", url, elapsed, e)
            raise

    def post(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[Union[float, Tuple[float, float]]] = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Send a POST request with rate limiting and exponential backoff."""
        self.rate_limiter.wait_for_slot(url)
        effective_headers = self._prepare_headers(url, headers)
        effective_timeout = timeout or self.default_timeout

        t0 = time.monotonic()
        try:
            resp = self.session.post(
                url,
                data=data,
                json=json,
                params=params,
                headers=effective_headers,
                timeout=effective_timeout,
                **kwargs,
            )
            elapsed = time.monotonic() - t0
            logger.debug("POST %s [%s] in %.2fs", url, resp.status_code, elapsed)
            return resp
        except Exception as e:
            elapsed = time.monotonic() - t0
            logger.error("POST %s failed after %.2fs: %s", url, elapsed, e)
            raise

    def download_file(
        self,
        url: str,
        target_path: Union[str, Path],
        chunk_size: int = 1024 * 1024,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        timeout: float = 60.0,
    ) -> Path:
        """
        Stream a large file directly to disk with chunking, temporary file write,
        and atomic replacement.
        """
        dest = Path(target_path).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp_dest = dest.with_suffix(dest.suffix + f".tmp_{time.time_ns()}")

        self.rate_limiter.wait_for_slot(url)
        effective_headers = self._prepare_headers(url)

        logger.info("Starting download of %s to %s", url, dest)
        with self.session.get(url, headers=effective_headers, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get("content-length", 0))
            downloaded = 0

            with open(tmp_dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)

        tmp_dest.replace(dest)
        logger.info("Completed download of %s (%.2f MB)", dest, downloaded / 1e6)
        return dest

    def close(self):
        """Close the underlying requests session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Shared singleton client instance
http_client = EnterpriseHttpClient()


def get_http_client() -> EnterpriseHttpClient:
    """Return the shared enterprise HTTP client singleton."""
    return http_client
