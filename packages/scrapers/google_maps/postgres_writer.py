"""
OneExtraction — Google Maps PostgreSQL Persistence Writer
===========================================================
Batch writer mapping scraped Google Maps places and enriched contacts
directly into the OneExtraction enterprise PostgreSQL schema (businesses & people).

Enterprise standards:
  - Zero SQLite dependency for main storage
  - Fully parameterized SQL (no SQL injection)
  - ON CONFLICT (company_id) DO UPDATE idempotency
  - Robust error handling and transaction rollback
  - Automatic domain normalization and quality scoring
"""

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("oneextraction.gmaps.postgres_writer")


def extract_domain_from_url(url: Optional[str]) -> Optional[str]:
    """Extracts clean registered domain from a website URL."""
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


def calculate_gmaps_quality_score(place: Dict[str, Any]) -> int:
    """Calculates data completeness score (0-100) for a scraped place."""
    score = 0
    if place.get("name"):
        score += 20
    if place.get("latitude") and place.get("longitude"):
        score += 20
    if place.get("phone") or place.get("phone_e164"):
        score += 15
    if place.get("website"):
        score += 15
    if place.get("address") or place.get("street_address"):
        score += 10
    if place.get("city") and (place.get("region") or place.get("state_code")):
        score += 10
    if place.get("category"):
        score += 10
    return min(100, score)


def upsert_gmaps_places_to_postgres(
    conn: Any,
    places: List[Dict[str, Any]],
    source_label: str = "google_maps",
) -> Dict[str, int]:
    """
    Batch upserts canonical Google Maps places into the PostgreSQL `businesses` table.

    Args:
        conn: Active psycopg2 PostgreSQL connection
        places: List of canonical place dictionaries
        source_label: Source identifier tag (default: 'google_maps')

    Returns:
        {"total": int, "inserted_or_updated": int, "failed": int}
    """
    if not places:
        return {"total": 0, "inserted_or_updated": 0, "failed": 0}

    upsert_sql = """
        INSERT INTO businesses (
            company_id,
            name,
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
            source,
            extracted_emails,
            executives_json,
            data_quality_score,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
        )
        ON CONFLICT (company_id) DO UPDATE SET
            name = EXCLUDED.name,
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
            source = EXCLUDED.source,
            extracted_emails = CASE
                WHEN EXCLUDED.extracted_emails IS NOT NULL AND array_length(EXCLUDED.extracted_emails, 1) > 0
                THEN EXCLUDED.extracted_emails
                ELSE businesses.extracted_emails
            END,
            executives_json = COALESCE(EXCLUDED.executives_json, businesses.executives_json),
            data_quality_score = GREATEST(EXCLUDED.data_quality_score, businesses.data_quality_score),
            updated_at = now();
    """

    inserted = 0
    failed = 0

    cur = conn.cursor()
    try:
        for p in places:
            cid = p.get("cid")
            if not cid:
                # If no CID, fallback to place_id or synthetic hash
                cid = p.get("place_id") or p.get("id")
            if not cid:
                failed += 1
                continue

            company_id = f"gmaps_{cid}" if not str(cid).startswith("gmaps_") else str(cid)
            name = p.get("name") or "Unknown Business"
            website = p.get("website")
            domain = extract_domain_from_url(website)
            phone = p.get("phone_e164") or p.get("phone")

            # Emails and contacts
            raw_emails = p.get("emails") or []
            if isinstance(raw_emails, str):
                raw_emails = [e.strip() for e in raw_emails.split(",") if e.strip()]
            email_primary = p.get("email") or (raw_emails[0] if raw_emails else None)

            # Location fields
            city = p.get("city")
            state = p.get("region")
            state_code = p.get("country_code") or (state[:2].upper() if state and len(state) == 2 else None)
            zip_code = p.get("postal_code")
            country = p.get("country") or "United States"

            # Coordinates
            lat = p.get("latitude")
            lng = p.get("longitude")

            # Classification
            industry = p.get("category")
            sub_industry = p.get("primary_vertical")

            # Executives / People
            contacts = p.get("contacts") or p.get("executives") or []
            executives_json = json.dumps(contacts) if contacts else None
            quality_score = calculate_gmaps_quality_score(p)

            try:
                cur.execute(
                    upsert_sql,
                    (
                        company_id,
                        name,
                        website,
                        domain,
                        phone,
                        email_primary,
                        city,
                        state,
                        state_code,
                        zip_code,
                        country,
                        lat,
                        lng,
                        industry,
                        sub_industry,
                        source_label,
                        raw_emails if raw_emails else None,
                        executives_json,
                        quality_score,
                    ),
                )
                inserted += 1
            except Exception as row_err:
                logger.debug("Failed to upsert place %s: %s", company_id, row_err)
                failed += 1

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("Transaction error upserting Google Maps batch: %s", exc)
        raise
    finally:
        cur.close()

    logger.info("Persisted %d Google Maps places to PostgreSQL (failed=%d)", inserted, failed)
    return {"total": len(places), "inserted_or_updated": inserted, "failed": failed}


def upsert_gmaps_people_to_postgres(
    conn: Any,
    people_records: List[Dict[str, Any]],
    source_label: str = "google_maps",
) -> Dict[str, int]:
    """
    Batch upserts extracted personnel / leadership contacts into `people`.

    Args:
        conn: Active psycopg2 connection
        people_records: List of person dictionaries with company_id
    """
    if not people_records:
        return {"total": 0, "inserted": 0, "failed": 0}

    upsert_person_sql = """
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
        for person in people_records:
            company_id = person.get("company_id")
            full_name = person.get("name") or person.get("full_name")
            if not company_id or not full_name:
                failed += 1
                continue

            person_id = person.get("person_id") or f"{company_id}_{full_name.lower().replace(' ', '_')}"
            first_name = person.get("first_name")
            last_name = person.get("last_name")
            if not first_name and full_name:
                parts = full_name.split()
                first_name = parts[0]
                last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

            title = person.get("title")
            work_email = person.get("email") or person.get("work_email")
            direct_phone = person.get("phone") or person.get("direct_phone")

            try:
                cur.execute(
                    upsert_person_sql,
                    (
                        person_id,
                        company_id,
                        first_name,
                        last_name,
                        full_name,
                        title,
                        title,  # standardized_title fallback
                        work_email,
                        direct_phone,
                        source_label,
                    ),
                )
                inserted += 1
            except Exception as row_err:
                logger.debug("Failed to upsert person %s: %s", person_id, row_err)
                failed += 1

        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.error("Transaction error upserting people batch: %s", exc)
        raise
    finally:
        cur.close()

    return {"total": len(people_records), "inserted": inserted, "failed": failed}

