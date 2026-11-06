"""
DataExtraction — Domain Email Enrichment & Multi-Source Scorer
==============================================================
Production coordinator for email discovery, ranking, confidence scoring,
and deliverability tiering. Integrates 5-tier validation heuristics.
"""

from dataclasses import dataclass, field
import asyncio
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

from packages.domain.smtp_engine import (
    generate_candidate_emails,
    get_mx_hosts,
    is_catchall_domain,
    verify_email_smtp,
)
from packages.domain.validation import (
    DISPOSABLE_DOMAINS,
    ROLE_PREFIXES,
    extract_registered_domain,
)
from packages.scrapers.web.email_crawler import AsyncEmailWebCrawler
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("domain.email_enricher")

# Inboxes that rarely reach a human decision maker. Ranked lowest.
LOW_VALUE_EMAIL_PREFIXES: Set[str] = {
    "abuse",
    "accessibility",
    "careers",
    "compliance",
    "copyright",
    "dataprotection",
    "dmca",
    "donotreply",
    "do-not-reply",
    "dpo",
    "gdpr",
    "hostmaster",
    "hr",
    "jobs",
    "legal",
    "no-reply",
    "noreply",
    "postmaster",
    "privacy",
    "recruiting",
    "security",
    "unsubscribe",
    "webmaster",
}

SOURCE_WEIGHTS: Dict[str, float] = {
    "WEB_CONTACT_PAGE": 0.95,
    "WEB_MAILTO": 0.95,
    "WEB_CRAWLER": 0.90,
    "JSON_LD": 0.90,
    "WEB_HOMEPAGE": 0.85,
    "WEB_REGEX": 0.85,
    "FOOTER": 0.80,
    "SMTP_PROBED": 0.70,
}


@dataclass
class EmailCandidate:
    """Represents a discovered email candidate with metadata."""
    email: str
    source: str
    confidence: float = 0.0
    deliverability_status: str = "PENDING"
    is_catchall: bool = False
    is_role_account: bool = False


@dataclass
class EnrichmentResult:
    """Consolidated enrichment outcome for an organization."""
    company_id: str
    domain: str
    primary_email: Optional[str]
    all_emails: List[str] = field(default_factory=list)
    discovery_source: str = "NONE"
    deliverability_status: str = "UNDELIVERABLE"
    confidence_score: float = 0.0
    is_catchall: bool = False
    is_role_account: bool = False
    tech_stack: List[str] = field(default_factory=list)
    cms_detected: Optional[str] = None
    ssl_valid: Optional[bool] = None
    site_speed_ms: Optional[int] = None
    http_status_code: Optional[int] = None


def normalize_site_host(site_host: str) -> str:
    """Normalizes hostname by removing www. and trailing dots."""
    host = (site_host or "").lower().strip().strip(".")
    return host[4:] if host.startswith("www.") else host


def rank_emails(emails: Iterable[str], site_host: str) -> List[str]:
    """
    Sorts emails with high-value business mailboxes first:
    1. Addresses matching the site's own domain come before third-party ones.
    2. Operational/decision-maker inboxes come before low-value ones (privacy@, noreply@).
    3. Preserves deterministic order.
    """
    site = normalize_site_host(site_host)

    def is_own_domain(domain_part: str) -> bool:
        if not site:
            return False
        return (
            domain_part == site
            or site.endswith("." + domain_part)
            or domain_part.endswith("." + site)
        )

    def sort_key(email_address: str) -> Tuple[bool, bool, str]:
        local_part, _, domain_part = email_address.partition("@")
        is_low_value = local_part in LOW_VALUE_EMAIL_PREFIXES
        is_third_party = not is_own_domain(domain_part)
        return (is_low_value, is_third_party, email_address)

    unique_valid = {e.lower().strip() for e in emails if e and "@" in e}
    return sorted(unique_valid, key=sort_key)


def compute_email_confidence(
    source: str,
    has_valid_mx: bool,
    is_catchall: bool,
    smtp_code: Optional[int] = None,
    email: Optional[str] = None,
) -> Tuple[float, str, bool]:
    """
    Computes calibrated probability confidence, deliverability tier, and role status:
    Confidence = W_source * (1 - P_catchall) * M_mx * S_smtp
    Returns (confidence, deliverability_status, is_role_account).
    """
    w_source = SOURCE_WEIGHTS.get(source, 0.75)
    m_mx = 1.0 if has_valid_mx else 0.0
    p_catchall = 0.50 if is_catchall else 0.00
    is_role = False

    if email and "@" in email:
        local_part, _, domain_part = email.partition("@")
        domain_part = domain_part.lower().strip()
        local_part = local_part.lower().strip()

        # Tier 3: Disposable domain blacklist
        if domain_part in DISPOSABLE_DOMAINS:
            return 0.0, "UNDELIVERABLE", False

        # Role address check
        if local_part in ROLE_PREFIXES:
            is_role = True

    if not has_valid_mx:
        return 0.0, "UNDELIVERABLE", is_role

    if smtp_code == 250:
        s_smtp = 1.0
    elif smtp_code in (450, 451, 452):
        s_smtp = 0.6  # Greylisting
    elif smtp_code in (550, 551, 552, 553, 554):
        s_smtp = 0.0  # Definitive rejection
    else:
        s_smtp = 0.85  # MX confirmed without SMTP probe

    confidence = round(w_source * (1.0 - p_catchall) * m_mx * s_smtp, 3)

    if s_smtp == 0.0:
        status = "UNDELIVERABLE"
    elif is_catchall:
        status = "CATCHALL"
    elif confidence >= 0.80 and smtp_code == 250:
        status = "DELIVERABLE"
    elif has_valid_mx and confidence >= 0.60:
        status = "MX_CONFIRMED"
    else:
        status = "RISKY"

    return confidence, status, is_role


class EmailEnrichmentEngine:
    """High-level domain service orchestrating discovery, SMTP probing, and scoring."""

    @staticmethod
    def process_discovered_emails(
        company_id: str,
        domain: str,
        crawl_results: Dict[str, Any],
        probe_smtp: bool = True,
    ) -> EnrichmentResult:
        """
        Processes web crawl results, resolves MX hosts, checks catch-all status,
        performs SMTP probes, and assigns confidence scores.
        """
        raw_emails = crawl_results.get("emails", [])
        tech_stack = crawl_results.get("tech_stack", [])
        cms_detected = crawl_results.get("cms_detected")
        ssl_valid = crawl_results.get("ssl_valid")
        site_speed_ms = crawl_results.get("site_speed_ms")
        http_status_code = crawl_results.get("http_status_code")

        clean_domain = domain or crawl_results.get("domain", "")

        # 1. Rank discovered emails
        ranked = rank_emails(raw_emails, clean_domain)

        # 2. MX resolution
        mx_hosts = get_mx_hosts(clean_domain) if clean_domain else None
        has_mx = bool(mx_hosts)

        # 3. Catch-all detection
        catchall = False
        if has_mx and probe_smtp:
            assert mx_hosts is not None
            catchall = is_catchall_domain(clean_domain, mx_hosts)

        # 4. If no web emails discovered, attempt candidate generation
        discovery_source = "NONE"
        candidate_to_probe: Optional[str] = None
        if ranked:
            candidate_to_probe = ranked[0]
            discovery_source = "WEB_CRAWLER"
        elif clean_domain and has_mx and probe_smtp:
            # Generate common candidates
            candidates = generate_candidate_emails(clean_domain)
            for cand in candidates:
                assert mx_hosts is not None
                probe_res = verify_email_smtp(cand, mx_hosts)
                if probe_res.get("is_deliverable"):
                    ranked.append(cand)
                    candidate_to_probe = cand
                    discovery_source = "SMTP_PROBED"
                    break

        # 5. Evaluate primary candidate
        primary_email: Optional[str] = None
        confidence = 0.0
        deliverability_status = "UNDELIVERABLE"
        is_role = False

        if candidate_to_probe and has_mx:
            primary_email = candidate_to_probe
            smtp_code = None
            if probe_smtp and mx_hosts:
                probe_res = verify_email_smtp(primary_email, mx_hosts)
                smtp_code = probe_res.get("smtp_code")

            confidence, deliverability_status, is_role = compute_email_confidence(
                source=discovery_source,
                has_valid_mx=has_mx,
                is_catchall=catchall,
                smtp_code=smtp_code,
                email=primary_email,
            )

        return EnrichmentResult(
            company_id=company_id,
            domain=clean_domain,
            primary_email=primary_email,
            all_emails=ranked,
            discovery_source=discovery_source,
            deliverability_status=deliverability_status,
            confidence_score=confidence,
            is_catchall=catchall,
            is_role_account=is_role,
            tech_stack=tech_stack,
            cms_detected=cms_detected,
            ssl_valid=ssl_valid,
            site_speed_ms=site_speed_ms,
            http_status_code=http_status_code,
        )

    @staticmethod
    async def enrich_companies_batch(
        companies: List[Dict[str, Any]],
        probe_smtp: bool = True,
    ) -> List[EnrichmentResult]:
        """
        Coordinates asynchronous crawling and enrichment for a batch of companies.
        """
        if not companies:
            return []

        crawler = AsyncEmailWebCrawler()
        try:
            urls = [c.get("website", "") for c in companies]
            crawl_results = await crawler.scrape_batch(urls)

            outcomes = []
            for company, crawl_res in zip(companies, crawl_results):
                comp_id = company["id"]
                domain = company.get("domain") or crawl_res.get("domain", "")
                enrich_res = EmailEnrichmentEngine.process_discovered_emails(
                    company_id=comp_id,
                    domain=domain,
                    crawl_results=crawl_res,
                    probe_smtp=probe_smtp,
                )
                outcomes.append(enrich_res)
            return outcomes
        finally:
            await crawler.close()


email_enrichment_engine = EmailEnrichmentEngine()
