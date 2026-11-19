"""
State licensing registry source.

North Carolina (NC DHSR, official public downloads, verified live):
  Home care agencies      https://info.ncdhhs.gov/dhsr/data/hclist.xlsx   (list page: /dhsr/ahc/listings.html)
  Home health agencies    https://info.ncdhhs.gov/dhsr/data/hhlist.xlsx
  Home care + hospice     https://info.ncdhhs.gov/dhsr/data/hchos.xlsx
  Hospice (all)           https://info.ncdhhs.gov/dhsr/data/hoslist.xlsx  (list page: /dhsr/reports.htm)
  Home health + hospice   https://info.ncdhhs.gov/dhsr/data/hhhos.xlsx
  Adult care homes        https://info.ncdhhs.gov/dhsr/data/Ahlist.xlsx   (list page: /dhsr/acls/faclistings.html)
  Family care homes       https://info.ncdhhs.gov/dhsr/data/Fchlist.xlsx
  Nursing homes           https://info.ncdhhs.gov/dhsr/data/Nhlist_a.xlsx (list page: /dhsr/nhlcs/facilities.html)

The spreadsheets are cached under data/registry/nc/ (refreshed after 7 days). Rows are mapped by header name.
Other states have no adapter and report `unavailable`. Named people (administrators, directors) are included only
when the official file lists a person's name.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

from packages.discovery.http import paced_request
from packages.discovery.names import looks_like_person
from packages.discovery.models import (
    Budget,
    FactRecord,
    OrgRecord,
    PersonRecord,
    PhoneEntry,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.discovery.relevance import registry_kinds
from packages.leadintel.deduplication import normalize_string

logger = logging.getLogger("discovery.source.state_registry")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
def _registry_dir() -> Path:
    """data/registry/nc, or $DISCOVERY_REGISTRY_DIR/nc (used by tests)."""
    base = os.getenv("DISCOVERY_REGISTRY_DIR")
    return (Path(base) if base else PROJECT_ROOT / "data" / "registry") / "nc"

NC_BASE = "https://info.ncdhhs.gov/dhsr/data"
CACHE_MAX_AGE_DAYS = 7.0

NC_FILES: Dict[str, Dict[str, Any]] = {
    "home_care": {"file": "hclist.xlsx", "category": "Home Care Agency", "kinds": {"home_health"},
                  "page": "https://info.ncdhhs.gov/dhsr/ahc/listings.html"},
    "home_health": {"file": "hhlist.xlsx", "category": "Home Health Agency", "kinds": {"home_health"},
                    "page": "https://info.ncdhhs.gov/dhsr/ahc/listings.html"},
    "home_care_hospice": {"file": "hchos.xlsx", "category": "Home Care with Hospice", "kinds": {"hospice", "home_health"},
                          "page": "https://info.ncdhhs.gov/dhsr/ahc/listings.html"},
    "hospice": {"file": "hoslist.xlsx", "category": "Hospice", "kinds": {"hospice"},
                "page": "https://info.ncdhhs.gov/dhsr/reports.htm"},
    "home_health_hospice": {"file": "hhhos.xlsx", "category": "Home Health with Hospice", "kinds": {"hospice", "home_health"},
                            "page": "https://info.ncdhhs.gov/dhsr/reports.htm"},
    "adult_care": {"file": "Ahlist.xlsx", "category": "Adult Care Home", "kinds": {"adult_care"},
                   "page": "https://info.ncdhhs.gov/dhsr/acls/faclistings.html"},
    "family_care": {"file": "Fchlist.xlsx", "category": "Family Care Home", "kinds": {"adult_care"},
                    "page": "https://info.ncdhhs.gov/dhsr/acls/faclistings.html"},
    "nursing_home": {"file": "Nhlist_a.xlsx", "category": "Nursing Home", "kinds": {"nursing_home"},
                     "page": "https://info.ncdhhs.gov/dhsr/nhlcs/facilities.html"},
}

def _norm_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\n", " ")).strip().lower()


def parse_dhsr_xlsx(content: bytes) -> List[Dict[str, str]]:
    """Parse a DHSR facility listing workbook into dicts keyed by normalized header names."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    header_idx = next((i for i, r in enumerate(rows)
                       if r and any(_norm_header(c) == "license #" for c in r)), None)
    if header_idx is None:
        raise ValueError("DHSR workbook has no 'License #' header row (format changed)")
    headers = [_norm_header(c) for c in rows[header_idx]]
    out: List[Dict[str, str]] = []
    for r in rows[header_idx + 1:]:
        if not r:
            continue
        rec: Dict[str, str] = {}
        for i, cell in enumerate(r):
            if i < len(headers) and headers[i] and cell is not None and str(cell).strip():
                rec.setdefault(headers[i], str(cell).strip())
        if rec.get("license #"):
            out.append(rec)
    return out


def map_dhsr_row(rec: Dict[str, str], category: str) -> Dict[str, Any]:
    name = rec.get("dba name") or rec.get("name of licensee legal name") or ""
    person_name = (rec.get("administrator name") or rec.get("director name") or rec.get("correspondence name") or "")
    person_title = (rec.get("director title") or rec.get("correspondence title")
                    or ("Administrator" if rec.get("administrator name") else ""))
    beds = rec.get("bed count") or rec.get("nh total beds")
    return {
        "name": name.strip(), "legal_name": rec.get("name of licensee legal name", "").strip(),
        "license": rec.get("license #", "").strip(), "county": rec.get("county", "").strip(),
        "phone": rec.get("facility contact number", "").strip(), "contact_name": rec.get("facility contact name", "").strip(),
        "person_name": person_name.strip(), "person_title": person_title.strip(),
        "street": rec.get("site address", "").strip(), "city": rec.get("site city", "").strip(),
        "state": (rec.get("site state") or "NC").strip(), "zip": rec.get("site zip", "").strip(),
        "beds": beds, "expiry": rec.get("expiry date", ""), "category": category,
    }


class NcDhsrAdapter:
    """Official North Carolina DHSR licensing lists."""
    state_code = "NC"

    @classmethod
    def _cache_path(cls, file_name: str) -> Path:
        return _registry_dir() / (Path(file_name).stem + ".json")

    @classmethod
    async def load_file(cls, key: str, budget: Budget) -> List[Dict[str, Any]]:
        spec = NC_FILES[key]
        cache = cls._cache_path(spec["file"])
        if cache.exists() and (time.time() - cache.stat().st_mtime) / 86400.0 < CACHE_MAX_AGE_DAYS:
            return json.loads(cache.read_text(encoding="utf-8"))["rows"]
        url = f"{NC_BASE}/{spec['file']}"
        try:
            resp = await paced_request("discovery_state_registry", "GET", url,
                                       timeout=min(30.0, max(3.0, budget.remaining())))
            resp.raise_for_status()
            rows = await asyncio.to_thread(parse_dhsr_xlsx, resp.content)
            mapped = [map_dhsr_row(r, spec["category"]) for r in rows]
            _registry_dir().mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"url": url, "retrieved_at": time.time(), "rows": mapped}), encoding="utf-8")
            return mapped
        except Exception:
            if cache.exists():  # stale cache is better than nothing, and is reported as such by the caller
                logger.warning("DHSR download failed for %s; using stale cache", spec["file"])
                return json.loads(cache.read_text(encoding="utf-8"))["rows"]
            raise


STATE_ADAPTERS: Dict[str, Any] = {"NC": NcDhsrAdapter}


def _row_matches_geo(row: Dict[str, Any], geo: Dict[str, Any]) -> bool:
    gtype = geo.get("type")
    if gtype == "zip":
        return row["zip"][:5] == str(geo.get("zip", ""))[:5]
    if gtype in ("county", "msa"):
        counties = {c.rsplit(",", 1)[0].strip().lower() for c in geo.get("counties", [])
                    if c.rsplit(",", 1)[-1].strip() == "NC"}
        if counties:
            return row["county"].lower() in counties
    if gtype in ("city", "msa", "county"):
        cities = {c.lower() for c in (geo.get("cities") or [geo.get("city")]) if c}
        return bool(cities) and row["city"].lower() in cities
    return gtype == "state"


class StateRegistrySource:
    def __init__(self, name: str = "state_registry") -> None:
        self.name = name
        self.source_type = "official_registry"
        self.weight = 1.4

    async def search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        async for res in self._execute_search(intent, budget):
            yield res

    async def _execute_search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        geo = intent.geography or {}
        if (geo.get("country_code") or "us") != "us":
            yield SourceResult(status=SourceStatus(
                name=self.name, status="empty", message="Not applicable: state licence lists cover U.S. states only"))
            return
        kinds = registry_kinds(intent)
        if not kinds:
            yield SourceResult(status=SourceStatus(
                name=self.name, status="empty", message="Not applicable: query is not about licensed care providers"))
            return
        states = [s for s in (geo.get("states") or ([geo["state"]] if geo.get("state") else [])) if s]
        unsupported = [s for s in states if s not in STATE_ADAPTERS]
        if "NC" not in states:
            yield SourceResult(status=SourceStatus(
                name=self.name, status="unavailable",
                message="No state licensing adapter for " + (", ".join(states) or "this location")
                        + " (implemented: " + ", ".join(sorted(STATE_ADAPTERS)) + ")"))
            return

        wanted = [k for k, spec in NC_FILES.items() if spec["kinds"] & kinds]
        loaded = await asyncio.gather(*[NcDhsrAdapter.load_file(k, budget) for k in wanted], return_exceptions=True)
        orgs: List[OrgRecord] = []
        people: List[PersonRecord] = []
        facts: List[FactRecord] = []
        errors: List[str] = []
        seen_licenses: set = set()
        for key, result in zip(wanted, loaded):
            if isinstance(result, Exception):
                errors.append(f"{NC_FILES[key]['file']}: {type(result).__name__}")
                continue
            spec = NC_FILES[key]
            for row in result:
                if not row["name"] or row["license"] in seen_licenses or not _row_matches_geo(row, geo):
                    continue
                seen_licenses.add(row["license"])
                page = spec["page"]
                org = OrgRecord(
                    name=row["name"], canonical_name=row["name"], normalized_name=normalize_string(row["name"]),
                    category=row["category"], subcategories=["NC DHSR licensed"],
                    address={"street": row["street"], "city": row["city"], "state": row["state"],
                             "postal_code": row["zip"][:5], "country": "US", "county": row["county"]},
                    phones=[PhoneEntry(number=row["phone"], type="work", source_url=page)] if row["phone"] else [],
                    regulatory={"nc_license_number": row["license"], "nc_license_status": "Listed on DHSR roster",
                                "nc_legal_name": row["legal_name"], "nc_county": row["county"],
                                **({"nc_beds": row["beds"]} if row["beds"] else {}),
                                **({"nc_license_expiry": row["expiry"]} if row["expiry"] else {})},
                    sources=[{"source": self.name, "url": f"{NC_BASE}/{spec['file']}", "page": page,
                              "license": row["license"]}],
                    verified=True, first_seen_source=self.name, confidence=0.96, quality_score=0.92,
                    metadata={"source_file": spec["file"]},
                )
                orgs.append(org)
                facts.append(FactRecord(entity_type="organization", entity_id=org.id, field="nc_license",
                                        value={"license": row["license"], "category": row["category"],
                                               "county": row["county"]},
                                        source=self.name, source_url=f"{NC_BASE}/{spec['file']}", confidence=0.98))
                if row["person_name"] and looks_like_person(row["person_name"], [row["name"], row["legal_name"]]):
                    person = PersonRecord(
                        name=row["person_name"], title=row["person_title"] or "Facility contact",
                        role_type="administrator" if "admin" in (row["person_title"] or "").lower() else "director",
                        org_id=org.id, org_name=row["name"], city=row["city"], state="NC",
                        provenance="state_registry", verified=True, confidence=0.9,
                        source_url=f"{NC_BASE}/{spec['file']}",
                    )
                    people.append(person)
                    org.people.append(person)

        if not orgs and errors:
            yield SourceResult(status=SourceStatus(name=self.name, status="unavailable",
                                                   message="DHSR files unavailable: " + "; ".join(errors)[:250]))
            return
        notes = []
        if errors:
            notes.append("partial: " + "; ".join(errors)[:150])
        if unsupported:
            notes.append("no adapter for " + ", ".join(unsupported))
        yield SourceResult(orgs=orgs, people=people, facts=facts,
                           status=SourceStatus(name=self.name, status="ok" if orgs else "empty", count=len(orgs),
                                               message="; ".join(notes) or None))

    async def healthcheck(self) -> Dict[str, Any]:
        try:
            resp = await paced_request("discovery_state_registry", "HEAD", f"{NC_BASE}/hclist.xlsx", timeout=6.0)
            return {"source": self.name, "status": "healthy" if resp.status_code == 200 else "degraded",
                    "http_status": resp.status_code, "type": self.source_type}
        except Exception as exc:
            return {"source": self.name, "status": "unavailable", "error": exc.__class__.__name__,
                    "type": self.source_type}
