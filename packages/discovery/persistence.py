"""
Transactional persistence for the Discovery Engine (schema discovery_dataextraction).

One search = one transaction: organizations, people, facts, search run and ranked results are written together.
Repeated searches update existing rows instead of duplicating them: an organization is matched by official
identifier (CMS CCN / state license), then website domain, then normalized name + ZIP. Suppressed people,
emails and phones are removed before anything is written.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from psycopg2.extras import execute_values

from packages.discovery.models import (
    FactRecord,
    OrgRecord,
    PersonRecord,
    SearchIntent,
    SourceStatus,
)
from packages.discovery.resolver import is_identity_domain, name_similarity
from packages.discovery.suppression import filter_organization, filter_people
from packages.infrastructure.db_connector import get_connection, release_connection

logger = logging.getLogger("discovery.persistence")

_NS = uuid.UUID("6b1d6a0e-3a53-4c3e-9f55-0d0a5f1e7a11")
SCHEMA = "discovery_dataextraction"


@dataclass
class PersistResult:
    ok: bool = False
    org_ids: Dict[str, str] = field(default_factory=dict)      # in-memory id -> stored id
    person_ids: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None


def _stable_org_key(org: OrgRecord) -> str:
    reg = org.regulatory or {}
    if reg.get("cms_ccn"):
        return f"ccn:{reg['cms_ccn']}"
    if reg.get("nc_license_number"):
        return f"nclic:{reg['nc_license_number']}"
    if is_identity_domain(org.domain):
        # domain + name: a domain alone can be shared (chains, directory pages) and must not merge different rows
        return f"domain:{org.domain}|{(org.normalized_name or org.name).lower().strip()}"
    return f"name:{(org.normalized_name or org.name).lower().strip()}|{str(org.address.get('postal_code') or '')[:5]}"


def stable_org_id(org: OrgRecord) -> str:
    return str(uuid.uuid5(_NS, _stable_org_key(org)))


def stable_person_id(person: PersonRecord, org_stored_id: Optional[str]) -> str:
    return str(uuid.uuid5(_NS, f"person:{(person.normalized_name or person.name).lower().strip()}|{org_stored_id or ''}"))


def _j(value: Any) -> str:
    return json.dumps(value, default=str)


def _find_existing_org_ids(cur: Any, orgs: List[OrgRecord]) -> Dict[str, str]:
    """Map in-memory org id -> id of an already stored row for the same real-world organization."""
    ccns = [o.regulatory.get("cms_ccn") for o in orgs if o.regulatory.get("cms_ccn")]
    lics = [o.regulatory.get("nc_license_number") for o in orgs if o.regulatory.get("nc_license_number")]
    domains = [o.domain for o in orgs if o.domain]
    names = [(o.normalized_name or o.name).lower().strip() for o in orgs]
    cur.execute(
        f"""
        SELECT id::text, normalized_name, COALESCE(address_postal_code, ''), domain,
               regulatory->>'cms_ccn', regulatory->>'nc_license_number'
        FROM {SCHEMA}.organizations
        WHERE normalized_name = ANY(%s) OR domain = ANY(%s)
           OR regulatory->>'cms_ccn' = ANY(%s) OR regulatory->>'nc_license_number' = ANY(%s)
        """,
        (names, domains or [""], ccns or [""], lics or [""]),
    )
    rows = cur.fetchall()
    by_ccn = {r[4]: r[0] for r in rows if r[4]}
    by_lic = {r[5]: r[0] for r in rows if r[5]}
    by_domain: Dict[str, List[Tuple[str, str]]] = {}
    for r in rows:
        if r[3]:
            by_domain.setdefault(r[3], []).append((r[0], r[1] or ""))
    by_name_zip = {(r[1], r[2]): r[0] for r in rows}
    found: Dict[str, str] = {}
    for o in orgs:
        zip5 = str(o.address.get("postal_code") or "")[:5]
        norm = (o.normalized_name or o.name).lower().strip()
        domain_hit = None
        if is_identity_domain(o.domain):
            # same website AND a similar name: the same organization stored by an earlier search
            domain_hit = next((rid for rid, rname in by_domain.get(o.domain, [])
                               if name_similarity(rname, norm) >= 0.34), None)
        hit = (by_ccn.get(o.regulatory.get("cms_ccn")) or by_lic.get(o.regulatory.get("nc_license_number"))
               or domain_hit or by_name_zip.get((norm, zip5)))
        if hit:
            found[o.id] = hit
    return found


def persist_discovery_search(
    run_id: str,
    query: str,
    intent: SearchIntent,
    organizations: List[OrgRecord],
    people: List[PersonRecord],
    facts: List[FactRecord],
    source_statuses: List[SourceStatus],
    timings: Optional[Dict[str, Any]] = None,
    requested_by: Optional[str] = None,
) -> PersistResult:
    """Persist one search. Never raises. Returns the id mapping so callers can expose stored ids."""
    result = PersistResult()
    clean_orgs = [filter_organization(o) for o in organizations]
    clean_people = filter_people(people)
    kept_person_ids = {p.id for p in clean_people}
    suppressed_person_ids = {p.id for p in people} - kept_person_ids
    for o in clean_orgs:
        o.people = [p for p in o.people if p.id in kept_person_ids]
    clean_facts = [f for f in facts if f.entity_id not in suppressed_person_ids]

    conn = None
    try:
        conn = get_connection()
        if not conn:
            result.error = "database unavailable"
            return result
        with conn.cursor() as cur:
            existing = _find_existing_org_ids(cur, clean_orgs) if clean_orgs else {}
            for o in clean_orgs:
                result.org_ids[o.id] = existing.get(o.id) or stable_org_id(o)

            org_rows: Dict[str, tuple] = {}
            for o in clean_orgs:
                sid = result.org_ids[o.id]
                a = o.address or {}
                reg = {**(o.metadata or {}), **(o.regulatory or {})} if o.regulatory else (o.metadata or {})
                org_rows[sid] = (
                    sid, o.name or o.canonical_name, (o.normalized_name or o.name).lower().strip(), o.category,
                    _j(o.subcategories or []), a.get("street"), a.get("city"), a.get("state"), a.get("postal_code"),
                    a.get("country", "US"), o.latitude, o.longitude,
                    _j([p.model_dump() for p in o.phones]), _j([e.model_dump() for e in o.emails]),
                    o.website, o.domain, _j(o.hours or []), o.rating, o.review_count or 0, _j(o.services or []),
                    _j(reg), _j(o.social or {}), o.quality_score,
                )
            if org_rows:
                execute_values(
                    cur,
                    f"""
                    INSERT INTO {SCHEMA}.organizations (
                        id, canonical_name, normalized_name, category, subcategories,
                        address_street, address_city, address_state, address_postal_code, address_country,
                        latitude, longitude, phones, emails, website, domain, hours,
                        rating, review_count, services, regulatory, social, quality_score
                    ) VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        canonical_name = EXCLUDED.canonical_name,
                        category = COALESCE(EXCLUDED.category, {SCHEMA}.organizations.category),
                        address_street = COALESCE(EXCLUDED.address_street, {SCHEMA}.organizations.address_street),
                        address_city = COALESCE(EXCLUDED.address_city, {SCHEMA}.organizations.address_city),
                        address_state = COALESCE(EXCLUDED.address_state, {SCHEMA}.organizations.address_state),
                        address_postal_code = COALESCE(EXCLUDED.address_postal_code, {SCHEMA}.organizations.address_postal_code),
                        latitude = COALESCE(EXCLUDED.latitude, {SCHEMA}.organizations.latitude),
                        longitude = COALESCE(EXCLUDED.longitude, {SCHEMA}.organizations.longitude),
                        website = COALESCE(EXCLUDED.website, {SCHEMA}.organizations.website),
                        domain = COALESCE(EXCLUDED.domain, {SCHEMA}.organizations.domain),
                        rating = COALESCE(EXCLUDED.rating, {SCHEMA}.organizations.rating),
                        review_count = GREATEST(EXCLUDED.review_count, {SCHEMA}.organizations.review_count),
                        phones = CASE WHEN EXCLUDED.phones = '[]'::jsonb THEN {SCHEMA}.organizations.phones ELSE EXCLUDED.phones END,
                        emails = CASE WHEN EXCLUDED.emails = '[]'::jsonb THEN {SCHEMA}.organizations.emails ELSE EXCLUDED.emails END,
                        services = CASE WHEN EXCLUDED.services = '[]'::jsonb THEN {SCHEMA}.organizations.services ELSE EXCLUDED.services END,
                        regulatory = {SCHEMA}.organizations.regulatory || EXCLUDED.regulatory,
                        social = {SCHEMA}.organizations.social || EXCLUDED.social,
                        quality_score = GREATEST(EXCLUDED.quality_score, {SCHEMA}.organizations.quality_score),
                        last_seen = NOW()
                    """,
                    list(org_rows.values()),
                    page_size=500,
                    template="(%s::uuid,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s::jsonb,%s,%s,"
                             "%s::jsonb,%s::jsonb,%s::jsonb,%s)",
                )

            # People: reuse an existing row for the same name + organization
            person_rows: Dict[str, tuple] = {}
            if clean_people:
                cur.execute(
                    f"SELECT id::text, normalized_name, COALESCE(org_id::text, '') FROM {SCHEMA}.people "
                    f"WHERE normalized_name = ANY(%s)",
                    ([(p.normalized_name or p.name).lower().strip() for p in clean_people],),
                )
                existing_people = {(r[1], r[2]): r[0] for r in cur.fetchall()}
            else:
                existing_people = {}
            for p in clean_people:
                org_sid = result.org_ids.get(p.org_id) if p.org_id else None
                norm = (p.normalized_name or p.name).lower().strip()
                sid = existing_people.get((norm, org_sid or "")) or stable_person_id(p, org_sid)
                result.person_ids[p.id] = sid
                person_rows[sid] = (
                    sid, p.name or p.full_name, norm, p.title, p.role_type, org_sid, p.org_name, p.headline, p.city,
                    p.state or p.region, p.country or "US", _j(p.profile_urls or []),
                    _j([e.model_dump() for e in p.emails]), _j([ph.model_dump() for ph in p.phones]),
                    p.provenance, p.verified, False,
                )
            if person_rows:
                execute_values(
                    cur,
                    f"""
                    INSERT INTO {SCHEMA}.people (
                        id, full_name, normalized_name, title, role_type, org_id, org_name, headline, city, region,
                        country, profile_urls, emails, phones, provenance, verified, suppressed
                    ) VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        title = COALESCE(EXCLUDED.title, {SCHEMA}.people.title),
                        role_type = COALESCE(EXCLUDED.role_type, {SCHEMA}.people.role_type),
                        profile_urls = CASE WHEN EXCLUDED.profile_urls = '[]'::jsonb THEN {SCHEMA}.people.profile_urls
                                            ELSE EXCLUDED.profile_urls END,
                        emails = CASE WHEN EXCLUDED.emails = '[]'::jsonb THEN {SCHEMA}.people.emails ELSE EXCLUDED.emails END,
                        phones = CASE WHEN EXCLUDED.phones = '[]'::jsonb THEN {SCHEMA}.people.phones ELSE EXCLUDED.phones END,
                        verified = {SCHEMA}.people.verified OR EXCLUDED.verified,
                        last_seen = NOW()
                    """,
                    list(person_rows.values()),
                    page_size=500,
                    template="(%s::uuid,%s,%s,%s,%s,%s::uuid,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s)",
                )

            # Facts (de-duplicated: ON CONFLICT cannot touch one row twice in a statement)
            fact_rows: Dict[Tuple[str, str, str, str, str], tuple] = {}
            for f in clean_facts:
                if f.entity_type == "organization":
                    sid = result.org_ids.get(f.entity_id)
                else:
                    sid = result.person_ids.get(f.entity_id)
                if not sid:
                    continue
                value = f.value if isinstance(f.value, (dict, list)) else {"value": f.value}
                key = (f.entity_type, sid, f.field, f.source, _j(value))
                fact_rows[key] = (f.entity_type, sid, f.field, _j(value), f.source, f.source_url, f.confidence)
            if fact_rows:
                execute_values(
                    cur,
                    f"""
                    INSERT INTO {SCHEMA}.facts (entity_type, entity_id, field, value, source, source_url, confidence)
                    VALUES %s
                    ON CONFLICT (entity_type, entity_id, field, source, value_hash)
                    DO UPDATE SET confidence = EXCLUDED.confidence, retrieved_at = NOW()
                    """,
                    list(fact_rows.values()),
                    page_size=1000,
                    template="(%s,%s::uuid,%s,%s::jsonb,%s,%s,%s)",
                )

            status_map = {st.name or st.source: {"status": st.status, "count": st.count, "elapsed_ms": st.elapsed_ms,
                                                  "message": st.message} for st in source_statuses}
            cur.execute(
                f"""
                INSERT INTO {SCHEMA}.search_runs (id, query, parsed, status, timings, source_status, requested_by,
                                                  started_at, finished_at)
                VALUES (%s::uuid, %s, %s::jsonb, 'completed', %s::jsonb, %s::jsonb, %s, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET timings = EXCLUDED.timings, source_status = EXCLUDED.source_status,
                    status = 'completed', finished_at = NOW()
                """,
                (run_id, query, _j(intent.model_dump()), _j(timings or {}), _j(status_map), requested_by),
            )

            results: Dict[Tuple[str, str], tuple] = {}
            for rank, o in enumerate(clean_orgs, 1):
                results[("organization", result.org_ids[o.id])] = (run_id, "organization", result.org_ids[o.id], rank, o.quality_score)
            for rank, p in enumerate(clean_people, 1):
                results[("person", result.person_ids[p.id])] = (run_id, "person", result.person_ids[p.id], rank, p.confidence)
            if results:
                execute_values(
                    cur,
                    f"""
                    INSERT INTO {SCHEMA}.search_results (run_id, entity_type, entity_id, rank, score) VALUES %s
                    ON CONFLICT (run_id, entity_type, entity_id) DO UPDATE SET rank = EXCLUDED.rank, score = EXCLUDED.score
                    """,
                    list(results.values()),
                    template="(%s::uuid,%s,%s::uuid,%s,%s)",
                )
        conn.commit()
        result.ok = True
        logger.info("Persisted search %s: %d orgs, %d people, %d facts", run_id, len(org_rows), len(person_rows), len(fact_rows))
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.org_ids, result.person_ids = {}, {}
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error("Failed to persist discovery search %s: %s", run_id, exc)
    finally:
        if conn:
            release_connection(conn)
    return result


def save_search_answer(run_id: str, answer: Dict[str, Any]) -> bool:
    """Store the composed answer so a finished search can be replayed after a restart."""
    conn = None
    try:
        conn = get_connection()
        if not conn:
            return False
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {SCHEMA}.search_runs SET answer = %s::jsonb WHERE id = %s::uuid", (_j(answer), run_id))
            updated = cur.rowcount
        conn.commit()
        return updated > 0
    except Exception as exc:
        logger.warning("Could not store answer for %s: %s", run_id, exc)
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False
    finally:
        if conn:
            release_connection(conn)


def get_search_run(run_id: str) -> Optional[Dict[str, Any]]:
    """Return the stored answer of a finished search (survives restarts), or None."""
    conn = None
    try:
        uuid.UUID(str(run_id))
    except ValueError:
        return None
    try:
        conn = get_connection()
        if not conn:
            return None
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id::text, query, parsed, status, timings, source_status, answer FROM {SCHEMA}.search_runs "
                f"WHERE id = %s::uuid",
                (run_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            answer = row[6] if isinstance(row[6], dict) else (json.loads(row[6]) if row[6] else None)
            base = {"id": row[0], "search_id": row[0], "query": row[1],
                    "parsed": row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}"),
                    "status": row[3], "timings": row[4], "source_status": row[5]}
            if answer:
                return {**base, **answer, "search_id": row[0], "status": row[3]}
            return {**base, "cards": [], "total_organizations": 0}
    except Exception as exc:
        logger.warning("Failed to fetch search run %s: %s", run_id, exc)
        return None
    finally:
        if conn:
            release_connection(conn)
