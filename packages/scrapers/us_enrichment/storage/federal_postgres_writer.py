"""
OneExtraction — Federal & Open Data PostgreSQL Persistence Writer
==================================================================
Batch writer mapping federal registry records (SAM.gov, Census CBP, openFDA,
BLS, BEA, EIA, USGS, Data.gov) directly into the OneExtraction PostgreSQL
`businesses` and `people` tables.

Enterprise Standards:
  - Parameterized SQL (immune to SQL injection)
  - ON CONFLICT (company_id) DO UPDATE idempotency
  - Preserves existing database table schemas without modifications
  - Full transaction isolation with rollback on exception
"""

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("oneextraction.federal_postgres_writer")


def _extract_domain(url: Optional[str]) -> Optional[str]:
    """Extracts registered domain from URL."""
    if not url:
        return None
    url = url.strip()
    if not url or url.lower() in ("null", "none", "n/a"):
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc.split(":")[0] if netloc else None
    except Exception:
        return None


def upsert_federal_businesses(
    conn: Any,
    records: List[Dict[str, Any]],
    default_source: str = "federal_open_data",
) -> Dict[str, int]:
    """
    Batch upserts federal/open-data establishments and vendors into `businesses`.

    Args:
        conn: Active psycopg2 connection
        records: List of business/vendor dictionaries
        default_source: Fallback source identifier

    Returns:
        {"total": int, "inserted_or_updated": int, "failed": int}
    """
    if not records:
        return {"total": 0, "inserted_or_updated": 0, "failed": 0}

    upsert_sql = """
        INSERT INTO businesses (
            company_id,
            name,
            legal_name,
            website_url,
            domain,
            phone,
            email,
            city,
            state,
            state_code,
            zip_code,
            country,
            latitude,
            longitude,
            industry,
            sub_industry,
            naics_code,
            ein,
            cage_code,
            uei,
            employee_count_band,
            source,
            data_quality_score,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (company_id) DO UPDATE SET
            name = EXCLUDED.name,
            legal_name = COALESCE(EXCLUDED.legal_name, businesses.legal_name),
            website_url = COALESCE(EXCLUDED.website_url, businesses.website_url),
            domain = COALESCE(EXCLUDED.domain, businesses.domain),
            phone = COALESCE(EXCLUDED.phone, businesses.phone),
            email = COALESCE(EXCLUDED.email, businesses.email),
            city = COALESCE(EXCLUDED.city, businesses.city),
            state = COALESCE(EXCLUDED.state, businesses.state),
            state_code = COALESCE(EXCLUDED.state_code, businesses.state_code),
            zip_code = COALESCE(EXCLUDED.zip_code, businesses.zip_code),
            country = COALESCE(EXCLUDED.country, businesses.country),
            latitude = COALESCE(EXCLUDED.latitude, businesses.latitude),
            longitude = COALESCE(EXCLUDED.longitude, businesses.longitude),
            industry = COALESCE(EXCLUDED.industry, businesses.industry),
            sub_industry = COALESCE(EXCLUDED.sub_industry, businesses.sub_industry),
            naics_code = COALESCE(EXCLUDED.naics_code, businesses.naics_code),
            ein = COALESCE(EXCLUDED.ein, businesses.ein),
            cage_code = COALESCE(EXCLUDED.cage_code, businesses.cage_code),
            uei = COALESCE(EXCLUDED.uei, businesses.uei),
            employee_count_band = COALESCE(EXCLUDED.employee_count_band, businesses.employee_count_band),
            source = EXCLUDED.source,
            data_quality_score = GREATEST(EXCLUDED.data_quality_score, businesses.data_quality_score),
            updated_at = now();
    """

    inserted = 0
    failed = 0
    cur = conn.cursor()

    try:
        for r in records:
            company_id = r.get("company_id") or r.get("uei") or r.get("id")
            if not company_id:
                failed += 1
                continue

            name = r.get("name") or r.get("legal_name") or "Unnamed Entity"
            website = r.get("website_url") or r.get("website")
            domain = _extract_domain(website)
            state = r.get("state") or r.get("state_name")
            state_code = r.get("state_code") or (state[:2].upper() if state and len(state) == 2 else None)
            quality_score = int(r.get("data_quality_score") or 60)

            try:
                cur.execute(
                    upsert_sql,
                    (
                        str(company_id),
                        name,
                        r.get("legal_name"),
                        website,
                        domain,
                        r.get("phone"),
                        r.get("email"),
                        r.get("city"),
                        state,
                        state_code,
                        r.get("zip_code") or r.get("postal_code"),
                        r.get("country") or "United States",
                        r.get("latitude"),
                        r.get("longitude"),
                        r.get("industry"),
                        r.get("sub_industry"),
                        r.get("naics_code"),
                        r.get("ein"),
                        r.get("cage_code"),
                        r.get("uei"),
                        r.get("employee_count_band"),
                        r.get("source") or default_source,
                        quality_score,
                    ),
                )
                inserted += 1
            except Exception as row_err:
                logger.debug("Row upsert skipped for %s: %s", company_id, row_err)
                failed += 1

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("Transaction error in upsert_federal_businesses: %s", exc)
        raise
    finally:
        cur.close()

    logger.info("Persisted %d federal businesses to PostgreSQL (failed=%d)", inserted, failed)
    return {"total": len(records), "inserted_or_updated": inserted, "failed": failed}


def upsert_federal_people(
    conn: Any,
    contacts: List[Dict[str, Any]],
    default_source: str = "federal_open_data",
) -> Dict[str, int]:
    """
    Batch upserts federal agency / vendor Points of Contact (POCs) into `people`.

    Args:
        conn: Active psycopg2 connection
        contacts: List of person dictionaries with company_id and full_name
        default_source: Source tag
    """
    if not contacts:
        return {"total": 0, "inserted": 0, "failed": 0}

    upsert_sql = """
        INSERT INTO people (
            person_id,
            company_id,
            first_name,
            last_name,
            full_name,
            title,
            standardized_title,
            work_email,
            direct_phone,
            source,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (person_id) DO UPDATE SET
            company_id = EXCLUDED.company_id,
            full_name = EXCLUDED.full_name,
            title = COALESCE(EXCLUDED.title, people.title),
            work_email = COALESCE(EXCLUDED.work_email, people.work_email),
            direct_phone = COALESCE(EXCLUDED.direct_phone, people.direct_phone),
            updated_at = now();
    """

    inserted = 0
    failed = 0
    cur = conn.cursor()

    try:
        for c in contacts:
            company_id = c.get("company_id")
            full_name = c.get("full_name") or c.get("name")
            if not company_id or not full_name:
                failed += 1
                continue

            person_id = c.get("person_id") or f"{company_id}_{full_name.lower().replace(' ', '_')[:32]}"
            parts = full_name.split()
            first_name = c.get("first_name") or (parts[0] if parts else "")
            last_name = c.get("last_name") or (" ".join(parts[1:]) if len(parts) > 1 else "")
            title = c.get("title") or "Point of Contact"

            try:
                cur.execute(
                    upsert_sql,
                    (
                        person_id,
                        company_id,
                        first_name,
                        last_name,
                        full_name,
                        title,
                        title,
                        c.get("work_email") or c.get("email"),
                        c.get("direct_phone") or c.get("phone"),
                        c.get("source") or default_source,
                    ),
                )
                inserted += 1
            except Exception as row_err:
                logger.debug("Row upsert skipped for person %s: %s", person_id, row_err)
                failed += 1

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("Transaction error in upsert_federal_people: %s", exc)
        raise
    finally:
        cur.close()

    logger.info("Persisted %d federal personnel to PostgreSQL (failed=%d)", inserted, failed)
    return {"total": len(contacts), "inserted": inserted, "failed": failed}

