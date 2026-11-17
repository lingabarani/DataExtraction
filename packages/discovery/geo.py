"""
Census-backed geographic resolution for the Discovery Engine.

Resolves free text ("Charlotte metro area", "Austin, TX", "Wake County NC", "28202", "North Carolina") using the
tables built by `geo_data.py` from official U.S. Census Bureau files (CBSA delineation + Gazetteer).
There is no default location: text that does not name a U.S. place returns {"needs_location": True}.
"""

from __future__ import annotations

import csv
import logging
import math
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from packages.discovery.geo_data import GEO_DIR, build_geo_data, geo_data_ready

logger = logging.getLogger("discovery.geo")

US_STATE_ABBRS = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL",
    "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
STATE_CODES = set(US_STATE_ABBRS.values())
_STATE_NAME_BY_CODE = {v: k.title() for k, v in US_STATE_ABBRS.items()}

# Words that appear in queries and also happen to be names of tiny Census places.
_STOP_PLACE_WORDS = {
    "care", "home", "homes", "health", "senior", "seniors", "elderly", "elder", "area", "metro", "metropolitan",
    "region", "county", "city", "town", "near", "around", "greater", "services", "service", "agency", "agencies",
    "center", "centers", "nursing", "living", "assisted", "memory", "hospice", "clinic", "clinics", "medical",
    "dental", "dentist", "dentists", "the", "and", "for", "with", "best", "top", "local", "new", "old", "north",
    "south", "east", "west", "central", "united", "states", "state", "restaurant", "restaurants", "plumbers",
    "plumber", "lawyers", "lawyer", "doctors", "doctor", "company", "companies", "business", "businesses",
    "provider", "providers", "facility", "facilities", "support", "help", "day", "adult", "family", "good",
}
_METRO_WORDS = re.compile(r"\b(metro|metropolitan|area|region|msa|greater|surrounding)\b", re.I)
_CITY_TYPES = {"city", "town", "village", "borough", "municipality", "city and borough"}


def extract_state_hint(text: str) -> Optional[str]:
    """State from ', NC' (any case after a comma), a full state name, or an UPPERCASE two-letter token."""
    m = re.search(r",\s*([A-Za-z]{2})\b", text)
    if m and m.group(1).upper() in STATE_CODES:
        return m.group(1).upper()
    low = text.lower()
    for name in sorted(US_STATE_ABBRS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", low):
            return US_STATE_ABBRS[name]
    for token in re.findall(r"\b([A-Z]{2})\b", text):
        if token in STATE_CODES:
            return token
    return None


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


class CensusGeoRegistry:
    """In-memory index over the Census CSV tables."""

    _lock = threading.Lock()
    loaded = False
    error: Optional[str] = None
    cbsa: Dict[str, Dict[str, Any]] = {}
    counties: Dict[str, Dict[str, Any]] = {}
    counties_by_name: Dict[str, List[Dict[str, Any]]] = {}
    places_by_name: Dict[str, List[Dict[str, Any]]] = {}
    places_by_cbsa: Dict[str, List[Dict[str, Any]]] = {}
    zcta: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls.loaded = False
            cls.error = None
            cls.cbsa, cls.counties, cls.counties_by_name = {}, {}, {}
            cls.places_by_name, cls.places_by_cbsa, cls.zcta = {}, {}, {}

    @classmethod
    def load(cls) -> None:
        if cls.loaded:
            return
        with cls._lock:
            if cls.loaded:
                return
            if not geo_data_ready():
                try:
                    logger.info("Census geo data missing; downloading (one-time, ~20 s)")
                    build_geo_data()
                except Exception as exc:  # network failure etc.
                    cls.error = f"Census reference data unavailable ({type(exc).__name__}). Run: python scripts/data/fetch_census_geo.py"
                    logger.warning(cls.error)
                    return
            try:
                cls._read_tables()
                cls.loaded = True
                cls.error = None
            except Exception as exc:
                cls.error = f"Census reference data unreadable: {exc}"
                logger.warning(cls.error)

    @classmethod
    def _read_tables(cls) -> None:
        with open(GEO_DIR / "counties.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rec = {"geoid": r["county_geoid"], "name": r["county_name"], "state": r["state_code"],
                       "lat": float(r["lat"]), "lng": float(r["lng"])}
                cls.counties[rec["geoid"]] = rec
                short = re.sub(r"\s+(County|Parish|Borough|Census Area|Municipality)$", "", rec["name"]).lower()
                cls.counties_by_name.setdefault(short, []).append(rec)
        with open(GEO_DIR / "cbsa_delineation.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                entry = cls.cbsa.setdefault(r["cbsa_code"], {
                    "code": r["cbsa_code"], "title": r["cbsa_title"], "type": r["cbsa_type"],
                    "counties": [], "county_geoids": [], "states": []})
                entry["counties"].append(f"{re.sub(r' County$', '', r['county_name'])}, {r['state_code']}")
                entry["county_geoids"].append(r["county_geoid"])
                if r["state_code"] and r["state_code"] not in entry["states"]:
                    entry["states"].append(r["state_code"])
        with open(GEO_DIR / "places.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rec = {"geoid": r["place_geoid"], "name": r["place_name"], "state": r["state_code"],
                       "type": r["place_type"], "lat": float(r["lat"]), "lng": float(r["lng"]),
                       "area": float(r.get("area_sqmi") or 0), "county_geoid": r["county_geoid"], "cbsa": r["cbsa_code"]}
                cls.places_by_name.setdefault(rec["name"].lower(), []).append(rec)
                if rec["cbsa"]:
                    cls.places_by_cbsa.setdefault(rec["cbsa"], []).append(rec)
        with open(GEO_DIR / "zcta.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                cls.zcta[r["zip"]] = {"zip": r["zip"], "lat": float(r["lat"]), "lng": float(r["lng"]),
                                      "state": r["state_code"], "place": r["place_name"]}


def _place_rank(place: Dict[str, Any], state_hint: Optional[str]) -> Tuple[int, int, float]:
    """Lower is better: matches state hint, is an incorporated place, then larger land area (proxy for size)."""
    return (0 if state_hint and place["state"] == state_hint else 1,
            0 if place["type"] in _CITY_TYPES else 1,
            -float(place.get("area", 0.0)))


def _geo_for_place(place: Dict[str, Any], metro: bool) -> Dict[str, Any]:
    reg = CensusGeoRegistry
    cbsa = reg.cbsa.get(place["cbsa"]) if place.get("cbsa") else None
    county = reg.counties.get(place["county_geoid"], {})
    out: Dict[str, Any] = {
        "type": "city", "name": place["name"], "city": place["name"], "state": place["state"],
        "states": [place["state"]], "lat": place["lat"], "lng": place["lng"], "radius_km": 25,
        "cbsa_code": place.get("cbsa") or None, "needs_location": False,
        "counties": ([re.sub(r" County$", "", county["name"]) + f", {county['state']}"] if county else []),
        "cities": [place["name"]],
        "centers": [{"name": place["name"], "lat": place["lat"], "lng": place["lng"]}],
        "ambiguous": False,
    }
    if metro and cbsa:
        members = reg.places_by_cbsa.get(cbsa["code"], [])
        title_cities = [c.strip().lower() for c in cbsa["title"].split(",")[0].split("-")]
        centers = [p for p in members if p["name"].lower() in title_cities and p["type"] in _CITY_TYPES]
        centers.sort(key=lambda p: title_cities.index(p["name"].lower()))
        seen_names: List[str] = []
        for p in members:
            if p["name"] not in seen_names:
                seen_names.append(p["name"])
        out.update({
            "type": "msa", "name": cbsa["title"], "states": list(cbsa["states"]), "radius_km": 45,
            "counties": list(cbsa["counties"]), "cities": seen_names,
            "centers": [{"name": c["name"], "lat": c["lat"], "lng": c["lng"]} for c in centers[:6]]
                       or out["centers"],
        })
    return out


def resolve_geography(location_query: Optional[str]) -> Dict[str, Any]:
    """Resolve text to a geography dict. Never guesses a default: unknown text -> {'needs_location': True}."""
    if not location_query or not location_query.strip():
        return {"needs_location": True}

    reg = CensusGeoRegistry
    reg.load()
    if not reg.loaded:
        return {"needs_location": True, "error": reg.error}

    text = location_query.strip()
    low = text.lower()
    state_hint = extract_state_hint(text)
    metro = bool(_METRO_WORDS.search(low))

    # 1. ZIP code
    zm = re.search(r"\b(\d{5})\b", text)
    if zm and zm.group(1) in reg.zcta:
        z = reg.zcta[zm.group(1)]
        return {"type": "zip", "name": z["zip"], "zip": z["zip"], "city": z["place"], "state": z["state"],
                "states": [z["state"]], "lat": z["lat"], "lng": z["lng"], "radius_km": 15, "needs_location": False,
                "cities": [z["place"]], "counties": [],
                "centers": [{"name": z["place"], "lat": z["lat"], "lng": z["lng"]}]}

    # 2. County ("Wake County NC", "Mecklenburg County")
    cm = re.search(r"\b([a-z][a-z\.'\-]*(?:\s+[a-z][a-z\.'\-]*){0,2})\s+(?:county|parish)\b", low)
    if cm:
        cand_name = cm.group(1).strip()
        # Drop leading words that belong to the query ("home care in wake" -> "wake")
        words = cand_name.split()
        for start in range(len(words)):
            key = " ".join(words[start:])
            cands = reg.counties_by_name.get(key)
            if cands:
                chosen = next((c for c in cands if state_hint and c["state"] == state_hint), cands[0])
                return {"type": "county", "name": chosen["name"], "county": chosen["name"], "state": chosen["state"],
                        "states": [chosen["state"]], "lat": chosen["lat"], "lng": chosen["lng"], "radius_km": 35,
                        "counties": [re.sub(r" County$", "", chosen["name"]) + f", {chosen['state']}"],
                        "cities": [], "needs_location": False,
                        "centers": [{"name": chosen["name"], "lat": chosen["lat"], "lng": chosen["lng"]}],
                        "ambiguous": len(cands) > 1 and not state_hint}

    # 3. City / metro: longest 1-4 word n-gram that is a Census place (full state names are masked first so
    #    "North Carolina" is not read as the place "Carolina")
    masked = text
    for sname in sorted(US_STATE_ABBRS, key=len, reverse=True):
        masked = re.sub(rf"\b{re.escape(sname)}\b", " ", masked, flags=re.I)
    tokens = re.findall(r"[A-Za-z][A-Za-z\.'\-]*", masked)
    best: Optional[Tuple[int, List[Dict[str, Any]]]] = None
    for n in (4, 3, 2, 1):
        for i in range(0, len(tokens) - n + 1):
            gram_words = tokens[i:i + n]
            if n == 1 and gram_words[0].lower() in _STOP_PLACE_WORDS:
                continue
            if n > 1 and all(w.lower() in _STOP_PLACE_WORDS for w in gram_words):
                continue
            gram = " ".join(gram_words).lower().replace(".", "")
            cands = reg.places_by_name.get(gram) or reg.places_by_name.get(" ".join(gram_words).lower())
            if cands:
                if best is None or n > best[0]:
                    best = (n, cands)
        if best:
            break
    if best:
        cands = sorted(best[1], key=lambda p: _place_rank(p, state_hint))
        chosen = cands[0]
        if state_hint and chosen["state"] != state_hint:
            # Named city exists, but not in the stated state: do not guess another state.
            return {"needs_location": True, "error": f"No place named '{chosen['name']}' found in {state_hint}"}
        geo = _geo_for_place(chosen, metro=metro)
        # Ambiguous only when another incorporated place of the same name is comparable in size.
        incorporated = [c for c in cands if c["type"] in _CITY_TYPES]
        rivals = [c for c in incorporated[1:]
                  if c["state"] != chosen["state"] and c.get("area", 0) >= 0.3 * max(chosen.get("area", 0), 0.01)]
        geo["ambiguous"] = (not state_hint) and bool(rivals)
        if geo["ambiguous"]:
            geo["alternatives"] = sorted({chosen["state"], *(c["state"] for c in rivals)})[:8]
        return geo

    # 4. State only
    if state_hint:
        return {"type": "state", "name": _STATE_NAME_BY_CODE.get(state_hint, state_hint), "state": state_hint,
                "states": [state_hint], "radius_km": 150, "needs_location": False,
                "cities": [], "counties": [], "centers": []}

    return {"needs_location": True}
