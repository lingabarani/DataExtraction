"""
Voyager API extraction client for LinkedIn identities and contact info.
Strictly disabled by default; requires LINKEDIN_AUTH_ENABLED=true.
"""

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from .client import AuthExpired, LinkedInHttpClient

logger = logging.getLogger("dataextraction.scrapers.linkedin.voyager")

VOYAGER_PROFILE_URL = "https://www.linkedin.com/voyager/api/identity/dash/profiles"
VOYAGER_DECORATION_ID = "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93"
CONTACT_URL_TEMPLATE = "https://www.linkedin.com/voyager/api/identity/profiles/{slug}/profileContactInfo"


async def fetch_voyager_profile(client: LinkedInHttpClient, slug: str) -> Dict[str, Any]:
    """Fetch structured profile data from LinkedIn Voyager API.
    Raises AuthExpired if LINKEDIN_AUTH_ENABLED is false.
    """
    if not client.is_auth_enabled():
        raise AuthExpired("Authenticated LinkedIn scraping is disabled (LINKEDIN_AUTH_ENABLED=false).")

    params = {
        "q": "memberIdentity",
        "memberIdentity": slug,
        "decorationId": VOYAGER_DECORATION_ID,
    }
    url = f"{VOYAGER_PROFILE_URL}?{urlencode(params)}"
    data = await client.get_authenticated(url)

    included = data.get("included", []) if isinstance(data, dict) else []

    profile_item: Dict[str, Any] = {}
    for item in included:
        if not isinstance(item, dict):
            continue
        urn = str(item.get("entityUrn", ""))
        if "fsd_profile" in urn and "firstName" in item:
            profile_item = item
            break

    first_name = profile_item.get("firstName")
    last_name = profile_item.get("lastName")
    full_name: Optional[str] = None
    if first_name or last_name:
        full_name = f"{first_name or ''} {last_name or ''}".strip() or None

    headline = profile_item.get("headline")
    about = profile_item.get("summary")

    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    location_name = profile_item.get("locationName")
    if location_name:
        parts = [p.strip() for p in location_name.split(",") if p.strip()]
        if len(parts) == 1:
            country = parts[0]
        elif len(parts) == 2:
            city, country = parts[0], parts[1]
        elif len(parts) >= 3:
            city, region, country = parts[0], parts[1], parts[-1]

    positions: List[Dict[str, Any]] = []
    for item in included:
        if not isinstance(item, dict):
            continue
        urn = str(item.get("entityUrn", ""))
        if "fsd_position" in urn:
            date_range = item.get("dateRange")
            is_current = True
            if isinstance(date_range, dict) and "end" in date_range:
                is_current = False
            positions.append({
                "title": item.get("title"),
                "company_name": item.get("companyName"),
                "location": item.get("locationName") or item.get("location"),
                "is_current": is_current,
            })

    education: List[Dict[str, Any]] = []
    for item in included:
        if not isinstance(item, dict):
            continue
        urn = str(item.get("entityUrn", ""))
        if "fsd_education" in urn:
            education.append({
                "school_name": item.get("schoolName"),
                "degree_name": item.get("degreeName"),
                "field_of_study": item.get("fieldOfStudy"),
            })

    skills: List[str] = []
    for item in included:
        if not isinstance(item, dict):
            continue
        urn = str(item.get("entityUrn", ""))
        if "fsd_skill" in urn:
            name = item.get("name")
            if name:
                skills.append(str(name))

    return {
        "name": full_name,
        "headline": headline,
        "about": about,
        "city": city,
        "region": region,
        "country": country,
        "positions": positions,
        "education": education,
        "skills": skills,
        "raw": data,
    }


async def fetch_voyager_contact_info(client: LinkedInHttpClient, slug: str) -> Dict[str, Any]:
    """Fetch contact info for a member slug. Swallows errors and returns empty structure safely."""
    empty_result = {
        "emails": [],
        "phones": [],
        "websites": [],
        "twitter": None,
    }
    if not client.is_auth_enabled():
        return empty_result

    try:
        url = CONTACT_URL_TEMPLATE.format(slug=slug)
        payload = await client.get_authenticated(url)
        root = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload

        if not isinstance(root, dict):
            return empty_result

        emails: List[str] = []
        if root.get("emailAddress"):
            emails.append(str(root["emailAddress"]).strip())
        if isinstance(root.get("emails"), list):
            for e in root["emails"]:
                if isinstance(e, str) and e.strip():
                    emails.append(e.strip())
                elif isinstance(e, dict) and e.get("email"):
                    emails.append(str(e["email"]).strip())

        phones: List[str] = []
        phone_entries = root.get("phoneNumbers") or root.get("phones") or []
        if isinstance(phone_entries, list):
            for p in phone_entries:
                if isinstance(p, dict) and p.get("number"):
                    phones.append(str(p["number"]).strip())
                elif isinstance(p, str) and p.strip():
                    phones.append(p.strip())

        websites: List[str] = []
        website_entries = root.get("websites") or []
        if isinstance(website_entries, list):
            for w in website_entries:
                if isinstance(w, dict) and w.get("url"):
                    websites.append(str(w["url"]).strip())
                elif isinstance(w, str) and w.strip():
                    websites.append(w.strip())

        twitter: Optional[str] = None
        tw = root.get("twitterHandles") or root.get("twitter")
        if isinstance(tw, list) and tw:
            first_tw = tw[0]
            if isinstance(first_tw, dict) and first_tw.get("name"):
                twitter = str(first_tw["name"]).strip()
            elif isinstance(first_tw, str):
                twitter = first_tw.strip()
        elif isinstance(tw, dict) and tw.get("name"):
            twitter = str(tw["name"]).strip()
        elif isinstance(tw, str):
            twitter = tw.strip()

        return {
            "emails": list(dict.fromkeys(emails)),
            "phones": list(dict.fromkeys(phones)),
            "websites": list(dict.fromkeys(websites)),
            "twitter": twitter,
        }
    except Exception as exc:
        logger.debug("Safe contact info extraction returned empty: %s", exc)
        return empty_result
