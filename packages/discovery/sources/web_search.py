"""
Web Search Discovery Source Adapter.
Queries DuckDuckGo HTML (no key required by default), Brave Search, or Tavily API.
Extracts candidate organization websites and public LinkedIn profile/company references.
Aggregators (Yelp, Caring.com, etc.) are captured as sources rather than standalone organizations.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse
from bs4 import BeautifulSoup

from packages.discovery.http import get_bucket, get_http_client
from packages.discovery.models import (
    Budget,
    FactRecord,
    OrgRecord,
    PersonRecord,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.leadintel.deduplication import clean_domain, normalize_string

logger = logging.getLogger("discovery.source.web_search")

DIRECTORY_DOMAINS = {
    "yelp.com", "caring.com", "seniorly.com", "agingcare.com", "facebook.com",
    "yellowpages.com", "angi.com", "homeadvisor.com", "bbb.org", "mapquest.com",
    "healthgrades.com", "aplaceformom.com", "senioradvisor.com",
}


class WebSearchSource:
    def __init__(self, name: str = "web_search") -> None:
        self.name = name
        self.source_type = "search_engine"
        self.weight = 1.1

    async def search(
        self,
        intent: SearchIntent,
        budget: Budget,
    ) -> AsyncIterator[SourceResult]:
        async for res in self._execute_search(intent, budget):
            yield res

    async def _execute_search(
        self,
        intent: SearchIntent,
        budget: Budget,
    ) -> AsyncIterator[SourceResult]:
        geo = intent.geography or {}
        city = geo.get("city") or ""
        state = geo.get("state") or ""
        query_terms = intent.categories if intent.categories else [intent.query]
        primary_category = query_terms[0] if query_terms else intent.query

        if geo.get("search_text"):  # places outside the U.S.: search with the words the user typed
            city, state = geo["search_text"], ""
        loc_part = f"in {city} {state}".strip() if (city or state) else ""
        primary_query = f"{primary_category} {loc_part}".strip()

        orgs: List[OrgRecord] = []
        people: List[PersonRecord] = []
        facts: List[FactRecord] = []
        error_msg: Optional[str] = None
        status_code = "ok"

        # Check for paid API keys first in Key Vault
        brave_key = self._get_vault_key("brave") or os.environ.get("BRAVE_API_KEY")
        tavily_key = self._get_vault_key("tavily") or os.environ.get("TAVILY_API_KEY")

        results: List[Dict[str, str]] = []
        linkedin_query = f"site:linkedin.com/company {primary_category} {city} {state}".strip()
        try:
            if brave_key:
                batches = await asyncio.gather(self._search_brave(primary_query, brave_key, budget),
                                               self._search_brave(linkedin_query, brave_key, budget))
            elif tavily_key:
                batches = [await self._search_tavily(primary_query, tavily_key, budget)]
            else:
                batches = await asyncio.gather(self._search_duckduckgo(primary_query, budget),
                                               self._search_duckduckgo(linkedin_query, budget),
                                               return_exceptions=True)
                errs = [b for b in batches if isinstance(b, Exception)]
                if len(errs) == len(batches):
                    raise errs[0]
                batches = [b for b in batches if not isinstance(b, Exception)]
            seen_urls = set()
            for batch in batches:
                for r in batch:
                    if r.get("url") not in seen_urls:
                        seen_urls.add(r.get("url"))
                        results.append(r)
        except Exception as exc:
            error_msg = f"Search engine error: {exc}"[:250]
            status_code = "blocked" if "blocked" in str(exc).lower() else "unavailable"

        directory_listings: List[Dict[str, Any]] = []

        for res in results:
            url = res.get("url") or ""
            title = res.get("title") or ""
            snippet = res.get("snippet") or ""

            if not url or not title:
                continue
            if self._is_listicle(title, url):
                directory_listings.append({"source": "directory_listing", "domain": clean_domain(url), "url": url,
                                           "snippet": snippet, "title": title})
                continue

            # Check if LinkedIn profile snippet
            if "linkedin.com/in/" in url:
                parsed_person = self._parse_profile_snippet(title, snippet, url)
                if parsed_person:
                    p_rec = PersonRecord(
                        full_name=parsed_person["full_name"],
                        name=parsed_person["full_name"],
                        normalized_name=normalize_string(parsed_person["full_name"]),
                        title=parsed_person.get("title"),
                        role_type=self._classify_role(parsed_person.get("title")),
                        org_name=parsed_person.get("company"),
                        profile_urls=[url],
                        provenance="web_search",
                        source_url=url,
                    )
                    people.append(p_rec)
                    facts.append(
                        FactRecord(
                            entity_type="person",
                            entity_id=p_rec.id,
                            field="profile_url",
                            value=url,
                            source=self.name,
                            source_url=url,
                            confidence=0.85,
                        )
                    )
            elif "linkedin.com/company/" in url:
                comp_name = self._parse_company_title(title)
                org = OrgRecord(
                    name=comp_name,
                    canonical_name=comp_name,
                    normalized_name=normalize_string(comp_name),
                    category=primary_category,
                    social={"linkedin": url},
                    sources=[{"source": self.name, "url": url}],
                    quality_score=0.75,
                )
                orgs.append(org)
            else:
                domain = clean_domain(url)
                if not domain or domain in ("duckduckgo.com", "google.com", "bing.com"):
                    continue

                comp_name = self._brand_name(title, domain)
                # Check if this domain is an aggregator or directory
                is_directory = any(d in domain for d in DIRECTORY_DOMAINS)
                if is_directory:
                    # Directory/aggregator: record as reference source rather than independent org
                    directory_listings.append({
                        "source": "directory_listing",
                        "domain": domain,
                        "url": url,
                        "snippet": snippet,
                        "title": title,
                    })
                else:
                    org = OrgRecord(
                        name=comp_name,
                        canonical_name=comp_name,
                        normalized_name=normalize_string(comp_name),
                        category=primary_category,
                        website=url,
                        domain=domain,
                        sources=[{"source": self.name, "url": url, "snippet": snippet}],
                        quality_score=0.7,
                    )
                    orgs.append(org)

        # Attach directory listings as citation sources onto matching organizations
        for dir_item in directory_listings:
            dir_snippet_lower = dir_item["snippet"].lower()
            dir_title_lower = dir_item["title"].lower()
            for org in orgs:
                if org.name.lower() in dir_snippet_lower or org.name.lower() in dir_title_lower:
                    org.sources.append(dir_item)

        if not orgs and not people and status_code == "ok":
            status_code = "empty"
        if directory_listings and not error_msg:
            error_msg = f"{len(directory_listings)} directory/listicle page(s) kept only as references"

        yield SourceResult(
            source=self.name,
            status=SourceStatus(
                name=self.name,
                source=self.name,
                status=status_code,
                count=len(orgs) + len(people),
                error_message=error_msg,
            ),
            organizations=orgs,
            people=people,
            facts=facts,
        )

    async def _search_duckduckgo(self, query: str, budget: Budget) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        timeout = min(5.0, budget.remaining())
        client = get_http_client("discovery_web_search", timeout=timeout)

        try:
            await get_bucket("discovery_web_search").acquire()
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
            )
            if resp.status_code in (202, 403, 429) or "anomaly" in resp.text[:4000].lower():
                raise RuntimeError(f"DuckDuckGo blocked automated search (HTTP {resp.status_code})")
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for result_div in soup.select(".result"):
                    title_elem = result_div.select_one(".result__title a")
                    snippet_elem = result_div.select_one(".result__snippet")
                    if title_elem:
                        raw_href = title_elem.get("href", "")
                        clean_url = self._extract_ddg_url(raw_href)
                        title_text = title_elem.get_text(strip=True)
                        snippet_text = snippet_elem.get_text(strip=True) if snippet_elem else ""
                        if clean_url:
                            results.append({"title": title_text, "url": clean_url, "snippet": snippet_text})
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("DuckDuckGo HTML search failed: %s", exc)
            raise RuntimeError(f"DuckDuckGo unreachable ({exc.__class__.__name__})") from exc
        return results

    async def _search_brave(self, query: str, api_key: str, budget: Budget) -> List[Dict[str, str]]:
        results = []
        client = get_http_client("discovery_web_search", timeout=min(5.0, budget.remaining()))
        headers = {"X-Subscription-Token": api_key, "Accept": "application/json"}
        url = "https://api.search.brave.com/res/v1/web/search"
        try:
            resp = await client.get(url, params={"q": query, "count": 20}, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("web", {}).get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("description", ""),
                    })
        except Exception as exc:
            logger.warning("Brave search failed: %s", exc)
        return results

    async def _search_tavily(self, query: str, api_key: str, budget: Budget) -> List[Dict[str, str]]:
        results = []
        client = get_http_client("discovery_web_search", timeout=min(5.0, budget.remaining()))
        url = "https://api.tavily.com/search"
        try:
            resp = await client.post(
                url,
                json={"api_key": api_key, "query": query, "search_depth": "basic", "max_results": 20},
            )
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", ""),
                    })
        except Exception as exc:
            logger.warning("Tavily search failed: %s", exc)
        return results

    def _get_vault_key(self, provider_name: str) -> Optional[str]:
        try:
            from packages.infrastructure.key_vault import get_secrets_manager
            manager = get_secrets_manager()
            record = manager.get_active_key(provider_name.lower())
            if record and getattr(record, "value", None):
                return record.value
        except Exception:
            pass
        return None

    def _extract_ddg_url(self, raw_href: str) -> Optional[str]:
        """DuckDuckGo wraps result links as [https:]//duckduckgo.com/l/?uddg=<encoded target>."""
        if not raw_href:
            return None
        if "uddg=" in raw_href:
            params = parse_qs(urlparse(raw_href).query)
            if "uddg" in params:
                return unquote(params["uddg"][0])
            return None
        if raw_href.startswith("http"):
            return raw_href
        return None

    def _parse_profile_snippet(
        self,
        title: str = "",
        snippet: str = "",
        url: str = "",
        **kwargs: Any,
    ) -> Optional[Dict[str, str]]:
        t = title or kwargs.get("title_text", "")
        parts = t.split(" - ")
        if len(parts) >= 3:
            comp = re.sub(r"\s*\|\s*LinkedIn.*$", "", parts[2], flags=re.I).strip()
            return {"full_name": parts[0].strip(), "title": parts[1].strip(), "company": comp}
        elif len(parts) == 2:
            return {"full_name": parts[0].strip(), "title": parts[1].strip(), "company": ""}
        elif len(parts) == 1 and len(parts[0].split()) >= 2:
            return {"full_name": parts[0].strip(), "title": "", "company": ""}
        return None

    _LISTICLE = re.compile(r"^\s*(\d+\s|top\s+\d+|best\s|find\s|compare\s|the\s+\d+\s)|\b(near me|reviews?,|directory|"
                           r"ratings?\s*&|top\s+\d+|best\s+\d+|\d+\s+best)\b", re.I)

    def _is_listicle(self, title: str, url: str) -> bool:
        """Directory / ranking / comparison pages are references, not organizations."""
        domain = clean_domain(url)
        if any(d == domain or domain.endswith("." + d) for d in DIRECTORY_DOMAINS):
            return True
        return bool(self._LISTICLE.search(title))

    def _brand_name(self, title: str, domain: str) -> str:
        """Pick the title segment that matches the site domain (e.g. "... | ComForCare" on comforcare.com)."""
        label = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower()) if domain else ""
        segments = [s.strip() for s in re.split(r"\s[|\u2013\u2014\-:]\s|\s[|]\s|[|]", title) if s.strip()]
        for seg in segments:
            flat = re.sub(r"[^a-z0-9]", "", seg.lower())
            if label and len(flat) >= 4 and (flat in label or label in flat):
                return re.sub(r"\s+(in|of|near)\s+.*$", "", seg, flags=re.I).strip() or seg
        for seg in segments:
            if not re.search(r"\b(home care|services?|elderly|senior|in-home|near me|charlotte|agency)\b", seg, re.I):
                return seg
        return (domain.split(".")[0].replace("-", " ").title()) if domain else (segments[0] if segments else title)

    def _parse_company_title(self, title_text: str) -> str:
        clean = re.sub(
            r"\s*[-|:]\s*(Home|Official Site|LinkedIn|Facebook|About Us|Contact).*$",
            "",
            title_text,
            flags=re.IGNORECASE,
        ).strip()
        return clean or title_text

    def _classify_role(self, title: Optional[str]) -> Optional[str]:
        if not title:
            return None
        t = title.lower()
        if any(w in t for w in ("owner", "founder", "proprietor")):
            return "owner"
        if any(w in t for w in ("administrator", "executive director")):
            return "administrator"
        if any(w in t for w in ("nursing", "don", "rn")):
            return "director_of_nursing"
        if any(w in t for w in ("ceo", "president", "vp", "chief", "director")):
            return "executive"
        return "staff"
