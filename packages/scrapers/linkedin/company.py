"""
Company organization parser from public LinkedIn company page HTML.
Extracts Schema.org Organization ld+json, canonical URLs, and OpenGraph metadata.
"""

import json
import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup

logger = logging.getLogger("dataextraction.scrapers.linkedin.company")


def extract_slug_from_url(url: Optional[str]) -> Optional[str]:
    """Extract company slug from LinkedIn company page URL."""
    if not url:
        return None
    path = urlparse(url).path.strip("/")
    match = re.search(r"(?:company|school)/([^/?#]+)", path)
    if match:
        return match.group(1)
    parts = [p for p in path.split("/") if p]
    return parts[-1] if parts else None


def parse_public_company(html: str) -> Dict[str, Any]:
    """Parse public LinkedIn company page HTML for Schema.org Organization metadata.

    Returns dict with keys:
        name, description, website, industry, employee_count, address, logo, slug, raw_ldjson.
    """
    result: Dict[str, Any] = {
        "name": None,
        "description": None,
        "website": None,
        "industry": None,
        "employee_count": None,
        "address": None,
        "logo": None,
        "slug": None,
        "raw_ldjson": None,
    }

    if not html or not html.strip():
        return result

    soup = BeautifulSoup(html, "lxml")

    # 1. Look for canonical URL or meta tag for slug
    canonical_tag = soup.find("link", rel="canonical")
    canonical_url: Optional[str] = None
    if canonical_tag and canonical_tag.get("href"):
        canonical_url = str(canonical_tag.get("href"))
    if not canonical_url:
        og_url_tag = soup.find("meta", property="og:url")
        if og_url_tag and og_url_tag.get("content"):
            canonical_url = str(og_url_tag.get("content"))

    if canonical_url:
        result["slug"] = extract_slug_from_url(canonical_url)

    # 2. Look for Organization ld+json block
    script_tags = soup.find_all("script", type="application/ld+json")
    org_data: Optional[Dict[str, Any]] = None

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
                    if isinstance(g, dict) and str(g.get("@type", "")).lower() in (
                        "organization",
                        "corporation",
                        "educationalorganization",
                    ):
                        org_data = g
                        break
            if str(item.get("@type", "")).lower() in (
                "organization",
                "corporation",
                "educationalorganization",
            ):
                org_data = item
                break
        if org_data:
            break

    if not org_data:
        # Fallback to OpenGraph / meta tags if ld+json is absent
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            result["name"] = str(og_title.get("content")).split("|")[0].strip()
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            result["description"] = str(og_desc.get("content")).strip()
        return result

    result["raw_ldjson"] = org_data
    result["name"] = org_data.get("name")
    result["description"] = org_data.get("description")
    result["website"] = org_data.get("url")

    # Address
    address = org_data.get("address")
    if isinstance(address, dict):
        result["address"] = {
            "street": address.get("streetAddress"),
            "city": address.get("addressLocality"),
            "region": address.get("addressRegion"),
            "postal_code": address.get("postalCode"),
            "country": address.get("addressCountry") if isinstance(address.get("addressCountry"), str) else (
                address.get("addressCountry", {}).get("name") if isinstance(address.get("addressCountry"), dict) else None
            ),
        }
    elif isinstance(address, str):
        result["address"] = {"street": address}

    # Logo
    logo = org_data.get("logo")
    if isinstance(logo, dict):
        result["logo"] = logo.get("contentUrl") or logo.get("url")
    elif isinstance(logo, str):
        result["logo"] = logo

    # Number of employees
    num_employees = org_data.get("numberOfEmployees")
    if isinstance(num_employees, dict):
        result["employee_count"] = num_employees.get("value") or num_employees.get("name")
    elif num_employees is not None:
        result["employee_count"] = str(num_employees)

    return result
