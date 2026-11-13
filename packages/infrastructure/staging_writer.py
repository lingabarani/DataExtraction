"""
DataExtraction — Canonical MDM Staging Writer
=============================================
Safely ingests raw scraper records into:
  - staging_dataextraction.staging_companies
  - staging_dataextraction.staging_people

Enforces MDM Layer 1 ingress standards with idempotency and JSON payload preservation.
Zero writes target legacy public serving views.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

import psycopg2.extras

logger = logging.getLogger("dataextraction.infrastructure.staging_writer")


def upsert_staging_record(cur, record: Dict[str, Any], source: str = "FEDERAL_SCRAPER") -> None:
    """
    Upserts a scraper dictionary into staging_dataextraction.staging_companies
    and (if decision-maker attributes exist) staging_dataextraction.staging_people.
    """
    if not record:
        return

    # Extract company identifiers
    company_name = record.get("company_name") or record.get("name")
    comp_id = record.get("company_id") or record.get("id") or f"{source.lower()}_{record.get('cik', '')}"
    domain = record.get("domain")

    # 1. Ingest Company into staging_companies if company information exists
    if company_name:
        cur.execute(
            """
            INSERT INTO staging_dataextraction.staging_companies (
                id, name, legal_name, website, domain, email, phone,
                city, state, state_code, zip_code, country,
                industry, naics_code, ein, cik, source,
                data_quality_score, raw_payload, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s::jsonb, NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                website = COALESCE(EXCLUDED.website, staging_companies.website),
                domain = COALESCE(EXCLUDED.domain, staging_companies.domain),
                email = COALESCE(EXCLUDED.email, staging_companies.email),
                phone = COALESCE(EXCLUDED.phone, staging_companies.phone),
                city = COALESCE(EXCLUDED.city, staging_companies.city),
                state = COALESCE(EXCLUDED.state, staging_companies.state),
                state_code = COALESCE(EXCLUDED.state_code, staging_companies.state_code),
                zip_code = COALESCE(EXCLUDED.zip_code, staging_companies.zip_code),
                industry = COALESCE(EXCLUDED.industry, staging_companies.industry),
                ein = COALESCE(EXCLUDED.ein, staging_companies.ein),
                cik = COALESCE(EXCLUDED.cik, staging_companies.cik),
                data_quality_score = GREATEST(COALESCE(EXCLUDED.data_quality_score, 0), COALESCE(staging_companies.data_quality_score, 0)),
                raw_payload = COALESCE(staging_companies.raw_payload, '{}'::jsonb) || EXCLUDED.raw_payload,
                updated_at = NOW();
            """,
            (
                str(comp_id),
                str(company_name),
                record.get("legal_name") or company_name,
                record.get("website") or (f"https://{domain}" if domain else None),
                domain,
                record.get("company_email") or record.get("email"),
                record.get("phone"),
                record.get("city"),
                record.get("state"),
                record.get("state_code"),
                record.get("zip_code"),
                record.get("country", "United States"),
                record.get("industry"),
                record.get("naics_code"),
                record.get("ein"),
                record.get("cik"),
                source,
                record.get("company_quality_score", 80),
                json.dumps(record),
            ),
        )

    # 2. Ingest Person into staging_people if person information exists
    full_name = record.get("full_name")
    work_email = record.get("email")
    title = record.get("title")

    if full_name or title or work_email:
        person_id = str(record.get("id") or f"{comp_id}_person")
        cur.execute(
            """
            INSERT INTO staging_dataextraction.staging_people (
                id, company_id, first_name, last_name, full_name,
                title, standardized_title, seniority_level, department,
                work_email, city, state, state_code, country,
                email_status, email_confidence_score, source,
                raw_payload, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s::jsonb, NOW()
            )
            ON CONFLICT (id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                title = EXCLUDED.title,
                work_email = COALESCE(EXCLUDED.work_email, staging_people.work_email),
                email_status = EXCLUDED.email_status,
                email_confidence_score = EXCLUDED.email_confidence_score,
                raw_payload = EXCLUDED.raw_payload,
                updated_at = NOW();
            """,
            (
                person_id,
                str(comp_id),
                record.get("first_name"),
                record.get("last_name"),
                full_name or "Executive Officer",
                title,
                record.get("standardized_title") or title,
                record.get("seniority_level", "EXECUTIVE"),
                record.get("department", "MANAGEMENT"),
                work_email,
                record.get("city"),
                record.get("state"),
                record.get("state_code"),
                record.get("country", "United States"),
                record.get("email_status", "UNKNOWN"),
                record.get("email_confidence_score", 0),
                source,
                json.dumps(record),
            ),
        )


def bulk_upsert_staging_records(
    cur,
    records: List[Dict[str, Any]],
    source: str = "LOAD_BENCHMARK",
) -> Tuple[int, int]:
    """
    High-throughput bulk upsert into staging_dataextraction.staging_companies
    and staging_dataextraction.staging_people using psycopg2 execute_values.

    Returns:
        Tuple[int, int]: (companies_upserted_count, people_upserted_count)
    """
    if not records:
        return 0, 0

    company_rows = []
    people_rows = []

    for r in records:
        company_name = r.get("company_name") or r.get("name")
        comp_id = r.get("company_id") or r.get("id") or f"{source.lower()}_{r.get('cik', '')}"
        domain = r.get("domain")

        if company_name:
            company_rows.append((
                str(comp_id),
                str(company_name),
                r.get("legal_name") or company_name,
                r.get("website") or (f"https://{domain}" if domain else None),
                domain,
                r.get("company_email") or r.get("email"),
                r.get("phone"),
                r.get("city"),
                r.get("state"),
                r.get("state_code"),
                r.get("zip_code"),
                r.get("country", "United States"),
                r.get("industry"),
                r.get("naics_code"),
                r.get("ein"),
                r.get("cik"),
                source,
                r.get("company_quality_score", 80),
                json.dumps(r),
            ))

        full_name = r.get("full_name")
        work_email = r.get("email")
        title = r.get("title")

        if full_name or title or work_email:
            person_id = str(r.get("id") or f"{comp_id}_person")
            people_rows.append((
                person_id,
                str(comp_id),
                r.get("first_name"),
                r.get("last_name"),
                full_name or "Executive Officer",
                title,
                r.get("standardized_title") or title,
                r.get("seniority_level", "EXECUTIVE"),
                r.get("department", "MANAGEMENT"),
                work_email,
                r.get("city"),
                r.get("state"),
                r.get("state_code"),
                r.get("country", "United States"),
                r.get("email_status", "UNKNOWN"),
                r.get("email_confidence_score", 0),
                source,
                json.dumps(r),
            ))

    if company_rows:
        company_sql = """
            INSERT INTO staging_dataextraction.staging_companies (
                id, name, legal_name, website, domain, email, phone,
                city, state, state_code, zip_code, country,
                industry, naics_code, ein, cik, source,
                data_quality_score, raw_payload, updated_at
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                website = COALESCE(EXCLUDED.website, staging_companies.website),
                domain = COALESCE(EXCLUDED.domain, staging_companies.domain),
                email = COALESCE(EXCLUDED.email, staging_companies.email),
                phone = COALESCE(EXCLUDED.phone, staging_companies.phone),
                city = COALESCE(EXCLUDED.city, staging_companies.city),
                state = COALESCE(EXCLUDED.state, staging_companies.state),
                state_code = COALESCE(EXCLUDED.state_code, staging_companies.state_code),
                zip_code = COALESCE(EXCLUDED.zip_code, staging_companies.zip_code),
                industry = COALESCE(EXCLUDED.industry, staging_companies.industry),
                ein = COALESCE(EXCLUDED.ein, staging_companies.ein),
                cik = COALESCE(EXCLUDED.cik, staging_companies.cik),
                data_quality_score = GREATEST(COALESCE(EXCLUDED.data_quality_score, 0), COALESCE(staging_companies.data_quality_score, 0)),
                raw_payload = COALESCE(staging_companies.raw_payload, '{}'::jsonb) || EXCLUDED.raw_payload,
                updated_at = NOW();
        """
        psycopg2.extras.execute_values(
            cur,
            company_sql,
            company_rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())",
            page_size=len(company_rows),
        )

    if people_rows:
        people_sql = """
            INSERT INTO staging_dataextraction.staging_people (
                id, company_id, first_name, last_name, full_name,
                title, standardized_title, seniority_level, department,
                work_email, city, state, state_code, country,
                email_status, email_confidence_score, source,
                raw_payload, updated_at
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                title = EXCLUDED.title,
                work_email = COALESCE(EXCLUDED.work_email, staging_people.work_email),
                email_status = EXCLUDED.email_status,
                email_confidence_score = EXCLUDED.email_confidence_score,
                raw_payload = EXCLUDED.raw_payload,
                updated_at = NOW();
        """
        psycopg2.extras.execute_values(
            cur,
            people_sql,
            people_rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())",
            page_size=len(people_rows),
        )

    return len(company_rows), len(people_rows)


def bulk_upsert_working_records(
    cur,
    organizations: Optional[List[Dict[str, Any]]] = None,
    emails: Optional[List[Dict[str, Any]]] = None,
    persons: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[int, int, int]:
    """
    High-throughput bulk upsert into the Pre-Master Working Layer:
      - staging_dataextraction.working_organizations
      - staging_dataextraction.working_emails
      - staging_dataextraction.working_persons
    Uses psycopg2.extras.execute_values for enterprise throughput (> 5,000 rec/s).

    Returns:
        Tuple[int, int, int]: (orgs_upserted, emails_upserted, persons_upserted)
    """
    organizations = organizations or []
    emails = emails or []
    persons = persons or []

    org_rows = []
    for org in organizations:
        org_id = str(org.get("org_id") or org.get("id"))
        legal_name = str(org.get("legal_name") or org.get("company_name") or org.get("name") or "Enterprise Entity")
        display_name = org.get("display_name") or legal_name
        domain = org.get("primary_domain") or org.get("domain")
        website = org.get("website") or (f"https://{domain}" if domain else None)

        phones_json = json.dumps(org.get("phones") if isinstance(org.get("phones"), list) else [org.get("phone")] if org.get("phone") else [])
        locations_json = json.dumps(org.get("locations") if isinstance(org.get("locations"), list) else [{
            "city": org.get("city"), "state": org.get("state"), "country": org.get("country", "United States")
        }] if org.get("city") else [])
        lineage_json = json.dumps(org.get("lineage_ids") if isinstance(org.get("lineage_ids"), list) else [org.get("source", "HARVESTER")])

        org_rows.append((
            org_id,
            legal_name,
            display_name,
            domain,
            website,
            org.get("statutory_tax_id") or org.get("ein"),
            org.get("sec_cik") or org.get("cik"),
            org.get("gleif_lei"),
            org.get("jurisdiction", "US"),
            org.get("industry"),
            org.get("naics_code"),
            org.get("sic_code"),
            org.get("employee_count_min"),
            org.get("employee_count_max"),
            org.get("annual_revenue_usd"),
            phones_json,
            locations_json,
            org.get("canonical_cluster_id") or org_id,
            float(org.get("identity_confidence", 1.0)),
            org.get("email_verification_status", "PENDING"),
            org.get("executive_enrichment_status", "PENDING"),
            int(org.get("data_quality_score", 0)),
            float(org.get("trust_score", 0.0)),
            org.get("governance_status", "IN_ENRICHMENT"),
            org.get("contributing_sources", ["REGISTRY"]),
            lineage_json,
        ))

    if org_rows:
        org_sql = """
            INSERT INTO staging_dataextraction.working_organizations (
                org_id, legal_name, display_name, primary_domain, website,
                statutory_tax_id, sec_cik, gleif_lei, jurisdiction, industry,
                naics_code, sic_code, employee_count_min, employee_count_max, annual_revenue_usd,
                phones, locations, canonical_cluster_id, identity_confidence,
                email_verification_status, executive_enrichment_status,
                data_quality_score, trust_score, governance_status,
                contributing_sources, lineage_ids, updated_at
            ) VALUES %s
            ON CONFLICT (org_id) DO UPDATE SET
                legal_name = EXCLUDED.legal_name,
                display_name = EXCLUDED.display_name,
                primary_domain = COALESCE(EXCLUDED.primary_domain, working_organizations.primary_domain),
                statutory_tax_id = COALESCE(EXCLUDED.statutory_tax_id, working_organizations.statutory_tax_id),
                sec_cik = COALESCE(EXCLUDED.sec_cik, working_organizations.sec_cik),
                gleif_lei = COALESCE(EXCLUDED.gleif_lei, working_organizations.gleif_lei),
                industry = COALESCE(EXCLUDED.industry, working_organizations.industry),
                employee_count_min = COALESCE(EXCLUDED.employee_count_min, working_organizations.employee_count_min),
                employee_count_max = COALESCE(EXCLUDED.employee_count_max, working_organizations.employee_count_max),
                annual_revenue_usd = COALESCE(EXCLUDED.annual_revenue_usd, working_organizations.annual_revenue_usd),
                phones = EXCLUDED.phones,
                locations = EXCLUDED.locations,
                canonical_cluster_id = COALESCE(EXCLUDED.canonical_cluster_id, working_organizations.canonical_cluster_id),
                identity_confidence = EXCLUDED.identity_confidence,
                email_verification_status = EXCLUDED.email_verification_status,
                executive_enrichment_status = EXCLUDED.executive_enrichment_status,
                data_quality_score = GREATEST(EXCLUDED.data_quality_score, working_organizations.data_quality_score),
                trust_score = GREATEST(EXCLUDED.trust_score, working_organizations.trust_score),
                governance_status = EXCLUDED.governance_status,
                updated_at = NOW();
        """
        psycopg2.extras.execute_values(
            cur,
            org_sql,
            org_rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())",
            page_size=len(org_rows),
        )

    email_rows = []
    for em in emails:
        org_id = str(em.get("org_id"))
        email_addr = str(em.get("email_address") or em.get("email")).strip().lower()
        parts = email_addr.split("@")
        mailbox = parts[0] if len(parts) > 0 else "info"
        domain = parts[1] if len(parts) > 1 else (em.get("email_domain") or "example.com")

        email_rows.append((
            org_id,
            email_addr,
            mailbox,
            domain,
            em.get("deliverability_status", "DELIVERABLE"),
            int(em.get("confidence_score", 90)),
            bool(em.get("is_catchall", False)),
            em.get("mx_record", f"mail.{domain}"),
            em.get("discovery_source", "BENCHMARK_STREAM"),
        ))

    if email_rows:
        email_sql = """
            INSERT INTO staging_dataextraction.working_emails (
                org_id, email_address, mailbox_user, email_domain,
                deliverability_status, confidence_score, is_catchall, mx_record,
                discovery_source, created_at
            ) VALUES %s
            ON CONFLICT (org_id, email_address) DO UPDATE SET
                deliverability_status = EXCLUDED.deliverability_status,
                confidence_score = EXCLUDED.confidence_score,
                is_catchall = EXCLUDED.is_catchall,
                mx_record = EXCLUDED.mx_record;
        """
        psycopg2.extras.execute_values(
            cur,
            email_sql,
            email_rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            page_size=len(email_rows),
        )

    person_rows = []
    for p in persons:
        person_id = str(p.get("person_id") or p.get("id"))
        org_id = str(p.get("org_id") or p.get("company_id"))
        full_name = str(p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or "Executive Officer")
        first_name = p.get("first_name")
        last_name = p.get("last_name")

        person_rows.append((
            person_id,
            org_id,
            full_name,
            first_name,
            last_name,
            p.get("title", "Chief Executive Officer"),
            p.get("seniority", "EXECUTIVE"),
            p.get("department", "MANAGEMENT"),
            p.get("primary_email") or p.get("email"),
            p.get("primary_phone") or p.get("phone"),
            p.get("linkedin_url"),
            float(p.get("confidence_score", 0.95)),
            p.get("governance_status", "IN_ENRICHMENT"),
        ))

    if person_rows:
        person_sql = """
            INSERT INTO staging_dataextraction.working_persons (
                person_id, org_id, full_name, first_name, last_name,
                title, seniority, department, primary_email, primary_phone,
                linkedin_url, confidence_score, governance_status, created_at
            ) VALUES %s
            ON CONFLICT (person_id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                title = EXCLUDED.title,
                seniority = EXCLUDED.seniority,
                department = EXCLUDED.department,
                primary_email = COALESCE(EXCLUDED.primary_email, working_persons.primary_email),
                primary_phone = COALESCE(EXCLUDED.primary_phone, working_persons.primary_phone),
                linkedin_url = COALESCE(EXCLUDED.linkedin_url, working_persons.linkedin_url),
                confidence_score = EXCLUDED.confidence_score,
                governance_status = EXCLUDED.governance_status;
        """
        psycopg2.extras.execute_values(
            cur,
            person_sql,
            person_rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            page_size=len(person_rows),
        )

    return len(org_rows), len(email_rows), len(person_rows)


def upsert_master_locations(cur, locations: List[Dict[str, Any]]) -> int:
    """
    Idempotently persists physical geospatial locations into `master_dataextraction.locations`
    using a deterministic UUIDv5 `location_id` derived from canonical source identifiers.
    Prevents duplicate rows across google_place_id, osm_place_id, and coordinates.
    """
    if not locations:
        return 0

    rows = []
    seen_ids = set()
    seen_gpids = set()
    seen_opids = set()
    for loc in locations:
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except (TypeError, ValueError):
            continue

        google_pid = loc.get("google_place_id")
        osm_pid_raw = loc.get("osm_place_id")
        osm_pid: Optional[int] = None
        if osm_pid_raw is not None:
            try:
                osm_pid = int(osm_pid_raw)
            except (TypeError, ValueError):
                osm_pid = None

        gpid_clean = str(google_pid)[:255] if google_pid else None
        if gpid_clean and gpid_clean in seen_gpids:
            continue
        if osm_pid is not None and osm_pid in seen_opids:
            continue

        # Canonical identity ordering guarantees the same place always resolves to one location_id
        source_key = (
            (f"gmaps:{gpid_clean}" if gpid_clean else "")
            or (f"osm:{osm_pid}" if osm_pid is not None else "")
            or str(loc.get("location_key") or "")
            or f"coord:{lat_f:.6f},{lon_f:.6f}:{(loc.get('name') or '').strip().lower()}"
        )
        loc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, source_key))
        if loc_id in seen_ids:
            continue
        seen_ids.add(loc_id)
        if gpid_clean:
            seen_gpids.add(gpid_clean)
        if osm_pid is not None:
            seen_opids.add(osm_pid)

        city = loc.get("city")
        state = loc.get("state")
        state_code = loc.get("state_code")
        postal_code = loc.get("postal_code") or loc.get("zip_code")
        country_name = loc.get("country") or "United States"
        cc_raw = str(loc.get("country_code") or ("MX" if "mexico" in str(country_name).lower() else "US")).strip().upper()
        country_code = cc_raw[:2] if len(cc_raw) >= 2 else "US"

        fallback_addr = ", ".join(
            str(p) for p in [loc.get("name"), city, state_code or state, postal_code, country_code] if p
        ) or f"{lat_f:.6f}, {lon_f:.6f}"
        raw_address = str(loc.get("raw_address") or loc.get("address") or fallback_addr)
        formatted_address = str(loc.get("formatted_address") or raw_address)

        rows.append((
            loc_id,
            raw_address,
            formatted_address,
            loc.get("street_number"),
            loc.get("route") or loc.get("street_address"),
            city,
            state,
            loc.get("county"),
            str(postal_code)[:20] if postal_code else None,
            country_code,
            lat_f,
            lon_f,
            loc.get("geocoding_precision") or "ROOFTOP",
            osm_pid,
            gpid_clean,
            city,
            state,
            str(state_code)[:10] if state_code else None,
            country_name,
        ))

    if not rows:
        return 0

    sql = """
        INSERT INTO master_dataextraction.locations (
            location_id, raw_address, formatted_address, street_number, route,
            locality, administrative_area_level_1, administrative_area_level_2,
            postal_code, country_code, latitude, longitude, geocoding_precision,
            osm_place_id, google_place_id, city, state, state_code, country
        ) VALUES %s
        ON CONFLICT (location_id) DO UPDATE SET
            formatted_address = COALESCE(EXCLUDED.formatted_address, master_dataextraction.locations.formatted_address),
            postal_code = COALESCE(EXCLUDED.postal_code, master_dataextraction.locations.postal_code),
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            geocoding_precision = COALESCE(EXCLUDED.geocoding_precision, master_dataextraction.locations.geocoding_precision),
            city = COALESCE(EXCLUDED.city, master_dataextraction.locations.city),
            state = COALESCE(EXCLUDED.state, master_dataextraction.locations.state),
            state_code = COALESCE(EXCLUDED.state_code, master_dataextraction.locations.state_code);
    """
    psycopg2.extras.execute_values(
        cur,
        sql,
        rows,
        template="(%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        page_size=min(250, len(rows)),
    )
    return len(rows)


def link_organization_locations(
    cur,
    company_location_pairs: List[tuple],
    source_system: str = "GOOGLE_MAPS",
) -> int:
    """
    Idempotently links `staging_companies.id` records to deterministic `location_id` rows
    in `master_dataextraction.organization_locations`.
    `company_location_pairs`: sequence of `(source_company_id, location_key)`.
    """
    if not company_location_pairs or not hasattr(cur, "mogrify"):
        return 0

    seen_pairs = set()
    rows = []
    for company_id, loc_key in company_location_pairs:
        if not company_id or not loc_key:
            continue
        loc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(loc_key)))
        pair_key = (str(company_id), loc_id)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        rows.append((str(company_id), loc_id, source_system))

    if not rows:
        return 0

    sql = """
        INSERT INTO master_dataextraction.organization_locations (
            source_company_id, location_id, source_system, is_primary, confidence
        ) VALUES %s
        ON CONFLICT (source_company_id, location_id) DO UPDATE SET
            updated_at = NOW();
    """
    psycopg2.extras.execute_values(
        cur,
        sql,
        rows,
        template="(%s, %s::uuid, %s, TRUE, 1.0)",
        page_size=min(250, len(rows)),
    )
    return len(rows)


