"""
Website crawl source.

Crawls the websites of organizations found by other sources (SSRF-checked by `SafeWebsiteCrawler`, robots.txt
honoured for the root and every followed link) and extracts phones, emails (labelled `found`), leadership/team
members and links to social profiles. Input comes from `intent.filters["crawl_targets"]` (url, org_id, name) or the
older `crawl_urls` / `crawl_domains` lists.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import Any, AsyncIterator, Dict, List, Optional, Set

import httpx

from packages.discovery.http import BOT_USER_AGENT
from packages.discovery.models import (
    Budget,
    EmailEntry,
    FactRecord,
    OrgRecord,
    PersonRecord,
    PhoneEntry,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.discovery.names import looks_like_person
from packages.discovery.robots import RobotsRules, get_robots
from packages.discovery.sources.base import SourceAdapter
from packages.leadintel.deduplication import clean_domain, normalize_string
from packages.leadintel.parser import TeamPageParser
from packages.leadintel.phone_finder import PhoneFinder
from packages.scrapers.google_maps.src.gmaps_scraper.website.crawler import SafeWebsiteCrawler

logger = logging.getLogger("discovery.source.website_crawl")

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_JUNK_EMAIL_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
_JUNK_EMAIL_DOMAINS = {"example.com", "domain.com", "sentry.io", "wixpress.com", "schema.org", "yourdomain.com",
                       "email.com", "test.com", "sentry-next.wixpress.com"}
_SOCIAL_HOSTS = {"facebook.com": "facebook", "instagram.com": "instagram", "twitter.com": "twitter",
                 "x.com": "twitter", "youtube.com": "youtube", "linkedin.com": "linkedin"}
CRAWL_CONCURRENCY = 6


class _RobotsAwareCrawler(SafeWebsiteCrawler):
    """SafeWebsiteCrawler that never follows a link disallowed by robots.txt."""

    def __init__(self, rules: RobotsRules, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._rules = rules

    def _extract_internal_links(self, html: str, base_url: str, root_domain: str) -> List[str]:
        links = super()._extract_internal_links(html, base_url, root_domain)
        return [link for link in links if self._rules.can_fetch(link, self.user_agent)]


def _published_phones(html: str) -> List[str]:
    found = re.findall(r'href=["\']tel:([^"\'?#]+)', html, flags=re.I)
    found += re.findall(r'"telephone"\s*:\s*"([^"]{7,30})"', html, flags=re.I)
    return [urllib.parse.unquote(f).strip() for f in found]


def _social_links(html: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.I):
        host = (urllib.parse.urlsplit(href).hostname or "").lower().removeprefix("www.")
        for suffix, label in _SOCIAL_HOSTS.items():
            if host == suffix or host.endswith("." + suffix):
                path = urllib.parse.urlsplit(href).path.strip("/")
                if path and not path.startswith(("sharer", "share", "intent", "plugins", "tr", "login")):
                    found.setdefault(label, href.split("?")[0].rstrip("/"))
    return found


def _targets(intent: SearchIntent) -> List[Dict[str, str]]:
    f = intent.filters or {}
    targets: List[Dict[str, str]] = list(f.get("crawl_targets") or [])
    if not targets:
        urls = list(f.get("crawl_urls") or [])
        urls += [d if str(d).startswith("http") else f"https://{d}" for d in (f.get("crawl_domains") or [])]
        targets = [{"url": u} for u in urls]
    return targets


class WebsiteCrawlSource(SourceAdapter):
    def __init__(self, name: str = "website_crawl", max_domains: int = 12, max_pages: int = 3) -> None:
        super().__init__(name=name, source_type="crawler", weight=1.3)
        self.max_domains = max_domains
        self.max_pages = max_pages
        self.team_parser = TeamPageParser()
        self.phone_finder = PhoneFinder()

    async def _crawl_one(self, target: Dict[str, str], client: httpx.AsyncClient, budget: Budget) -> Optional[Dict[str, Any]]:
        url = target["url"]
        if not url.startswith("http"):
            url = f"https://{url}"
        rules = await get_robots(url)
        if not rules.can_fetch(url):
            return {"skipped": "robots", "url": url}
        crawler = _RobotsAwareCrawler(rules, max_pages=self.max_pages, timeout_seconds=4.0, user_agent=BOT_USER_AGENT)
        try:
            pages = await asyncio.wait_for(crawler.crawl(url, http_client=client), timeout=max(2.0, min(9.0, budget.remaining())))
        except Exception as exc:
            logger.debug("Crawl error for %s: %s", url, exc)
            return {"error": type(exc).__name__, "url": url}
        return {"url": url, "pages": list(pages.values()) if isinstance(pages, dict) else list(pages), "target": target}

    def _build(self, crawled: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        pages = crawled["pages"]
        if not pages:
            return None
        url, target = crawled["url"], crawled["target"]
        domain = clean_domain(url)
        site_emails: Dict[str, str] = {}
        site_phones: Dict[str, str] = {}
        team: List[Dict[str, Any]] = []
        social: Dict[str, str] = {}
        for page in pages:
            html = getattr(page, "html", "") or ""
            page_url = getattr(page, "url", url)
            # mailto links are often URL-encoded ("mailto:%20info@x.com"); decode first so "%20" is not read as "20"
            for match in EMAIL_REGEX.findall(urllib.parse.unquote(html)):
                em = match.lower().strip(".")
                if em.endswith(_JUNK_EMAIL_SUFFIX) or em.split("@")[-1] in _JUNK_EMAIL_DOMAINS:
                    continue
                site_emails.setdefault(em, page_url)
            # Only numbers the site publishes as a contact (tel: links, JSON-LD "telephone") are kept. Scanning the whole
            # text picks up other branches, partners and tracking numbers from footers.
            for raw in _published_phones(html):
                for ph in self.phone_finder.extract_from_text(raw, source_url=page_url):
                    if ph.get("e164"):
                        site_phones.setdefault(ph["e164"], page_url)
            social.update({k: v for k, v in _social_links(html).items() if k not in social})
            if any(k in page_url.lower() for k in ("about", "team", "leadership", "staff", "management", "who-we-are")):
                team.extend(self.team_parser.parse_team_members(html, source_url=page_url))

        name = target.get("name") or domain.split(".")[0].replace("-", " ").title()
        org = OrgRecord(
            id=target.get("org_id") or OrgRecord(name=name).id,
            name=name, canonical_name=name, normalized_name=normalize_string(name),
            website=url, domain=domain,
            phones=[PhoneEntry(number=n, source_url=u) for n, u in list(site_phones.items())[:2]],
            emails=[EmailEntry(value=e, label="found", confidence=0.95 if e.split("@")[-1].endswith(domain) else 0.7,
                               source_url=u) for e, u in list(site_emails.items())[:8]],
            social={k: v for k, v in social.items()},
            sources=[{"source": self.name, "url": url, "pages_crawled": len(pages)}],
            first_seen_source=self.name, quality_score=0.85,
        )
        facts = [FactRecord(entity_type="organization", entity_id=org.id, field="website", value=url,
                            source=self.name, source_url=url, confidence=0.95)]
        for e in org.emails:
            facts.append(FactRecord(entity_type="organization", entity_id=org.id, field="email",
                                    value=e.value, source=self.name, source_url=e.source_url, confidence=e.confidence))
        people: List[PersonRecord] = []
        seen: Set[str] = set()
        for member in team:
            p_name = (member.get("full_name") or "").strip()
            if not looks_like_person(p_name, [name]) or p_name.lower() in seen:
                continue
            seen.add(p_name.lower())
            person = PersonRecord(
                name=p_name, full_name=p_name, normalized_name=normalize_string(p_name), title=member.get("title"),
                role_type=member.get("role_type"), org_id=org.id, org_name=name,
                profile_urls=[member["source_url"]] if member.get("source_url") else [],
                emails=[EmailEntry(value=em, label="found", confidence=0.9, source_url=member.get("source_url"))
                        for em in member.get("emails", [])],
                phones=[PhoneEntry(number=p, source_url=member.get("source_url")) for p in member.get("phones", [])],
                provenance="website_crawl", verified=False, confidence=0.75, source_url=member.get("source_url"),
            )
            people.append(person)
            org.people.append(person)
            facts.append(FactRecord(entity_type="person", entity_id=person.id, field="title", value=member.get("title"),
                                    source=self.name, source_url=member.get("source_url"), confidence=0.75))
        return {"org": org, "people": people, "facts": facts}

    async def _execute_search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        targets = _targets(intent)[: self.max_domains]
        if not targets:
            yield SourceResult(source=self.name, status=SourceStatus(
                source=self.name, status="empty", count=0, message="No website URLs to crawl"))
            return

        sem = asyncio.Semaphore(CRAWL_CONCURRENCY)
        total_orgs = total_people = 0
        skipped_robots = failed = 0

        async with httpx.AsyncClient(timeout=4.0, follow_redirects=False, verify=True,
                                     headers={"User-Agent": BOT_USER_AGENT}) as client:
            async def work(t: Dict[str, str]) -> Optional[Dict[str, Any]]:
                async with sem:
                    if budget.is_expired():
                        return None
                    return await self._crawl_one(t, client, budget)

            tasks = [asyncio.create_task(work(t)) for t in targets]
            try:
                for coro in asyncio.as_completed(tasks):
                    crawled = await coro
                    if not crawled:
                        continue
                    if crawled.get("skipped") == "robots":
                        skipped_robots += 1
                        continue
                    if crawled.get("error"):
                        failed += 1
                        continue
                    built = self._build(crawled)
                    if not built:
                        continue
                    total_orgs += 1
                    total_people += len(built["people"])
                    # Stream each site as soon as it is done so a timeout keeps what was already found.
                    yield SourceResult(
                        source=self.name,
                        status=SourceStatus(source=self.name, status="ok", count=1 + len(built["people"])),
                        organizations=[built["org"]], people=built["people"], facts=built["facts"],
                    )
            finally:
                for t_ in tasks:
                    if not t_.done():
                        t_.cancel()

        notes = []
        if skipped_robots:
            notes.append(f"{skipped_robots} site(s) skipped by robots.txt")
        if failed:
            notes.append(f"{failed} site(s) unreachable")
        yield SourceResult(
            source=self.name,
            status=SourceStatus(source=self.name, status="ok" if total_orgs else "empty",
                                count=total_orgs + total_people, message="; ".join(notes) or None),
        )