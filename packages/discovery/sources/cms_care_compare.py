"""
CMS Care Compare source (official Medicare provider data).

Datasets queried through the CMS Provider Data Catalog datastore API (verified against the live catalog
https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items):

  6jpm-sxkc  Home Health Care Agencies        https://data.cms.gov/provider-data/dataset/6jpm-sxkc
  4pq5-n9py  Nursing Home Provider Information https://data.cms.gov/provider-data/dataset/4pq5-n9py
  yc9t-dgbk  Hospice - General Information     https://data.cms.gov/provider-data/dataset/yc9t-dgbk

Query endpoint: POST https://data.cms.gov/provider-data/api/1/datastore/query/{dataset}/0
(body: limit, offset, count, results, conditions[{property,value,operator}]). Field names below are the ones
returned by that API. If the API cannot be reached or the response shape changes the source reports
`unavailable` with zero records. It never invents data.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Tuple

import httpx

from packages.discovery.http import cached_json, paced_request
from packages.discovery.models import (
    Budget,
    FactRecord,
    OrgRecord,
    PhoneEntry,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.discovery.relevance import registry_kinds
from packages.leadintel.deduplication import normalize_string

logger = logging.getLogger("discovery.source.cms")

CMS_BASE = "https://data.cms.gov/provider-data"
CMS_QUERY_URL = CMS_BASE + "/api/1/datastore/query/{dataset}/0"
MAX_RECORDS_PER_DATASET = 400
PAGE_SIZE = 100
CACHE_TTL_SECONDS = 6 * 3600

SERVICE_FLAGS = {
    "offers_nursing_care_services": "nursing_care",
    "offers_physical_therapy_services": "physical_therapy",
    "offers_occupational_therapy_services": "occupational_therapy",
    "offers_speech_pathology_services": "speech_pathology",
    "offers_medical_social_services": "medical_social",
    "offers_home_health_aide_services": "home_health_aide",
}

DATASETS: Dict[str, Dict[str, Any]] = {
    "home_health": {
        "id": "6jpm-sxkc", "category": "Home Health Agency", "subcategory": "Medicare-certified home health",
        "name": "provider_name", "address": "address", "city": "citytown", "zip": "zip_code",
        "phone": "telephone_number", "ccn": "cms_certification_number_ccn", "ownership": "type_of_ownership",
        "rating": "quality_of_patient_care_star_rating", "county": None, "certified": "certification_date",
    },
    "nursing_home": {
        "id": "4pq5-n9py", "category": "Nursing Home", "subcategory": "Medicare/Medicaid-certified nursing home",
        "name": "provider_name", "address": "provider_address", "city": "citytown", "zip": "zip_code",
        "phone": "telephone_number", "ccn": "cms_certification_number_ccn", "ownership": "ownership_type",
        "rating": "overall_rating", "county": "countyparish", "beds": "number_of_certified_beds", "certified": None,
    },
    "hospice": {
        "id": "yc9t-dgbk", "category": "Hospice", "subcategory": "Medicare-certified hospice",
        "name": "facility_name", "address": "address_line_1", "city": "citytown", "zip": "zip_code",
        "phone": "telephone_number", "ccn": "cms_certification_number_ccn", "ownership": "ownership_type",
        "rating": None, "county": "countyparish", "certified": "certification_date",
    },
}


def _case_variants(values: List[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        for variant in (v.upper(), v.title(), v):
            if variant not in out:
                out.append(variant)
    return out


def build_conditions(cfg: Dict[str, Any], geo: Dict[str, Any], state: str) -> List[Dict[str, Any]]:
    """Datastore conditions for one dataset and one state."""
    conds: List[Dict[str, Any]] = [{"property": "state", "value": state, "operator": "="}]
    gtype = geo.get("type")
    if gtype == "zip" and geo.get("zip"):
        conds.append({"property": cfg["zip"], "value": geo["zip"], "operator": "="})
        return conds
    if gtype in ("county", "msa") and cfg.get("county"):
        counties = [c.rsplit(",", 1)[0].strip() for c in geo.get("counties", []) if c.rsplit(",", 1)[-1].strip() == state]
        if counties:
            conds.append({"property": cfg["county"], "value": _case_variants(counties), "operator": "IN"})
            return conds
    if gtype in ("city", "msa", "county"):
        cities = geo.get("cities") or ([geo["city"]] if geo.get("city") else [])
        if cities:
            conds.append({"property": cfg["city"], "value": _case_variants(cities[:200]), "operator": "IN"})
    return conds


class CMSCareCompareSource:
    def __init__(self, name: str = "cms_care_compare") -> None:
        self.name = name
        self.source_type = "official_registry"
        self.weight = 1.5

    async def search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        async for res in self._execute_search(intent, budget):
            yield res

    async def _query_dataset(self, kind: str, state: str, geo: Dict[str, Any], budget: Budget) -> List[Dict[str, Any]]:
        cfg = DATASETS[kind]
        conditions = build_conditions(cfg, geo, state)
        url = CMS_QUERY_URL.format(dataset=cfg["id"])
        rows: List[Dict[str, Any]] = []
        offset = 0
        while len(rows) < MAX_RECORDS_PER_DATASET and not budget.is_expired():
            body = {"limit": PAGE_SIZE, "offset": offset, "count": True, "results": True, "conditions": conditions}
            cache_key = f"cms:{cfg['id']}:{offset}:{repr(conditions)}"

            async def fetch(body: Dict[str, Any] = body) -> Dict[str, Any]:
                resp = await paced_request("discovery_cms", "POST", url, timeout=min(10.0, max(1.0, budget.remaining())),
                                           json=body)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict) or "results" not in data:
                    raise ValueError("unexpected CMS response shape")
                return data

            data = await cached_json(cache_key, fetch, CACHE_TTL_SECONDS)
            page = data.get("results") or []
            rows.extend(page)
            total = int(data.get("count") or 0)
            offset += PAGE_SIZE
            if not page or offset >= total:
                break
        for r in rows:
            r["_dataset_kind"] = kind
        return rows

    async def _execute_search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        geo = intent.geography or {}
        if (geo.get("country_code") or "us") != "us":
            yield SourceResult(status=SourceStatus(name=self.name, status="empty",
                                                   message="Not applicable: Medicare data covers the United States only"))
            return
        kinds = sorted(registry_kinds(intent) & set(DATASETS))
        if not kinds:
            yield SourceResult(status=SourceStatus(
                name=self.name, status="empty",
                message="Not applicable: query is not about Medicare-certified care providers"))
            return
        states = [s for s in (geo.get("states") or ([geo["state"]] if geo.get("state") else [])) if s]
        if not states:
            yield SourceResult(status=SourceStatus(name=self.name, status="empty",
                                                   message="No U.S. state resolved for this query"))
            return

        tasks = [(kind, state) for kind in kinds for state in states]
        results = await asyncio.gather(*[self._query_dataset(k, s, geo, budget) for k, s in tasks],
                                       return_exceptions=True)
        records: List[Dict[str, Any]] = []
        errors: List[str] = []
        for (kind, state), res in zip(tasks, results):
            if isinstance(res, Exception):
                errors.append(f"{DATASETS[kind]['id']}/{state}: {self._describe(res)}")
            else:
                records.extend(res)

        if not records and errors:
            blocked = any("HTTP 403" in e or "HTTP 401" in e or "HTTP 429" in e for e in errors)
            yield SourceResult(status=SourceStatus(
                name=self.name, status="blocked" if blocked else "unavailable", message="; ".join(errors)[:300]))
            return

        orgs, facts = self._map_records(records)
        yield SourceResult(
            orgs=orgs, facts=facts,
            status=SourceStatus(name=self.name, status="ok" if orgs else "empty", count=len(orgs),
                                message=("; ".join(errors)[:300] if errors else None)),
        )

    @staticmethod
    def _describe(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            return f"HTTP {exc.response.status_code}"
        return exc.__class__.__name__

    def _map_records(self, records: List[Dict[str, Any]]) -> Tuple[List[OrgRecord], List[FactRecord]]:
        orgs: List[OrgRecord] = []
        facts: List[FactRecord] = []
        seen: set = set()
        for row in records:
            kind = row["_dataset_kind"]
            cfg = DATASETS[kind]
            name = str(row.get(cfg["name"]) or "").strip()
            ccn = str(row.get(cfg["ccn"]) or "").strip()
            if not name or (kind, ccn or name) in seen:
                continue
            seen.add((kind, ccn or name))

            source_url = f"{CMS_BASE}/dataset/{cfg['id']}"
            phone = "".join(ch for ch in str(row.get(cfg["phone"]) or "") if ch.isdigit())
            rating_raw = row.get(cfg["rating"]) if cfg.get("rating") else None
            try:
                rating = float(rating_raw) if rating_raw not in (None, "", "Not Available") else None
            except (TypeError, ValueError):
                rating = None
            ownership = str(row.get(cfg["ownership"]) or "").strip()
            services = [label for col, label in SERVICE_FLAGS.items() if str(row.get(col, "")).lower() == "yes"]

            org = OrgRecord(
                name=name, canonical_name=name, normalized_name=normalize_string(name),
                category=cfg["category"], subcategories=[cfg["subcategory"]],
                address={"street": str(row.get(cfg["address"]) or "").strip(),
                         "city": str(row.get(cfg["city"]) or "").strip().title(),
                         "state": str(row.get("state") or "").strip(),
                         "postal_code": str(row.get(cfg["zip"]) or "").strip(), "country": "US"},
                phones=[PhoneEntry(number=phone, type="work", source_url=source_url, verified=False)] if phone else [],
                services=services,
                regulatory={"cms_dataset": cfg["id"], "cms_ccn": ccn, "cms_ownership": ownership,
                            "cms_star_rating": rating, "cms_kind": kind,
                            **({"cms_certified_beds": row.get(cfg["beds"])} if cfg.get("beds") else {}),
                            **({"cms_county": row.get(cfg["county"])} if cfg.get("county") else {})},
                sources=[{"source": self.name, "url": source_url, "dataset": cfg["id"], "ccn": ccn}],
                verified=True, first_seen_source=self.name, confidence=0.95, quality_score=0.9,
                metadata={"dataset_id": cfg["id"], "source_url": source_url},
            )
            orgs.append(org)
            facts.append(FactRecord(entity_type="organization", entity_id=org.id, field="cms_certification",
                                    value={"ccn": ccn, "ownership": ownership, "dataset": cfg["id"]},
                                    source=self.name, source_url=source_url, confidence=0.98))
            if rating is not None:
                facts.append(FactRecord(entity_type="organization", entity_id=org.id, field="cms_star_rating",
                                        value=rating, source=self.name, source_url=source_url, confidence=0.98))
        return orgs, facts

    async def healthcheck(self) -> Dict[str, Any]:
        try:
            resp = await paced_request("discovery_cms", "GET", f"{CMS_BASE}/api/1/metastore/schemas/dataset/items/6jpm-sxkc",
                                       timeout=6.0)
            return {"source": self.name, "status": "healthy" if resp.status_code == 200 else "degraded",
                    "http_status": resp.status_code, "type": self.source_type}
        except Exception as exc:
            return {"source": self.name, "status": "unavailable", "error": exc.__class__.__name__,
                    "type": self.source_type}
