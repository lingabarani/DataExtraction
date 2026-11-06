"""
DataExtraction — Async Web Scraper & Contact Page Crawler
=========================================================
Enterprise async HTTP extraction engine harvested and refactored from FORGE.
Capabilities:
  - Connection pooling with DNS caching via httpx.AsyncClient
  - Dual-layer rate limiting: global token bucket + per-domain politeness locks
  - Multi-tier contact path exploration (/contact, /about, /team, /staff)
  - Cloudflare & entity obfuscation decoding integration
  - Web technology stack, CMS detection, SSL validity, and response latency profiling
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.structured_logger import get_structured_logger
from packages.scrapers.web.obfuscation_decoder import extract_all_emails_from_html

logger = get_structured_logger("scrapers.email_crawler")

# ── Tech Stack Signatures (Headers + HTML) ────────────────────────────────────

_TECH_PATTERNS: Dict[str, List[str]] = {
    # CMS Platforms
    "wordpress": [r"wp-content", r"wp-includes", r"WordPress"],
    "shopify": [r"cdn\.shopify\.com", r"Shopify"],
    "squarespace": [r"squarespace\.com", r"Squarespace"],
    "wix": [r"wix\.com", r"wixstatic\.com"],
    "webflow": [r"webflow\.com", r"Webflow"],
    "drupal": [r"Drupal", r"/sites/default/files"],
    "joomla": [r"Joomla", r"/components/com_"],
    "ghost": [r"ghost\.io", r"Ghost"],
    "weebly": [r"weebly\.com"],
    "godaddy-builder": [r"godaddy\.com/website-builder"],
    "hubspot-cms": [r"hubspot\.com/hub", r"hs-sites\.com"],
    "bigcommerce": [r"bigcommerce\.com", r"BigCommerce"],

    # Frontend Frameworks
    "react": [r"__next", r"_next/static", r"react\.production", r"data-reactroot"],
    "next.js": [r"__next", r"/_next/"],
    "vue": [r"vue\.js", r"__vue__", r"data-v-"],
    "angular": [r"ng-version", r"angular"],
    "svelte": [r"svelte", r"__svelte"],
    "bootstrap": [r"bootstrap\.min\.(css|js)", r"getbootstrap\.com"],
    "tailwind": [r"tailwindcss", r"tailwind\.min\.css"],

    # Analytics & Telemetry
    "google-analytics": [r"google-analytics\.com", r"gtag", r"UA-\d+", r"G-[A-Z0-9]+"],
    "google-tag-manager": [r"googletagmanager\.com", r"GTM-"],
    "facebook-pixel": [r"connect\.facebook\.net", r"fbevents\.js"],
    "hotjar": [r"hotjar\.com"],
    "segment": [r"segment\.com/analytics", r"analytics\.js"],

    # Booking & Scheduling
    "calendly": [r"calendly\.com"],
    "acuity": [r"acuityscheduling\.com"],

    # Customer Messaging & Chat
    "intercom": [r"intercom\.io", r"intercomSettings"],
    "drift": [r"drift\.com"],
    "zendesk": [r"zendesk\.com"],
    "crisp": [r"crisp\.chat"],
    "tidio": [r"tidio\.co"],
    "hubspot": [r"hubspot\.com", r"hs-scripts"],

    # Payment Gateways
    "stripe": [r"stripe\.com", r"js\.stripe"],
    "square": [r"squareup\.com"],
    "paypal": [r"paypal\.com"],

    # Security & Infrastructure
    "cloudflare": [r"cloudflare", r"cf-ray", r"__cf_bm"],
    "recaptcha": [r"google\.com/recaptcha", r"g-recaptcha"],
}

_CMS_PRIORITY = [
    "wordpress", "shopify", "squarespace", "wix", "webflow",
    "drupal", "joomla", "ghost", "weebly", "godaddy-builder",
]

_CONTACT_PATHS = [
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/team",
    "/staff",
    "/our-team",
    "/leadership",
    "/reach-us",
    "/privacy-policy",
    "/privacy",
    "/terms",
]


class AsyncTokenBucketLimiter:
    """Async token bucket rate limiter without external C-extensions."""

    def __init__(self, rate_per_second: float):
        self.rate = max(0.1, rate_per_second)
        self.capacity = self.rate
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now

                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return

                needed = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(needed)


class AsyncEmailWebCrawler:
    """
    High-throughput async website crawler for email discovery and tech profiling.
    Follows politeness constraints and handles connection pooling via httpx.AsyncClient.
    """

    def __init__(
        self,
        rate_limit_per_second: Optional[float] = None,
        per_host_limit: Optional[int] = None,
        total_timeout: Optional[float] = None,
        connect_timeout: Optional[float] = None,
        max_body_size: Optional[int] = None,
        max_concurrent: Optional[int] = None,
        user_agent: Optional[str] = None,
    ):
        cfg = config_manager.get_email_enrichment_config()
        self.rate_limit = rate_limit_per_second or cfg["rate_limit_per_second"]
        self.per_host_limit = per_host_limit or cfg["per_host_limit"]
        self.total_timeout = total_timeout or cfg["total_timeout"]
        self.connect_timeout = connect_timeout or cfg["connect_timeout"]
        self.max_body_size = max_body_size or cfg["max_body_size"]
        self.max_concurrent = max_concurrent or cfg["max_concurrent"]
        self.user_agent = user_agent or cfg["user_agent"]

        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._rate_limiter = AsyncTokenBucketLimiter(self.rate_limit)
        self._domain_locks: Dict[str, asyncio.Lock] = {}
        self._domain_last_request: Dict[str, float] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """Initializes or retrieves the active connection-pooled httpx client."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(
                max_connections=self.max_concurrent,
                max_keepalive_connections=self.max_concurrent,
                keepalive_expiry=30.0,
            )
            timeout = httpx.Timeout(
                timeout=self.total_timeout,
                connect=self.connect_timeout,
            )
            self._client = httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            )
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._client

    async def close(self) -> None:
        """Gracefully closes open HTTP connection pools."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _apply_domain_politeness(self, domain: str) -> None:
        """Enforces minimum 0.5s interval between requests targeting the same host."""
        if not domain:
            return
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()

        async with self._domain_locks[domain]:
            now = time.monotonic()
            elapsed = now - self._domain_last_request.get(domain, 0.0)
            min_delay = 0.5
            if elapsed < min_delay:
                await asyncio.sleep(min_delay - elapsed)
            self._domain_last_request[domain] = time.monotonic()

    def _detect_tech_stack(self, html: str, headers: Dict[str, str]) -> List[str]:
        """Scans page markup and response headers for known technology signatures."""
        detected = []
        search_blob = html + " " + " ".join(f"{k}: {v}" for k, v in headers.items())
        for tech, patterns in _TECH_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, search_blob, re.IGNORECASE):
                    detected.append(tech)
                    break
        return detected

    def _detect_primary_cms(self, tech_stack: List[str]) -> Optional[str]:
        """Extracts the primary CMS from the detected technologies."""
        for cms in _CMS_PRIORITY:
            if cms in tech_stack:
                return cms
        return None

    async def _crawl_contact_pages(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        domain: str,
    ) -> Set[str]:
        """Crawls standard contact and team subpaths until emails are discovered."""
        found_emails: Set[str] = set()

        for path in _CONTACT_PATHS:
            target_url = urljoin(base_url, path)
            try:
                await self._rate_limiter.acquire()
                await self._apply_domain_politeness(domain)

                resp = await client.get(target_url)
                if resp.status_code == 200:
                    html_text = resp.text[:self.max_body_size]
                    extracted = extract_all_emails_from_html(html_text)
                    if extracted:
                        found_emails.update(extracted)
                        logger.debug("Discovered %d emails on contact page: %s", len(extracted), target_url)
                        break  # Found emails; stop crawling additional subpaths
            except Exception:
                continue

        return found_emails

    async def scrape_domain_emails(
        self,
        website_url: str,
        crawl_contact_pages: bool = True,
    ) -> Dict[str, Any]:
        """
        Scrapes a business website for email addresses and domain profile metadata.
        Returns a standardized dictionary with discovered emails, tech stack, and telemetry.
        """
        raw_url = website_url.strip() if website_url else ""
        if not raw_url:
            return {"status": "INVALID_URL", "emails": [], "tech_stack": []}

        if not raw_url.startswith(("http://", "https://")):
            url = f"https://{raw_url}"
        else:
            url = raw_url

        parsed = urlparse(url)
        domain = parsed.hostname or ""

        result: Dict[str, Any] = {
            "url": url,
            "domain": domain,
            "status": "UNKNOWN",
            "emails": [],
            "tech_stack": [],
            "cms_detected": None,
            "ssl_valid": None,
            "site_speed_ms": None,
            "http_status_code": None,
            "crawled_contact_pages": False,
        }

        client = await self._get_client()
        assert self._semaphore is not None

        start_time = time.monotonic()
        try:
            async with self._semaphore:
                await self._rate_limiter.acquire()
                await self._apply_domain_politeness(domain)

                try:
                    # Attempt HTTPS first with verification
                    resp = await client.get(url)
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    result["site_speed_ms"] = duration_ms
                    result["http_status_code"] = resp.status_code
                    result["ssl_valid"] = url.startswith("https://")

                    if resp.status_code == 200:
                        html = resp.text[:self.max_body_size]
                        result["status"] = "SUCCESS"

                        # 1. Tech stack and CMS detection
                        tech = self._detect_tech_stack(html, dict(resp.headers))
                        result["tech_stack"] = tech
                        result["cms_detected"] = self._detect_primary_cms(tech)

                        # 2. Extract homepage emails
                        discovered_emails = extract_all_emails_from_html(html)

                        # 3. If homepage lacks emails, explore contact pages
                        if not discovered_emails and crawl_contact_pages:
                            base_url = f"{resp.url.scheme}://{resp.url.netloc}"
                            contact_emails = await self._crawl_contact_pages(client, base_url, domain)
                            discovered_emails.update(contact_emails)
                            result["crawled_contact_pages"] = True

                        result["emails"] = list(discovered_emails)
                    else:
                        result["status"] = f"HTTP_{resp.status_code}"

                except (httpx.ConnectError, httpx.SecurityError):
                    # SSL Certificate failure -> Retry over HTTP
                    result["ssl_valid"] = False
                    http_url = url.replace("https://", "http://")
                    http_resp = await client.get(http_url)
                    duration_ms = int((time.monotonic() - start_time) * 1000)
                    result["site_speed_ms"] = duration_ms
                    result["http_status_code"] = http_resp.status_code
                    if http_resp.status_code == 200:
                        html = http_resp.text[:self.max_body_size]
                        result["status"] = "SUCCESS_NO_SSL"
                        tech = self._detect_tech_stack(html, dict(http_resp.headers))
                        result["tech_stack"] = tech
                        result["cms_detected"] = self._detect_primary_cms(tech)
                        result["emails"] = list(extract_all_emails_from_html(html))
                    else:
                        result["status"] = f"HTTP_{http_resp.status_code}"

        except httpx.TimeoutException:
            result["status"] = "TIMEOUT"
        except httpx.RequestError as exc:
            result["status"] = "CONNECTION_FAILED"
            result["error"] = str(exc)[:200]
        except Exception as exc:
            result["status"] = "ERROR"
            result["error"] = str(exc)[:200]
            logger.debug("Crawling error on %s: %s", url, exc)

        return result

    crawl_site = scrape_domain_emails

    async def scrape_batch(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Scrapes multiple business URLs concurrently with shared connection pooling."""
        tasks = [self.scrape_domain_emails(u) for u in urls]
        return await asyncio.gather(*tasks, return_exceptions=False)
