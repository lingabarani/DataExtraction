"""
Public LinkedIn discovery module.
Uses web search results to identify public linkedin.com/in/ and linkedin.com/company/ URLs,
fetches each public page politely with token-bucket rate limiting, and extracts
structured Schema.org Person and Organization entities.
"""

import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from packages.discovery.models import OrgRecord, PersonRecord
from .client import AuthExpired, Blocked, LinkedInHttpClient, RateLimited
from .company import parse_public_company
from .public_profile import parse_public_profile

logger = logging.getLogger("dataextraction.scrapers.linkedin.discover")


def normalize_entity_name(name: str) -> str:
    """Normalize entity name for deduplication and indexing."""
    cleaned = re.sub(r"[^\w\s]", "", name.lower())
    return " ".join(cleaned.split())


def build_discovery_search_queries(category: str, location: str) -> List[str]:
    """Generate search queries targeting public LinkedIn profiles and company directories."""
    clean_cat = category.strip()
    clean_loc = location.strip()
    return [
        f'site:linkedin.com/company "{clean_cat}" {clean_loc}',
        f'site:linkedin.com/in "administrator" OR "director" "{clean_cat}" {clean_loc}',
        f'site:linkedin.com/in "owner" OR "founder" "{clean_cat}" {clean_loc}',
    ]


async def fetch_and_parse_linkedin_url(
    client: LinkedInHttpClient,
    url: str,
) -> Tuple[Optional[OrgRecord], Optional[PersonRecord]]:
    """Fetch a public LinkedIn URL and parse into either an OrgRecord or PersonRecord."""
    try:
        html = await client.get_public_page(url)
        if not html:
            return None, None

        parsed_url = urlparse(url)
        path = parsed_url.path.lower()

        if "/company/" in path or "/school/" in path:
            data = parse_public_company(html)
            if data and data.get("name"):
                name = str(data["name"]).strip()
                domain = None
                website = data.get("website")
                if website:
                    parsed_web = urlparse(website if "://" in website else f"https://{website}")
                    domain = parsed_web.netloc.lower().removeprefix("www.")

                org = OrgRecord(
                    name=name,
                    canonical_name=name,
                    normalized_name=normalize_entity_name(name),
                    category=None,
                    website=website,
                    domain=domain,
                    address=data.get("address") or {},
                    social={"linkedin": url},
                    first_seen_source="linkedin_public",
                    sources=[{"source": "linkedin_public", "url": url, "confidence": 0.85}],
                    quality_score=0.75,
                )
                return org, None

        elif "/in/" in path:
            data = parse_public_profile(html)
            if data and data.get("name"):
                full_name = str(data["name"]).strip()
                headline = data.get("headline") or ""
                role_type = "executive"
                lower_h = headline.lower()
                if "owner" in lower_h or "founder" in lower_h:
                    role_type = "owner"
                elif "administrator" in lower_h:
                    role_type = "administrator"
                elif "director of nursing" in lower_h or "don" in lower_h:
                    role_type = "director_of_nursing"

                person = PersonRecord(
                    name=full_name,
                    full_name=full_name,
                    normalized_name=normalize_entity_name(full_name),
                    title=headline[:120] if headline else None,
                    role_type=role_type,
                    headline=headline,
                    org_name=data.get("company"),
                    city=data.get("city"),
                    region=data.get("region"),
                    country=data.get("country"),
                    profile_urls=[url],
                    provenance="linkedin_public",
                    verified=False,
                    source_url=url,
                )
                return None, person

    except (Blocked, RateLimited, AuthExpired) as exc:
        logger.warning("LinkedIn public fetch stopped for %s: %s", url, exc)
        raise
    except Exception as exc:
        logger.debug("Failed parsing LinkedIn public page %s: %s", url, exc)

    return None, None


async def discover_linkedin_entities(
    urls: List[str],
    client: Optional[LinkedInHttpClient] = None,
    max_pages: int = 10,
) -> Tuple[List[OrgRecord], List[PersonRecord]]:
    """Politely fetch and parse a batch of candidate LinkedIn URLs."""
    http_client = client or LinkedInHttpClient()
    orgs: List[OrgRecord] = []
    people: List[PersonRecord] = []

    urls_to_crawl = [u for u in urls if "linkedin.com/" in u][:max_pages]

    for url in urls_to_crawl:
        try:
            org, person = await fetch_and_parse_linkedin_url(http_client, url)
            if org:
                orgs.append(org)
            if person:
                people.append(person)
        except (Blocked, RateLimited, AuthExpired):
            # Stop immediately on block / login wall
            logger.info("Stopping LinkedIn discovery run due to anti-bot response.")
            break
        except Exception as exc:
            logger.debug("Error during LinkedIn discovery for %s: %s", url, exc)

    return orgs, people
