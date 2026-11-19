"""
Worldwide location lookup for Live Discovery (free, no API key).

U.S. places are resolved offline from Census files (`geo.py`). Everything else, for example "Chennai metro area",
"RS Puram, Coimbatore" or "Paris, France", is looked up with OpenStreetMap Nominatim:
    https://nominatim.openstreetmap.org/search   (usage policy: https://operations.osmfoundation.org/policies/nominatim/)

Policy compliance: at most 1 request per second (bucket `discovery_geocode` in config/rate_limits.yaml), an
identifying User-Agent, and every answer cached on disk (data/geo/world_cache.json, 30 days; "not found" for 1 day),
so repeated searches never hit the service again. Set NOMINATIM_EMAIL to send a contact address with each request.

`resolve_location()` decides between the two:
  * a U.S. ZIP or county, or a U.S. place that accounts for every word of the location, uses the Census result;
  * otherwise the OpenStreetMap result wins when it exists ("Anna Nagar, Chennai" must not become Anna, TX, and
    "Coimbatore, TN" must not become the state of Tennessee);
  * a bare U.S. city name ("Miami") stays in the U.S. unless OpenStreetMap finds a much better-known place abroad.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from packages.discovery.geo import US_STATE_ABBRS, _METRO_WORDS, _STOP_PLACE_WORDS, extract_state_hint, resolve_geography
from packages.discovery.http import BOT_USER_AGENT, paced_request

logger = logging.getLogger("discovery.world_geo")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
RATE_BUCKET = "discovery_geocode"
CACHE_TTL_FOUND = 30 * 86400.0
CACHE_TTL_MISSING = 86400.0
FOREIGN_IMPORTANCE = 0.6   # a bare U.S. city name loses only to a foreign place at least this well known
_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "geo" / "world_cache.json"

_cache: Optional[Dict[str, Dict[str, Any]]] = None
_lock: Optional[asyncio.Lock] = None
_lock_loop: Optional[int] = None


def _cache_path() -> Path:
    base = os.getenv("DISCOVERY_GEO_CACHE")
    return Path(base) if base else _CACHE_PATH


def _load_cache() -> Dict[str, Dict[str, Any]]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(_cache or {}, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug("Could not write geocode cache: %s", exc)


def _get_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    loop_id = id(asyncio.get_running_loop())
    if _lock is None or _lock_loop != loop_id:
        _lock, _lock_loop = asyncio.Lock(), loop_id
    return _lock


def clean_location(text: str) -> str:
    """'chennai metro area' -> 'chennai'; 'RS Puram ,Coimbatore' -> 'RS Puram, Coimbatore'."""
    t = _METRO_WORDS.sub(" ", text or "")
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r"\s+", " ", t).strip(" ,.")
    return t


def _radius_km(bbox: List[str], lat: float, metro: bool) -> float:
    try:
        south, north, west, east = (float(x) for x in bbox)
    except (TypeError, ValueError):
        return 25.0 if metro else 10.0
    dlat = (north - south) * 111.0
    dlng = (east - west) * 111.0 * math.cos(math.radians(lat))
    radius = math.hypot(dlat, dlng) / 2
    if metro:
        radius = max(radius * 1.3, 25.0)
    return round(min(max(radius, 3.0), 60.0), 1)


def geography_from_nominatim(hit: Dict[str, Any], metro: bool) -> Dict[str, Any]:
    """Nominatim jsonv2 result (with addressdetails) -> the geography dict used by every source."""
    addr = hit.get("address") or {}
    name = hit.get("name") or (hit.get("display_name") or "").split(",")[0].strip()
    city = (addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
            or addr.get("city_district") or addr.get("county") or addr.get("state_district") or name)
    region = addr.get("state") or addr.get("region") or ""
    country = addr.get("country") or ""
    cc = (addr.get("country_code") or "").lower()
    parts: List[str] = []
    for p in (name, city, region, country):
        if p and p not in parts:
            parts.append(p)
    lat, lng = float(hit["lat"]), float(hit["lon"])
    cities = [c for c in dict.fromkeys([name, city]) if c]
    geo: Dict[str, Any] = {
        "type": "place", "name": ", ".join(parts), "city": city, "region": region, "country": country,
        "country_code": cc, "state": "", "states": [], "counties": [], "cities": cities,
        "lat": lat, "lng": lng, "radius_km": _radius_km(hit.get("boundingbox") or [], lat, metro),
        "centers": [{"name": ", ".join(parts[:-1]) if len(parts) > 1 else parts[0], "lat": lat, "lng": lng}],
        "needs_location": False, "ambiguous": False, "importance": float(hit.get("importance") or 0.0),
        "geocoder": "OpenStreetMap Nominatim",
        "source_url": f"https://www.openstreetmap.org/{hit.get('osm_type', 'node')}/{hit.get('osm_id', '')}",
    }
    if cc == "us":
        # Keep the U.S. sources working when OpenStreetMap is what found a U.S. place
        code = US_STATE_ABBRS.get(region.lower())
        if code:
            geo.update(state=code, states=[code])
    return geo


async def geocode_world(text: str, metro: bool = False, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """OpenStreetMap lookup with a disk cache. Returns None when nothing is found or the service is unreachable."""
    q = clean_location(text)
    if len(q) < 2:
        return None
    key = q.lower()
    cache = _load_cache()
    entry = cache.get(key)
    now = time.time()
    if entry and now - entry.get("ts", 0) < (CACHE_TTL_FOUND if entry.get("hit") else CACHE_TTL_MISSING):
        return geography_from_nominatim(entry["hit"], metro) if entry.get("hit") else None

    async with _get_lock():  # one request at a time, also coalesces identical lookups
        entry = cache.get(key)
        if entry and time.time() - entry.get("ts", 0) < (CACHE_TTL_FOUND if entry.get("hit") else CACHE_TTL_MISSING):
            return geography_from_nominatim(entry["hit"], metro) if entry.get("hit") else None
        params = {"q": q, "format": "jsonv2", "addressdetails": "1", "limit": "1", "accept-language": "en"}
        if os.getenv("NOMINATIM_EMAIL"):
            params["email"] = os.environ["NOMINATIM_EMAIL"]
        try:
            resp = await paced_request(RATE_BUCKET, "GET", NOMINATIM_URL, timeout=timeout, params=params,
                                       headers={"User-Agent": BOT_USER_AGENT, "Accept-Language": "en"})
        except (httpx.HTTPError, OSError) as exc:
            logger.warning("OpenStreetMap lookup failed for %r: %s", q, exc)
            return None
        if resp.status_code != 200:
            logger.warning("OpenStreetMap lookup for %r returned HTTP %s", q, resp.status_code)
            return None
        try:
            hits = resp.json()
        except ValueError:
            return None
        hit = hits[0] if isinstance(hits, list) and hits else None
        cache[key] = {"ts": time.time(), "hit": hit}
        _save_cache()
    return geography_from_nominatim(hit, metro) if hit else None


def _words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower().replace(".", ""))
            if w not in _STOP_PLACE_WORDS and not _METRO_WORDS.fullmatch(w)]


def _us_covers_location(us: Dict[str, Any], location: str) -> bool:
    """True when the U.S. result accounts for every word of the location text."""
    state_hint = extract_state_hint(location)
    named = set(_words(" ".join([str(us.get("name") or ""), str(us.get("city") or ""),
                                 " ".join(us.get("cities") or [])])))
    for full, code in US_STATE_ABBRS.items():
        if code in (us.get("states") or [us.get("state")]):
            named |= set(_words(full)) | {code.lower()}
    if state_hint:
        named.add(state_hint.lower())
    return set(_words(location)) <= named


async def resolve_location(location: Optional[str]) -> Dict[str, Any]:
    """Resolve any location text: U.S. Census first where it fits, OpenStreetMap for the rest of the world."""
    if not location or not location.strip():
        return {"needs_location": True}
    us = resolve_geography(location)
    us_ok = not us.get("needs_location")
    if us_ok and us.get("type") in ("zip", "county"):
        return us
    covered = us_ok and _us_covers_location(us, location)
    if covered and (us.get("type") in ("msa", "state") or extract_state_hint(location)):
        return us

    world = await geocode_world(location, metro=bool(_METRO_WORDS.search(location)))
    if world:
        # Search with the words the user typed ("RS Puram, Coimbatore"); OpenStreetMap only supplies the position
        typed = clean_location(location)
        typed_parts = [p.strip() for p in typed.split(",") if p.strip()]
        if not all(p.lower() in world["name"].lower() for p in typed_parts):
            # show what the user asked for ("RS Puram, Coimbatore"), not OpenStreetMap's district name ("Perur")
            extra = [x for x in (world.get("region"), world.get("country"))
                     if x and x.lower() not in typed.lower()]
            world["name"] = ", ".join([*typed_parts, *extra])
        world["search_text"] = typed
        world["centers"][0]["name"] = typed
        world["cities"] = list(dict.fromkeys([*world["cities"], *(p.strip() for p in typed.split(",") if p.strip())]))
    if covered:
        # Bare U.S. city name: keep it unless a far better-known place abroad has that name ("Paris", "London")
        if world and world.get("country_code") != "us" and world.get("importance", 0) >= FOREIGN_IMPORTANCE:
            world["ambiguous"] = True
            world["alternatives"] = [f"{us.get('name')}, {us.get('state')}"]
            return world
        return us
    if world:
        return world
    if us_ok:
        return us
    return {"needs_location": True,
            "error": f"Could not find '{clean_location(location)}' on the map. Check the spelling or add the city "
                     "and country, for example: 'hospitals in RS Puram, Coimbatore, India'."}
