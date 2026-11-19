"""
Downloads and builds the Census reference tables used by `geo.py`.

Sources (all U.S. Census Bureau, public domain):
  * CBSA delineation (metro/micro areas -> counties):
      https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list1_2023.xlsx
  * Gazetteer places, counties and ZCTAs (names, internal-point coordinates):
      https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_{place,counties,zcta}_national.zip

Output (data/geo/, git-ignored, rebuilt by `python scripts/data/fetch_census_geo.py`):
  cbsa_delineation.csv  cbsa_code,cbsa_title,cbsa_type,county_geoid,county_name,state_code,central_outlying
  counties.csv          county_geoid,county_name,state_code,lat,lng
  places.csv            place_geoid,place_name,state_code,place_type,lat,lng,area_sqmi,county_geoid,cbsa_code
  zcta.csv              zip,lat,lng,state_code,place_name
  SOURCES.md            URLs, retrieval time and SHA-256 of every downloaded file

The Census place->county relationship file for 2020 is not published at a stable URL, so each place is
assigned to the county whose internal point is nearest within the same state. That is an approximation
near county borders and is recorded in SOURCES.md.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GEO_DIR = PROJECT_ROOT / "data" / "geo"

BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer"
URL_CBSA = ("https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/"
            "delineation-files/list1_2023.xlsx")
URL_PLACES = f"{BASE}/2023_Gaz_place_national.zip"
URL_COUNTIES = f"{BASE}/2023_Gaz_counties_national.zip"
URL_ZCTA = f"{BASE}/2023_Gaz_zcta_national.zip"

REQUIRED_FILES = ("cbsa_delineation.csv", "counties.csv", "places.csv", "zcta.csv")

STATE_FIPS_TO_USPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC",
    "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT",
    "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY", "72": "PR",
}

_PLACE_SUFFIXES = (
    " city and borough", " consolidated government (balance)", " metropolitan government (balance)",
    " unified government (balance)", " municipality", " borough", " village", " town", " city", " CDP", " (balance)",
    " township", " plantation", " comunidad", " zona urbana",
)


def geo_data_ready() -> bool:
    return all((GEO_DIR / f).exists() and (GEO_DIR / f).stat().st_size > 1000 for f in REQUIRED_FILES)


def _clean_place_name(raw: str) -> Tuple[str, str]:
    name = raw.strip()
    ptype = "place"
    changed = True
    while changed:
        changed = False
        for suf in _PLACE_SUFFIXES:
            if name.lower().endswith(suf.lower()):
                ptype = suf.strip().strip("()").lower() or ptype
                name = name[: -len(suf)].strip()
                changed = True
                break
    return name, ptype


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _read_zip_table(content: bytes) -> List[Dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        text = zf.read(member).decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    header = [h.strip() for h in next(reader)]
    return [dict(zip(header, [c.strip() for c in row])) for row in reader if row]


def _read_cbsa_xlsx(content: bytes) -> List[Dict[str, str]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    header_idx = next(i for i, r in enumerate(rows) if r and any(str(c).strip() == "CBSA Code" for c in r if c))
    header = [str(c).strip() if c is not None else "" for c in rows[header_idx]]
    out = []
    for r in rows[header_idx + 1:]:
        if not r or r[0] in (None, ""):
            continue
        rec = {header[i]: ("" if c is None else str(c).strip()) for i, c in enumerate(r) if i < len(header)}
        if rec.get("CBSA Code", "").isdigit():
            out.append(rec)
    return out


def build_geo_data(force: bool = False, client: Optional[httpx.Client] = None) -> Dict[str, int]:
    """Download Census files and write data/geo/*.csv. Returns row counts. Raises on failure."""
    if geo_data_ready() and not force:
        return {}
    GEO_DIR.mkdir(parents=True, exist_ok=True)
    own = client is None
    http = client or httpx.Client(timeout=120, follow_redirects=True,
                                  headers={"User-Agent": "DataExtractionBot/1.0 (+census reference data)"})
    try:
        downloads: Dict[str, bytes] = {}
        for label, url in (("cbsa", URL_CBSA), ("places", URL_PLACES), ("counties", URL_COUNTIES), ("zcta", URL_ZCTA)):
            resp = http.get(url)
            resp.raise_for_status()
            downloads[label] = resp.content
    finally:
        if own:
            http.close()

    # ── counties ─────────────────────────────────────────────────────────────
    counties: List[Dict[str, object]] = []
    for r in _read_zip_table(downloads["counties"]):
        geoid = r["GEOID"].zfill(5)
        counties.append({"county_geoid": geoid, "county_name": r["NAME"], "state_code": r["USPS"],
                         "lat": float(r["INTPTLAT"]), "lng": float(r["INTPTLONG"])})
    county_by_state: Dict[str, List[Dict[str, object]]] = {}
    for c in counties:
        county_by_state.setdefault(str(c["state_code"]), []).append(c)

    # ── CBSA delineation ─────────────────────────────────────────────────────
    cbsa_rows: List[Dict[str, str]] = []
    county_to_cbsa: Dict[str, str] = {}
    for r in _read_cbsa_xlsx(downloads["cbsa"]):
        state_fips = r.get("FIPS State Code", "").zfill(2)
        county_fips = r.get("FIPS County Code", "").zfill(3)
        geoid = f"{state_fips}{county_fips}"
        cbsa_rows.append({
            "cbsa_code": r["CBSA Code"],
            "cbsa_title": r.get("CBSA Title", ""),
            "cbsa_type": r.get("Metropolitan/Micropolitan Statistical Area", ""),
            "county_geoid": geoid,
            "county_name": r.get("County/County Equivalent", ""),
            "state_code": STATE_FIPS_TO_USPS.get(state_fips, ""),
            "central_outlying": r.get("Central/Outlying County", ""),
        })
        county_to_cbsa[geoid] = r["CBSA Code"]

    # ── places (nearest county centroid within state) ────────────────────────
    places: List[Dict[str, object]] = []
    for r in _read_zip_table(downloads["places"]):
        state = r["USPS"]
        name, ptype = _clean_place_name(r["NAME"])
        lat, lng = float(r["INTPTLAT"]), float(r["INTPTLONG"])
        best_geoid, best_d = "", 1e9
        for c in county_by_state.get(state, []):
            d = _haversine_km(lat, lng, float(c["lat"]), float(c["lng"]))
            if d < best_d:
                best_geoid, best_d = str(c["county_geoid"]), d
        try:
            area = float(r.get("ALAND_SQMI") or 0)
        except ValueError:
            area = 0.0
        places.append({"place_geoid": r["GEOID"], "place_name": name, "state_code": state, "place_type": ptype,
                       "lat": lat, "lng": lng, "area_sqmi": area, "county_geoid": best_geoid,
                       "cbsa_code": county_to_cbsa.get(best_geoid, "")})

    # ── ZCTA (state from nearest place) ──────────────────────────────────────
    grid: Dict[Tuple[int, int], List[Dict[str, object]]] = {}
    for p in places:
        grid.setdefault((math.floor(float(p["lat"])), math.floor(float(p["lng"]))), []).append(p)
    zctas: List[Dict[str, object]] = []
    for r in _read_zip_table(downloads["zcta"]):
        lat, lng = float(r["INTPTLAT"]), float(r["INTPTLONG"])
        best, best_d = None, 1e9
        gl, gn = math.floor(lat), math.floor(lng)
        for radius in (1, 3, 8):  # widen the search only when the neighbourhood has no places
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    for p in grid.get((gl + dy, gn + dx), ()):
                        d = (float(p["lat"]) - lat) ** 2 + (float(p["lng"]) - lng) ** 2
                        if d < best_d:
                            best, best_d = p, d
            if best is not None:
                break
        zctas.append({"zip": r["GEOID"], "lat": lat, "lng": lng,
                      "state_code": best["state_code"] if best else "", "place_name": best["place_name"] if best else ""})

    def write(name: str, rows: List[Dict[str, object]], fields: List[str]) -> None:
        with open(GEO_DIR / name, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write("cbsa_delineation.csv", cbsa_rows,
          ["cbsa_code", "cbsa_title", "cbsa_type", "county_geoid", "county_name", "state_code", "central_outlying"])
    write("counties.csv", counties, ["county_geoid", "county_name", "state_code", "lat", "lng"])
    write("places.csv", places,
          ["place_geoid", "place_name", "state_code", "place_type", "lat", "lng", "area_sqmi", "county_geoid",
           "cbsa_code"])
    write("zcta.csv", zctas, ["zip", "lat", "lng", "state_code", "place_name"])

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["# Census reference data (generated)", "", f"Built: {stamp} by `scripts/data/fetch_census_geo.py`", "",
             "| File | Source URL | SHA-256 |", "|---|---|---|"]
    for label, url in (("cbsa", URL_CBSA), ("places", URL_PLACES), ("counties", URL_COUNTIES), ("zcta", URL_ZCTA)):
        lines.append(f"| {label} | {url} | `{hashlib.sha256(downloads[label]).hexdigest()}` |")
    lines += ["", "Place-to-county assignment uses the nearest county internal point inside the same state "
                  "(approximation near borders). ZIP-to-place uses the nearest place internal point.", ""]
    (GEO_DIR / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")
    return {"cbsa_rows": len(cbsa_rows), "counties": len(counties), "places": len(places), "zcta": len(zctas)}


_ = re  # keep import for callers that extend cleaning rules
