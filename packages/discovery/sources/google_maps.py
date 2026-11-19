"""
Google Maps discovery source.

Uses the project's existing Google Maps search protocol (`gmaps_scraper.search`) for one text query per search center.
Centers come from the resolved geography (principal cities of a metro area, the city, county or ZIP centroid); there
is no default location. A CAPTCHA, consent wall or HTTP 429/503 marks the source `blocked` and is never worked around.
Details, services and reviews for the places found here are collected afterwards by the deep place pipeline
(`POST /api/v1/places/extract`); this source only discovers places.

Google's terms of service restrict automated access to Maps. The operator is responsible for that risk; the source can
be disabled with DISCOVERY_DISABLE_GOOGLE_MAPS=true.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import urllib.parse
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

import httpx

from packages.discovery.http import paced_request
from packages.discovery.models import (
    Budget,
    FactRecord,
    OrgRecord,
    PhoneEntry,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.leadintel.deduplication import clean_domain, normalize_string
from packages.scrapers.google_maps.src.gmaps_scraper.models import PlaceStub
from packages.scrapers.google_maps.src.gmaps_scraper.search import build_search_pb, parse_search_rpc_response

logger = logging.getLogger("discovery.source.google_maps")

MAX_CENTERS = 3
MAX_QUERIES = 2
PAGE_SIZE = 20          # results per Google Maps request
MAX_PAGES = 5           # pages per (query, center); page 2+ is requested only when page 1 was full
MAX_REQUESTS = 24       # hard cap per search, to stay polite and fast
RATE_BUCKET = "discovery_gmaps"  # config/rate_limits.yaml
_CONSENT_COOKIE = "SOCS=CAISHAgBEhJnd3NfMjAyNDA2MTAtMF9SQzEaAmVuIAEaBgiA_LyuBg"
_BLOCK_SIGNALS = ("sorry/index", "recaptcha", "unusual traffic", "automated queries", "/sorry?")


def _is_blocked(resp: httpx.Response) -> bool:
    if resp.status_code in (429, 503):
        return True
    if any(sig in str(resp.url).lower() for sig in _BLOCK_SIGNALS):
        return True
    try:
        head = resp.text[:2048].lower()
    except Exception:
        return False
    return any(sig in head for sig in _BLOCK_SIGNALS)


def parse_us_address(address: Optional[str]) -> Dict[str, str]:
    """"219 Greenwich Rd, Charlotte, NC 28211" -> street/city/state/postal_code (missing parts stay empty)."""
    out = {"street": address or "", "city": "", "state": "", "postal_code": ""}
    if not address:
        return out
    m = re.match(r"^(?P<street>.+?),\s*(?P<city>[^,]+),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5})(?:-\d{4})?(?:,.*)?$", address.strip())
    if m:
        out.update(street=m.group("street").strip(), city=m.group("city").strip(), state=m.group("state"),
                   postal_code=m.group("zip"))
    return out


def clean_website(url: Optional[str]) -> Optional[str]:
    """Drop tracking query strings (utm_*, gclid) but keep the page."""
    if not url:
        return None
    parts = urllib.parse.urlsplit(url)
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if not k.lower().startswith(("utm_", "gclid", "fbclid"))]
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(kept), ""))


def search_centers(geo: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Search centers (name, lat, lng) from the resolved geography. Empty when none can be derived."""
    centers = [c for c in (geo.get("centers") or []) if c.get("lat") is not None and c.get("lng") is not None]
    if not centers and geo.get("lat") is not None and geo.get("lng") is not None:
        centers = [{"name": geo.get("city") or geo.get("name") or "", "lat": geo["lat"], "lng": geo["lng"]}]
    return centers[:MAX_CENTERS]


def pages_per_job(max_results: int, n_jobs: int) -> int:
    """Pages per (query, center) so that about 1.5x the wanted results are fetched, within MAX_PAGES/MAX_REQUESTS."""
    n_jobs = max(1, n_jobs)
    wanted = math.ceil(max(1, max_results) * 1.5 / (PAGE_SIZE * n_jobs))
    return max(1, min(MAX_PAGES, wanted, MAX_REQUESTS // n_jobs))


class GoogleMapsSource:
    def __init__(self, name: str = "google_maps") -> None:
        self.name = name
        self.source_type = "scraper"
        self.weight = 1.2

    async def search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        async for res in self._execute_search(intent, budget):
            yield res

    async def _fetch_stubs(self, query: str, center: Dict[str, Any], state: str, span_m: int, budget: Budget,
                           offset: int = 0, country: str = "us") -> Tuple[List[PlaceStub], Optional[str], bool]:
        pb = build_search_pb(center["lat"], center["lng"], span_meters=span_m, num_results=PAGE_SIZE, offset=offset)
        place = f"{center.get('name', '')}, {state}".strip(" ,")
        gl = urllib.parse.quote(country or "us")
        url = (f"https://www.google.com/search?tbm=map&authuser=0&hl=en&gl={gl}&pb=" + pb + "&q="
               + urllib.parse.quote(f"{query} in {place}".strip()))
        try:
            resp = await paced_request(RATE_BUCKET, "GET", url, timeout=min(8.0, max(2.0, budget.remaining())),
                                       headers={"Cookie": _CONSENT_COOKIE, "Accept-Language": "en-US,en;q=0.9"})
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            return [], f"Network unavailable: {exc.__class__.__name__}", False
        except httpx.TimeoutException:
            return [], "Google Maps request timed out", False
        except Exception as exc:
            return [], f"Request error: {exc.__class__.__name__}", False
        if _is_blocked(resp):
            return [], f"HTTP {resp.status_code} or CAPTCHA/consent wall", True
        if resp.status_code != 200:
            return [], f"HTTP {resp.status_code}", False
        try:
            return parse_search_rpc_response(resp.text), None, False
        except Exception as exc:
            return [], f"Unparseable response ({exc.__class__.__name__}); Google may have changed the format", False

    async def _execute_search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        if os.getenv("DISCOVERY_DISABLE_GOOGLE_MAPS", "false").lower() == "true":
            yield SourceResult(status=SourceStatus(name=self.name, status="unavailable",
                                                   message="Disabled by DISCOVERY_DISABLE_GOOGLE_MAPS"))
            return
        geo = intent.geography or {}
        centers = search_centers(geo)
        if not centers:
            yield SourceResult(status=SourceStatus(
                name=self.name, status="unavailable",
                message="No coordinates for this location (state-level searches are not supported by Google Maps discovery)"))
            return

        queries = (intent.categories or [intent.query])[:MAX_QUERIES]
        state = geo.get("state") or ""
        country = (geo.get("country_code") or "us").lower()
        span_m = int(float(geo.get("radius_km", 20)) * 1000)
        jobs = [(q, c) for q in queries for c in centers]
        pages = pages_per_job(int((intent.filters or {}).get("max_results", 50) or 50), len(jobs))

        seen_places: Set[str] = set()
        seen_keys: Set[str] = set()
        errors: List[str] = []
        blocked = False
        total = 0
        full_jobs: List[bool] = []

        # Round 1: first page of every (query, center). Round 2: further pages only where page 1 was full.
        rounds: List[List[Tuple[str, Dict[str, Any], int]]] = [[(q, c, 0) for q, c in jobs]]
        for round_no in range(2):
            if round_no == 1:
                if blocked or pages <= 1 or budget.remaining() < 3.0:
                    break
                rounds.append([(q, c, p * PAGE_SIZE) for (q, c), full in zip(jobs, full_jobs) if full
                               for p in range(1, pages)])
                if not rounds[1]:
                    break
            batch_jobs = rounds[round_no]
            results = await asyncio.gather(*[self._fetch_stubs(q, c, state, span_m, budget, offset=o, country=country)
                                              for q, c, o in batch_jobs])
            new_stubs: List[PlaceStub] = []
            for found, err, was_blocked in results:
                blocked = blocked or was_blocked
                if err:
                    errors.append(err)
                for s in found:
                    pid = s.cid or s.place_id or s.name
                    if pid not in seen_places:
                        seen_places.add(pid)
                        new_stubs.append(s)
            if round_no == 0:
                full_jobs = [len(found) >= PAGE_SIZE for found, _, _ in results]
            orgs, facts = self._to_orgs(new_stubs, seen_keys, queries, state, country)
            total += len(orgs)
            if orgs:
                yield SourceResult(organizations=orgs, facts=facts)

        if blocked:
            status = "blocked"
        elif total:
            status = "ok"
        elif errors:
            status = "unavailable"
        else:
            status = "empty"
        yield SourceResult(status=SourceStatus(name=self.name, status=status, count=total,
                                               message=("; ".join(dict.fromkeys(errors))[:250] or None)))

    def _to_orgs(self, stubs: List[PlaceStub], seen: Set[str], queries: List[str], state: str, country: str = "us"
                 ) -> Tuple[List[OrgRecord], List[FactRecord]]:
        orgs: List[OrgRecord] = []
        facts: List[FactRecord] = []
        for stub in stubs:
            key = f"{normalize_string(stub.name)}|{stub.address or ''}"
            if key in seen:
                continue
            seen.add(key)
            maps_url = f"https://www.google.com/maps/place/?q=place_id:{stub.place_id or stub.cid}"
            phone = stub.phone_e164 or stub.phone
            website = clean_website(stub.website)
            if country == "us":
                addr = parse_us_address(stub.address or stub.street_address)
                # street_address sometimes holds the whole "street, city, ST zip" line: keep only the street part
                address = {"street": addr["street"] if addr["postal_code"] else (stub.street_address or addr["street"]),
                           "city": stub.city or addr["city"], "state": stub.region or addr["state"] or state,
                           "postal_code": stub.postal_code or addr["postal_code"], "country": "US"}
            else:
                # Address formats differ by country: keep Google's full address line as the street
                address = {"street": stub.address or stub.street_address or "", "city": stub.city or "",
                           "state": stub.region or "", "postal_code": stub.postal_code or "", "country": country.upper()}
            org = OrgRecord(
                name=stub.name, canonical_name=stub.name, normalized_name=normalize_string(stub.name),
                category=stub.category or (queries[0] if queries else None),
                address=address,
                latitude=stub.latitude, longitude=stub.longitude,
                phones=[PhoneEntry(number=phone, source_url=maps_url)] if phone else [],
                website=website, domain=clean_domain(website) if website else None,
                rating=stub.rating, review_count=stub.review_count,
                sources=[{"source": self.name, "place_id": stub.place_id, "cid": stub.cid, "url": maps_url}],
                first_seen_source=self.name, quality_score=0.85 if stub.website and phone else 0.7,
                metadata={"cid": stub.cid, "ftid": stub.ftid},
            )
            orgs.append(org)
            facts.append(FactRecord(entity_type="organization", entity_id=org.id, field="listing", value=stub.name,
                                    source=self.name, source_url=maps_url, confidence=0.9))
            if stub.rating is not None:
                facts.append(FactRecord(entity_type="organization", entity_id=org.id, field="rating", value=stub.rating,
                                        source=self.name, source_url=maps_url, confidence=0.9))
        return orgs, facts

    async def healthcheck(self) -> Dict[str, Any]:
        return {"source": self.name, "status": "unknown", "type": self.source_type,
                "note": "Probed lazily by real searches to avoid triggering rate limits"}
