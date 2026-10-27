"""
Resilient HTTP client with retry, backoff, and streaming capabilities.
"""

import os
import time
import random
import requests
from typing import Optional, Dict, Any, Generator
from .logging import logger


class HttpClient:
    """
    HTTP client configured for resilient data acquisition from official sources.
    Respects rate limits, Retry-After headers, and implements exponential backoff.
    """

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        headers: Optional[Dict[str, str]] = None,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.session = requests.Session()
        default_headers = {
            "User-Agent": "Mexico-B2B-OpenData-Ingestion/1.0 (Government Open Data Ingestion Pipeline)",
            "Accept": "application/json, text/csv, application/xhtml+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
        if headers:
            default_headers.update(headers)
        self.session.headers.update(default_headers)

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> requests.Response:
        """Performs a GET request with retry logic."""
        return self._request_with_retry("GET", url, params=params, headers=headers, timeout=timeout)

    def post(
        self,
        url: str,
        data: Optional[Any] = None,
        json: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
    ) -> requests.Response:
        """Performs a POST request with retry logic."""
        return self._request_with_retry(
            "POST", url, data=data, json=json, params=params, headers=headers, timeout=timeout
        )

    def download_file(
        self,
        url: str,
        destination_path: str,
        chunk_size: int = 65536,
        timeout: Optional[int] = 60,
    ) -> str:
        """
        Streams a remote file directly to disk to minimize memory usage for large CSVs/ZIPs.
        """
        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)
        temp_destination = destination_path + ".tmp"
        
        response = self.session.get(url, stream=True, timeout=timeout or self.timeout)
        response.raise_for_status()

        with open(temp_destination, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)

        if os.path.exists(destination_path):
            os.remove(destination_path)
        os.rename(temp_destination, destination_path)
        return destination_path

    def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        timeout = kwargs.pop("timeout", None) or self.timeout
        attempt = 0

        while attempt <= self.max_retries:
            try:
                response = self.session.request(method, url, timeout=timeout, **kwargs)
                
                # Check for rate limiting / Retry-After
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_time = float(retry_after) if retry_after else (self.backoff_factor ** attempt) + random.uniform(0.5, 1.5)
                    logger.warn("Rate limited (429)", url=self._sanitize_url(url), retry_in_seconds=sleep_time)
                    time.sleep(sleep_time)
                    attempt += 1
                    continue

                if response.status_code in (500, 502, 503, 504):
                    if attempt < self.max_retries:
                        sleep_time = (self.backoff_factor ** attempt) + random.uniform(0.5, 1.5)
                        logger.warn(f"Server error ({response.status_code})", url=self._sanitize_url(url), retry_in_seconds=sleep_time)
                        time.sleep(sleep_time)
                        attempt += 1
                        continue

                response.raise_for_status()
                return response

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                attempt += 1
                if attempt > self.max_retries:
                    logger.error("HTTP request failed after max retries", url=self._sanitize_url(url), error=str(e))
                    raise
                sleep_time = (self.backoff_factor ** attempt) + random.uniform(0.5, 1.5)
                logger.warn("HTTP connection error, retrying", url=self._sanitize_url(url), attempt=attempt, retry_in_seconds=sleep_time)
                time.sleep(sleep_time)

        raise requests.exceptions.RetryError(f"Max retries exceeded for URL: {self._sanitize_url(url)}")

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """Removes query parameters containing potential tokens for clean logging."""
        if "?" in url:
            base, query = url.split("?", 1)
            sanitized_params = []
            for param in query.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    if any(sensitive in k.lower() for sensitive in ["token", "key", "secret", "auth", "pwd"]):
                        sanitized_params.append(f"{k}=***")
                    else:
                        sanitized_params.append(param)
                else:
                    sanitized_params.append(param)
            return f"{base}?{'&'.join(sanitized_params)}"
        return url
