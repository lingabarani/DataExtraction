"""
Voyager people and company search.
Strictly disabled unless LINKEDIN_AUTH_ENABLED=true.
"""

import logging
import re
from typing import List
from urllib.parse import urlencode

from .client import AuthExpired, LinkedInHttpClient

logger = logging.getLogger("dataextraction.scrapers.linkedin.search")

SEARCH_BLENDED_URL = "https://www.linkedin.com/voyager/api/search/blended"


async def search_people_voyager(client: LinkedInHttpClient, keyword: str, limit: int = 10) -> List[str]:
    """Search LinkedIn Voyager for people matching keyword and return profile slugs."""
    if not client.is_auth_enabled():
        raise AuthExpired("Authenticated LinkedIn scraping is disabled (LINKEDIN_AUTH_ENABLED=false).")

    params = {
        "keywords": keyword,
        "origin": "GLOBAL_SEARCH_HEADER",
        "q": "all",
        "filters": "List(resultType->PEOPLE)",
        "count": min(limit * 2, 40),
    }
    url = f"{SEARCH_BLENDED_URL}?{urlencode(params)}"
    try:
        data = await client.get_authenticated(url)
    except Exception as exc:
        logger.debug("Voyager people search failed: %s", exc)
        return []

    slugs: List[str] = []
    included = data.get("included", []) if isinstance(data, dict) else []
    for item in included:
        if not isinstance(item, dict):
            continue
        pid = item.get("publicIdentifier")
        if pid and isinstance(pid, str) and pid not in slugs:
            slugs.append(pid)
            if len(slugs) >= limit:
                return slugs

        nav_url = item.get("navigationUrl") or item.get("url") or ""
        match = re.search(r"/in/([a-zA-Z0-9_-]+)", str(nav_url))
        if match:
            slug = match.group(1)
            if slug not in slugs:
                slugs.append(slug)
                if len(slugs) >= limit:
                    return slugs

    return slugs[:limit]


async def search_companies_voyager(client: LinkedInHttpClient, keyword: str, limit: int = 10) -> List[str]:
    """Search LinkedIn Voyager for companies matching keyword and return company slugs."""
    if not client.is_auth_enabled():
        raise AuthExpired("Authenticated LinkedIn scraping is disabled (LINKEDIN_AUTH_ENABLED=false).")

    params = {
        "keywords": keyword,
        "origin": "GLOBAL_SEARCH_HEADER",
        "q": "all",
        "filters": "List(resultType->COMPANIES)",
        "count": min(limit * 2, 40),
    }
    url = f"{SEARCH_BLENDED_URL}?{urlencode(params)}"
    try:
        data = await client.get_authenticated(url)
    except Exception as exc:
        logger.debug("Voyager company search failed: %s", exc)
        return []

    slugs: List[str] = []
    included = data.get("included", []) if isinstance(data, dict) else []
    for item in included:
        if not isinstance(item, dict):
            continue
        universal_name = item.get("universalName")
        if universal_name and isinstance(universal_name, str) and universal_name not in slugs:
            slugs.append(universal_name)
            if len(slugs) >= limit:
                return slugs

        nav_url = item.get("navigationUrl") or item.get("url") or ""
        match = re.search(r"/(?:company|school)/([a-zA-Z0-9_-]+)", str(nav_url))
        if match:
            slug = match.group(1)
            if slug not in slugs:
                slugs.append(slug)
                if len(slugs) >= limit:
                    return slugs

    return slugs[:limit]
