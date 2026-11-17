"""
Local database source: organizations and people stored by earlier discovery searches and imports
(schema discovery_dataextraction). It answers instantly and lets repeated searches build on earlier results.
Suppressed people are never returned; hand-entered (`manual_seed`) people only with include_unverified=true.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List

from packages.discovery.models import (
    Budget,
    EmailEntry,
    FactRecord,
    OrgRecord,
    PersonRecord,
    PhoneEntry,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.discovery.suppression import filter_people
from packages.infrastructure.db_connector import get_connection, release_connection

logger = logging.getLogger("discovery.source.local_db")

MAX_ROWS = 300
_SCHEMA = "discovery_dataextraction"


def _jlist(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except ValueError:
            return []
    return []


def _jdict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


def _terms(intent: SearchIntent) -> List[str]:
    out: List[str] = []
    for t in [*intent.categories, *intent.synonyms]:
        t = (t or "").strip().lower()
        if len(t) >= 3 and t not in out:
            out.append(t)
    return out[:8]


def _query_orgs(intent: SearchIntent, include_unverified: bool) -> Dict[str, Any]:
    geo = intent.geography or {}
    states = [s for s in (geo.get("states") or ([geo["state"]] if geo.get("state") else [])) if s]
    cities = [c for c in (geo.get("cities") or ([geo["city"]] if geo.get("city") else [])) if c]
    sql = [
        "SELECT id::text, canonical_name, normalized_name, category, subcategories, address_street, address_city,",
        "       address_state, address_postal_code, latitude, longitude, phones, emails, website, domain, hours,",
        "       rating, review_count, services, regulatory, social, quality_score, address_country",
        f"FROM {_SCHEMA}.organizations WHERE 1=1",
    ]
    params: List[Any] = []
    terms = _terms(intent)
    if terms:
        like = [f"%{t}%" for t in terms]
        sql.append("AND (category ILIKE ANY(%s) OR canonical_name ILIKE ANY(%s))")
        params += [like, like]
    if geo.get("type") == "zip" and geo.get("zip"):
        sql.append("AND address_postal_code = %s")
        params.append(geo["zip"])
    else:
        if states:
            sql.append("AND address_state = ANY(%s)")
            params.append(states)
        if cities and geo.get("type") in ("city", "msa", "place"):
            sql.append("AND lower(address_city) = ANY(%s)")
            params.append([c.lower() for c in cities])
        country = (geo.get("country_code") or "us").upper()
        if country != "US":
            # places outside the U.S. (OpenStreetMap geography): never mix in U.S. rows with the same city name
            sql.append("AND upper(coalesce(address_country, 'US')) = %s")
            params.append(country)
    sql.append("ORDER BY quality_score DESC, last_seen DESC LIMIT %s")
    params.append(MAX_ROWS)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("\n".join(sql), tuple(params))
            org_rows = cur.fetchall()
            people_rows: List[tuple] = []
            if org_rows:
                p_sql = (
                    "SELECT id::text, full_name, normalized_name, title, role_type, org_id::text, org_name, headline, "
                    "city, region, country, profile_urls, emails, phones, provenance, verified "
                    f"FROM {_SCHEMA}.people WHERE NOT suppressed AND org_id = ANY(%s::uuid[])"
                )
                if not include_unverified:
                    p_sql += " AND provenance <> 'manual_seed'"
                cur.execute(p_sql, ([r[0] for r in org_rows],))
                people_rows = cur.fetchall()
        return {"orgs": org_rows, "people": people_rows}
    finally:
        release_connection(conn)


class LocalDBSource:
    def __init__(self, name: str = "local_db") -> None:
        self.name = name
        self.source_type = "database"
        self.weight = 1.0

    async def search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        async for res in self._execute_search(intent, budget):
            yield res

    async def _execute_search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        include_unverified = bool((intent.filters or {}).get("include_unverified", False))
        try:
            data = await asyncio.to_thread(_query_orgs, intent, include_unverified)
        except Exception as exc:
            yield SourceResult(status=SourceStatus(name=self.name, status="unavailable",
                                                   message=f"Database query failed: {type(exc).__name__}"))
            return

        orgs: List[OrgRecord] = []
        facts: List[FactRecord] = []
        for r in data["orgs"]:
            org = OrgRecord(
                id=r[0], name=r[1], canonical_name=r[1], normalized_name=r[2], category=r[3],
                subcategories=_jlist(r[4]),
                address={"street": r[5], "city": r[6], "state": r[7], "postal_code": r[8], "country": r[22] or "US"},
                latitude=float(r[9]) if r[9] is not None else None, longitude=float(r[10]) if r[10] is not None else None,
                phones=[PhoneEntry(**p) if isinstance(p, dict) else PhoneEntry(number=str(p)) for p in _jlist(r[11])],
                emails=[EmailEntry(**e) if isinstance(e, dict) else EmailEntry(value=str(e)) for e in _jlist(r[12])],
                website=r[13], domain=r[14], hours=_jlist(r[15]),
                rating=float(r[16]) if r[16] is not None else None, review_count=r[17],
                services=[str(s) for s in _jlist(r[18])], regulatory=_jdict(r[19]), social=_jdict(r[20]),
                quality_score=float(r[21]) if r[21] is not None else 0.5,
                sources=[{"source": self.name}], first_seen_source=self.name,
            )
            orgs.append(org)
            facts.append(FactRecord(entity_type="organization", entity_id=org.id, field="stored_record",
                                    value=org.canonical_name, source=self.name, confidence=0.8))

        by_id = {o.id: o for o in orgs}
        people: List[PersonRecord] = []
        for r in data["people"]:
            person = PersonRecord(
                id=r[0], name=r[1], full_name=r[1], normalized_name=r[2], title=r[3], role_type=r[4], org_id=r[5],
                org_name=r[6], headline=r[7], city=r[8], region=r[9], country=r[10] or "US",
                profile_urls=[str(u) for u in _jlist(r[11])],
                emails=[EmailEntry(**e) if isinstance(e, dict) else EmailEntry(value=str(e)) for e in _jlist(r[12])],
                phones=[PhoneEntry(**p) if isinstance(p, dict) else PhoneEntry(number=str(p)) for p in _jlist(r[13])],
                provenance=r[14] or "local_db", verified=bool(r[15]),
            )
            people.append(person)
        people = filter_people(people)
        for p in people:
            if p.org_id in by_id:
                by_id[p.org_id].people.append(p)

        yield SourceResult(
            organizations=orgs, people=people, facts=facts,
            status=SourceStatus(name=self.name, status="ok" if orgs else "empty", count=len(orgs) + len(people)),
        )

    async def healthcheck(self) -> Dict[str, Any]:
        try:
            await asyncio.to_thread(self._ping)
            return {"source": self.name, "status": "healthy", "type": self.source_type}
        except Exception as exc:
            return {"source": self.name, "status": "unavailable", "error": exc.__class__.__name__, "type": self.source_type}

    @staticmethod
    def _ping() -> None:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM {_SCHEMA}.organizations LIMIT 1")
        finally:
            release_connection(conn)
