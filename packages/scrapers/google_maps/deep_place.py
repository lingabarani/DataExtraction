"""
Deep place extraction for Google Maps places.

Collects, for one place: details (hours, attributes/services, rating), ALL reviews
(paginated), and, when the place has a website, contacts, people and services from
the site. Optional LLM steps add review sentiment/topics and extract people and
services from unstructured page text.

Design notes
  * Pure helpers (dates, hashing, row building, regex contacts) have no I/O so they
    are unit-testable without network or database.
  * Network code reuses the existing scraper pieces: HttpClient (block detection,
    identity rotation), build_boq_reviews_url / parse_reviews_response,
    parse_place_details_response, SafeWebsiteCrawler (SSRF safe), WebsiteExtractor.
  * A CAPTCHA/consent block is reported as `blocked`; nothing tries to bypass it.
  * The LLM is optional. Without it every step falls back to regex or is skipped.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("dataextraction.gmaps.deep_place")

REVIEWER_MODES = ("hash", "plain")


# ══════════════════════════════════════════════════════════════════════════════
# Pure helpers
# ══════════════════════════════════════════════════════════════════════════════

_REL_RE = re.compile(
    r"(?P<num>a|an|\d+)\s+(?P<unit>second|minute|hour|day|week|month|year)s?\s+ago", re.IGNORECASE
)
_UNIT_DAYS = {"second": 1 / 86400, "minute": 1 / 1440, "hour": 1 / 24, "day": 1,
              "week": 7, "month": 30.4375, "year": 365.25}


def parse_relative_date(text: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    """'2 weeks ago', 'a month ago', 'Edited 3 years ago' -> absolute UTC datetime (approximate)."""
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    low = text.strip().lower()
    if low in ("just now", "now", "today"):
        return now
    if low == "yesterday":
        return now - timedelta(days=1)
    m = _REL_RE.search(low)
    if not m:
        return None
    num = 1 if m.group("num") in ("a", "an") else int(m.group("num"))
    days = num * _UNIT_DAYS[m.group("unit").lower()]
    return now - timedelta(days=days)


def reviewer_mode() -> str:
    mode = os.getenv("REVIEWER_NAME_MODE", "hash").strip().lower()
    if mode not in REVIEWER_MODES:
        raise ValueError(f"REVIEWER_NAME_MODE must be one of {REVIEWER_MODES}, got '{mode}'")
    return mode


def _hash_key() -> bytes:
    key = os.getenv("REVIEWER_HASH_SALT") or os.getenv("SECRETS_MASTER_KEY") or ""
    if not key:
        raise ValueError(
            "REVIEWER_NAME_MODE=hash needs REVIEWER_HASH_SALT (or SECRETS_MASTER_KEY) so names "
            "cannot be recovered by guessing."
        )
    return key.encode("utf-8")


def hash_reviewer_name(name: str, key: Optional[bytes] = None) -> str:
    """Keyed HMAC-SHA256 of the normalised name (64 hex chars)."""
    return hmac.new(key or _hash_key(), name.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()


def reviewer_identity(name: Optional[str], reviewer_id: Optional[str], mode: str,
                      key: Optional[bytes] = None) -> Dict[str, Optional[str]]:
    """Return the reviewer fields to store for the given privacy mode."""
    clean = (name or "").strip()
    if not clean or clean.lower() == "anonymous":
        return {"reviewer_name": None, "reviewer_name_hash": None, "reviewer_id": None}
    if mode == "plain":
        return {"reviewer_name": clean, "reviewer_name_hash": None, "reviewer_id": reviewer_id}
    return {"reviewer_name": None, "reviewer_name_hash": hash_reviewer_name(clean, key), "reviewer_id": None}


def build_review_row(rev: Dict[str, Any], place_id: str, run_id: str, mode: str,
                     source_url: Optional[str] = None, key: Optional[bytes] = None,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    """Convert a parse_reviews_response() dict into a place_reviews row."""
    published: Optional[datetime] = None
    ts_ms = rev.get("timestamp_ms")
    if ts_ms:
        try:
            # Google returns microseconds for some responses and milliseconds for others.
            ts = int(ts_ms)
            ts = ts / 1_000_000 if ts > 10**14 else ts / 1000
            published = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            published = None
    if published is None:
        published = parse_relative_date(rev.get("relative_date"), now)

    ident = reviewer_identity(rev.get("author_name"), rev.get("author_id"), mode, key)
    photos = rev.get("photos_json") or "[]"
    return {
        "place_id": place_id,
        "review_id": str(rev["review_id"]),
        **ident,
        "rating": rev.get("rating"),
        "review_text": rev.get("text"),
        "language": rev.get("language"),
        "published_at": published,
        "relative_date": rev.get("relative_date"),
        "owner_response_text": rev.get("owner_response_text"),
        "owner_response_date": rev.get("owner_response_date"),
        "reaction_count": rev.get("reaction_count") or 0,
        "photo_urls": photos if isinstance(photos, str) else json.dumps(photos),
        "source_url": source_url,
        "run_id": run_id,
    }


def attributes_to_service_rows(attributes: Iterable[Dict[str, Any]], place_id: str, run_id: str,
                               source_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """Google 'attributes' (amenities, service options, payments...) -> place_services rows."""
    rows, seen = [], set()
    for a in attributes or []:
        name = (a.get("attribute_name") or "").strip()
        if not name:
            continue
        group = (a.get("group_name") or "").strip()
        key = (group, name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "place_id": place_id, "group_name": group, "service_name": name,
            "is_enabled": bool(a.get("is_enabled", True)),
            "display_value": a.get("display_value"), "origin": "attribute",
            "source_url": source_url, "run_id": run_id,
        })
    return rows


# ── contacts from page HTML (no LLM) ─────────────────────────────────────────

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?[2-9]\d{2}[-.\s]?\d{4}|\+?52[-.\s]?\(?\d{2,3}\)?[-.\s]?\d{4}[-.\s]?\d{4}"
)
_SOCIAL_HOSTS = ("facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
                 "youtube.com", "tiktok.com", "pinterest.com", "yelp.com", "wa.me")
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_EMAIL_JUNK_DOMAINS = {"example.com", "domain.com", "sentry.io", "wixpress.com", "schema.org",
                       "test.com", "sample.com", "yourcompany.com", "email.com"}
_EMAIL_JUNK_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")


def html_to_text(html: str, limit: int = 20000) -> str:
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>|<style[^>]*>[\s\S]*?</style>|<svg[^>]*>[\s\S]*?</svg>",
                  " ", html or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def regex_contacts(pages: Dict[str, str]) -> List[Dict[str, Any]]:
    """Emails, phones and social links from {url: html}. Deduplicated."""
    out: List[Dict[str, Any]] = []
    seen: set = set()

    def add(ctype: str, value: str, label: Optional[str], url: str) -> None:
        key = (ctype, value)
        if key in seen:
            return
        seen.add(key)
        out.append({"contact_type": ctype, "value": value, "label": label,
                    "extraction_method": "regex", "source_url": url})

    for url, html in pages.items():
        text = html_to_text(html)
        mailto = re.findall(r'href=["\']mailto:([^"\'?]+)', html or "", flags=re.IGNORECASE)
        for em in set(e.strip().lower() for e in mailto + _EMAIL_RE.findall(text)):
            domain = em.split("@")[-1]
            if domain in _EMAIL_JUNK_DOMAINS or em.endswith(_EMAIL_JUNK_SUFFIX) or "@" not in em:
                continue
            add("email", em, "general", url)
        for tel in re.findall(r'href=["\']tel:([+0-9\s().-]+)["\']', html or "", flags=re.IGNORECASE):
            digits = re.sub(r"[^\d+]", "", tel)
            if len(re.sub(r"\D", "", digits)) >= 10:
                add("phone", digits, "office", url)
        for ph in _PHONE_RE.findall(text):
            digits = re.sub(r"[^\d+]", "", ph)
            if len(re.sub(r"\D", "", digits)) >= 10:
                add("phone", digits, "office", url)
        for href in _HREF_RE.findall(html or ""):
            host = (urllib.parse.urlsplit(href).hostname or "").lower().removeprefix("www.")
            if host and any(host == h or host.endswith("." + h) for h in _SOCIAL_HOSTS):
                add("social", href.split("?")[0].rstrip("/"), host, url)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# LLM steps (optional)
# ══════════════════════════════════════════════════════════════════════════════

class _Person(BaseModel):
    full_name: str
    role_title: str = ""
    email: Optional[str] = None
    phone: Optional[str] = None


class SiteFacts(BaseModel):
    people: List[_Person] = Field(default_factory=list)
    services: List[str] = Field(default_factory=list)


class _ReviewInsight(BaseModel):
    review_id: str
    sentiment: str = "neutral"  # positive | neutral | negative | mixed
    topics: List[str] = Field(default_factory=list)


class ReviewInsights(BaseModel):
    items: List[_ReviewInsight] = Field(default_factory=list)


_VALID_SENTIMENT = {"positive", "neutral", "negative", "mixed"}


def llm_site_facts(llm: Any, business_name: str, pages: Dict[str, str]) -> SiteFacts:
    """Ask the LLM for named people (with roles) and services found in page text."""
    parts, budget = [], 9000
    for url, html in pages.items():
        chunk = html_to_text(html, limit=3000)
        if not chunk:
            continue
        parts.append(f"[{url}]\n{chunk}")
        budget -= len(chunk)
        if budget <= 0:
            break
    if not parts:
        return SiteFacts()
    messages = [
        {"role": "system", "content": (
            "You extract facts from a business website. Only report people who are explicitly named "
            "in the text with a person's full name. Never invent names, emails or phones. "
            "List the services or products the business offers as short phrases.")},
        {"role": "user", "content": f"Business: {business_name}\n\n" + "\n\n".join(parts)},
    ]
    result = llm.chat(messages, schema=SiteFacts, max_tokens=2000, purpose="place_site_facts")
    facts: SiteFacts = result.parsed  # type: ignore[assignment]
    # Guard against hallucination: keep only names that literally appear in the crawled text.
    haystack = " ".join(html_to_text(h, limit=40000) for h in pages.values()).lower()
    facts.people = [p for p in facts.people if p.full_name and p.full_name.strip().lower() in haystack]
    return facts


def llm_review_insights(llm: Any, reviews: List[Dict[str, Any]], batch_size: int = 20) -> Dict[str, Dict[str, Any]]:
    """Return {review_id: {"sentiment": str, "topics": [..]}} for reviews that have text."""
    out: Dict[str, Dict[str, Any]] = {}
    texts = [r for r in reviews if (r.get("review_text") or "").strip()]
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = "\n".join(f"{r['review_id']}: {(r['review_text'] or '')[:400]}" for r in batch)
        messages = [
            {"role": "system", "content": (
                "Classify each customer review. For each line 'id: text' return its id, a sentiment "
                "(positive, neutral, negative or mixed) and up to 3 short topic tags such as 'service', "
                "'price', 'cleanliness', 'staff'.")},
            {"role": "user", "content": payload},
        ]
        res = llm.chat(messages, schema=ReviewInsights, max_tokens=2500, purpose="place_review_insights")
        valid_ids = {str(r["review_id"]) for r in batch}
        for item in res.parsed.items:  # type: ignore[union-attr]
            if item.review_id in valid_ids:
                sent = item.sentiment.lower() if item.sentiment.lower() in _VALID_SENTIMENT else "neutral"
                out[item.review_id] = {"sentiment": sent, "topics": [t[:40] for t in item.topics[:3]]}
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Orchestration for one place
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlaceBundle:
    place_id: str
    details: Dict[str, Any] = field(default_factory=dict)
    services: List[Dict[str, Any]] = field(default_factory=list)
    reviews: List[Dict[str, Any]] = field(default_factory=list)
    contacts: List[Dict[str, Any]] = field(default_factory=list)
    people: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "complete"          # complete | partial | blocked
    notes: List[str] = field(default_factory=list)


def _is_blocked(resp: Any) -> bool:
    try:
        from gmaps_scraper.http import _is_blocked_response
        return bool(_is_blocked_response(resp))
    except Exception:
        return getattr(resp, "status_code", 200) in (429, 503)


class DeepPlaceExtractor:
    """Extract everything for one place. All dependencies are injectable for testing."""

    def __init__(self, http_client: Any, *, run_id: str, mode: Optional[str] = None,
                 max_reviews: Optional[int] = None, llm: Any = None, crawler: Any = None,
                 hl: str = "en", gl: str = "us", page_size: int = 10,
                 suppressed: Optional[Callable[[Optional[str]], bool]] = None):
        self.suppressed = suppressed or (lambda _v: False)
        self.http = http_client
        self.run_id = run_id
        self.mode = mode or reviewer_mode()
        self.key = _hash_key() if self.mode == "hash" else None
        self.max_reviews = int(os.getenv("MAX_REVIEWS_PER_PLACE", "500")) if max_reviews is None else max_reviews
        self.llm = llm
        self.crawler = crawler
        self.hl, self.gl, self.page_size = hl, gl, page_size

    async def fetch_details(self, stub: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        from gmaps_scraper.details import parse_place_details_response
        lat, lng = stub.get("latitude"), stub.get("longitude")
        if lat is None or lng is None:
            return {}, False
        pb = f"!4m8!1m3!1d500!2d{lng}!3d{lat}!3m2!1i1024!2i768!4f13.1!7i20!10b1"
        url = (f"https://www.google.com/search?tbm=map&authuser=0&hl={self.hl}&gl={self.gl}"
               f"&pb={pb}&q={urllib.parse.quote(stub.get('name') or '')}")
        resp = await self.http.get(url)
        if _is_blocked(resp):
            return {}, True
        return parse_place_details_response(resp.text, stub["cid"]), False

    async def fetch_reviews(self, ftid: str, cid: str) -> Tuple[List[Dict[str, Any]], bool]:
        from gmaps_scraper.reviews import build_boq_reviews_url, parse_reviews_response
        collected: List[Dict[str, Any]] = []
        seen: set = set()
        token: Optional[str] = None
        blocked = False
        limit = self.max_reviews if self.max_reviews > 0 else 10**9
        while len(collected) < limit:
            url = build_boq_reviews_url(ftid, page_size=self.page_size, sort_code=1, pagination_token=token)
            resp = await self.http.get(url)
            if _is_blocked(resp):
                blocked = True
                break
            parsed, next_token = parse_reviews_response(resp.text, cid)
            fresh = [r for r in parsed if r["review_id"] not in seen]
            if not fresh:
                break
            for r in fresh:
                seen.add(r["review_id"])
                collected.append(r)
                if len(collected) >= limit:
                    break
            if not next_token or next_token == token:
                break
            token = next_token
        return collected, blocked

    async def crawl_website(self, website: str) -> Dict[str, str]:
        """Return {url: html}. The crawler enforces SSRF rules and size limits."""
        crawler = self.crawler
        if crawler is None:
            from gmaps_scraper.website.crawler import SafeWebsiteCrawler
            crawler = SafeWebsiteCrawler(max_pages=int(os.getenv("PLACE_SITE_MAX_PAGES", "6")))
        pages = await crawler.crawl(website)
        return {u: (p.html if hasattr(p, "html") else str(p)) for u, p in pages.items()}

    async def extract_place(self, stub: Dict[str, Any]) -> PlaceBundle:
        cid = str(stub["cid"])
        bundle = PlaceBundle(place_id=cid)
        source_url = f"https://www.google.com/maps/place/?q=place_id:{stub.get('place_id') or cid}"

        # 1. details + services
        try:
            details, blocked = await self.fetch_details(stub)
        except Exception as exc:
            details, blocked = {}, False
            bundle.notes.append(f"details failed: {type(exc).__name__}")
            bundle.status = "partial"
        if blocked:
            bundle.status = "blocked"
            bundle.notes.append("details blocked by CAPTCHA/consent wall")
            return bundle
        bundle.details = details
        bundle.services = attributes_to_service_rows(details.get("attributes", []), cid, self.run_id, source_url)

        # 2. reviews
        ftid = stub.get("ftid")
        if ftid:
            try:
                raw_reviews, blocked = await self.fetch_reviews(ftid, cid)
            except Exception as exc:
                raw_reviews, blocked = [], False
                bundle.notes.append(f"reviews failed: {type(exc).__name__}")
                bundle.status = "partial"
            # GDPR/CCPA: a suppressed person is dropped before anything is stored or hashed.
            raw_reviews = [r for r in raw_reviews if not self.suppressed(r.get("author_name"))]
            bundle.reviews = [build_review_row(r, cid, self.run_id, self.mode, source_url, self.key)
                              for r in raw_reviews]
            if blocked:
                bundle.status = "blocked" if not bundle.reviews else "partial"
                bundle.notes.append("reviews blocked by CAPTCHA/consent wall")
        else:
            bundle.notes.append("no ftid; reviews skipped")

        # 3. website contacts, people, services
        website = stub.get("website")
        pages: Dict[str, str] = {}
        if website:
            try:
                pages = await self.crawl_website(website)
            except Exception as exc:
                bundle.notes.append(f"website crawl failed: {type(exc).__name__}")
        if pages:
            for c in regex_contacts(pages):
                bundle.contacts.append({**c, "place_id": cid, "run_id": self.run_id})
            bundle.people.extend(self._people_from_extractor(stub, pages, cid))

        # 4. optional LLM enrichment (never blocks the scrape)
        if self.llm is not None:
            if pages:
                try:
                    facts = llm_site_facts(self.llm, stub.get("name") or "", pages)
                    for p in facts.people:
                        bundle.people.append({
                            "place_id": cid, "full_name": p.full_name.strip(), "role_title": p.role_title.strip(),
                            "email": p.email, "phone": p.phone, "profile_url": None,
                            "extraction_method": "llm", "source_url": website, "run_id": self.run_id})
                    for svc in facts.services:
                        bundle.services.append({
                            "place_id": cid, "group_name": "website", "service_name": svc.strip()[:200],
                            "is_enabled": True, "display_value": None, "origin": "llm",
                            "source_url": website, "run_id": self.run_id})
                except Exception as exc:
                    bundle.notes.append(f"llm site facts skipped: {type(exc).__name__}")
            if bundle.reviews:
                try:
                    insights = llm_review_insights(self.llm, bundle.reviews)
                    for r in bundle.reviews:
                        ins = insights.get(r["review_id"])
                        if ins:
                            r["sentiment"], r["topics"] = ins["sentiment"], ins["topics"]
                except Exception as exc:
                    bundle.notes.append(f"llm review insights skipped: {type(exc).__name__}")

        for p in bundle.people:
            if not p.get("run_id"):
                p["run_id"] = self.run_id
        # Suppression applies to people and contact values as well.
        bundle.people = [p for p in bundle.people
                         if not (self.suppressed(p.get("full_name")) or self.suppressed(p.get("email"))
                                 or self.suppressed(p.get("phone")))]
        bundle.contacts = [c for c in bundle.contacts
                           if not (c["contact_type"] in ("email", "phone") and self.suppressed(c["value"]))]
        bundle.people = _dedupe_people(bundle.people)
        bundle.services = _dedupe_services(bundle.services)
        return bundle

    @staticmethod
    def _people_from_extractor(stub: Dict[str, Any], pages: Dict[str, str], cid: str) -> List[Dict[str, Any]]:
        """Leadership found by the existing rule-based WebsiteExtractor."""
        try:
            from gmaps_scraper.website.crawler import PageResponse
            from gmaps_scraper.website.extractor import WebsiteExtractor
            page_objs = {u: PageResponse(u, 200, h) for u, h in pages.items()}
            extracted = WebsiteExtractor.extract({"name": stub.get("name"), "category": stub.get("category")},
                                                 page_objs)
        except Exception as exc:
            logger.debug("WebsiteExtractor unavailable: %s", exc)
            return []
        rows = []
        for leader in extracted.get("leaders", []):
            if not leader.get("full_name"):
                continue
            rows.append({
                "place_id": cid, "full_name": leader["full_name"], "role_title": leader.get("title") or "",
                "email": None, "phone": None, "profile_url": None, "extraction_method": "regex",
                "source_url": leader.get("source_url"), "run_id": None,
            })
        return rows


def _dedupe_people(people: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for p in people:
        key = (p["full_name"].strip().lower(), (p.get("role_title") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _dedupe_services(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for s in services:
        key = ((s.get("group_name") or "").lower(), s["service_name"].strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
