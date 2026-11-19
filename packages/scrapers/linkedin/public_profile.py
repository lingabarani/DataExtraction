"""
Parser for public LinkedIn profile HTML Schema.org ld+json Person metadata.
Extracts name, headline, current company, location, image, and social URLs.
"""

import json
import logging
from typing import Any, Dict, Optional
from bs4 import BeautifulSoup

logger = logging.getLogger("dataextraction.scrapers.linkedin.public_profile")


def parse_public_profile(html: str) -> Dict[str, Any]:
    """Parse public LinkedIn profile HTML for Schema.org ld+json Person metadata.

    Returns dict with keys:
        name, headline, company, company_url, city, region, country, image, same_as, raw_ldjson.
    Missing fields become None or empty list.
    """
    result: Dict[str, Any] = {
        "name": None,
        "headline": None,
        "company": None,
        "company_url": None,
        "city": None,
        "region": None,
        "country": None,
        "image": None,
        "same_as": [],
        "raw_ldjson": None,
    }

    if not html or not html.strip():
        return result

    soup = BeautifulSoup(html, "lxml")
    script_tags = soup.find_all("script", type="application/ld+json")

    person_data: Optional[Dict[str, Any]] = None

    for script in script_tags:
        content = script.string or script.get_text()
        if not content:
            continue
        try:
            parsed = json.loads(content.strip())
        except Exception:
            continue

        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            if "@graph" in item and isinstance(item["@graph"], list):
                for g in item["@graph"]:
                    if isinstance(g, dict) and str(g.get("@type", "")).lower() == "person":
                        person_data = g
                        break
            if str(item.get("@type", "")).lower() == "person":
                person_data = item
                break
        if person_data:
            break

    if not person_data:
        # Fallback to OpenGraph meta tags if ld+json is missing
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title_text = str(og_title["content"])
            parts = [p.strip() for p in title_text.split("-") if p.strip()]
            if parts:
                result["name"] = parts[0]
                if len(parts) > 1:
                    result["headline"] = parts[1]

        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content") and not result["headline"]:
            result["headline"] = str(og_desc["content"])
        return result

    result["raw_ldjson"] = person_data
    result["name"] = person_data.get("name")
    result["headline"] = person_data.get("description") or person_data.get("jobTitle")

    works_for = person_data.get("worksFor")
    if isinstance(works_for, list) and works_for:
        works_for = works_for[0]

    if isinstance(works_for, dict):
        result["company"] = works_for.get("name")
        result["company_url"] = works_for.get("url")
    elif isinstance(works_for, str):
        result["company"] = works_for

    address = person_data.get("address")
    if isinstance(address, dict):
        result["city"] = address.get("addressLocality")
        result["region"] = address.get("addressRegion")
        country = address.get("addressCountry")
        if isinstance(country, dict):
            result["country"] = country.get("name")
        elif isinstance(country, str):
            result["country"] = country

    image = person_data.get("image")
    if isinstance(image, dict):
        result["image"] = image.get("contentUrl") or image.get("url")
    elif isinstance(image, str):
        result["image"] = image

    same_as = person_data.get("sameAs")
    if isinstance(same_as, list):
        result["same_as"] = [str(x) for x in same_as if x]
    elif isinstance(same_as, str) and same_as:
        result["same_as"] = [same_as]

    return result
