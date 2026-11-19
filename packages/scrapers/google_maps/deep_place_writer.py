"""
PostgreSQL persistence for deep place data (migration 016).

Every statement is parameterized and upserts on the table's natural key, so running
the same extraction twice never creates duplicate rows.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional, Set

from psycopg2.extras import execute_values

from packages.scrapers.google_maps.deep_place import PlaceBundle

logger = logging.getLogger("dataextraction.gmaps.deep_place_writer")

SOURCE = "GOOGLE_MAPS"


class Suppressor:
    """GDPR/CCPA suppression lookup against kg_audit.suppression_lists (SHA-256 of lowercase value)."""

    def __init__(self, hashes: Optional[Set[str]] = None):
        self._hashes: Set[str] = hashes or set()

    @classmethod
    def load(cls, conn: Any) -> "Suppressor":
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT hashed_identifier FROM kg_audit.suppression_lists WHERE is_active")
                hashes = {str(r[0]).strip() for r in cur.fetchall()}
            return cls(hashes)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Suppression list unavailable (%s); continuing with an empty list", type(exc).__name__)
            return cls(set())

    def __call__(self, identifier: Optional[str]) -> bool:
        if not identifier or not self._hashes:
            return False
        h = hashlib.sha256(identifier.strip().lower().encode("utf-8")).hexdigest()
        return h in self._hashes


def _j(value: Any) -> str:
    return json.dumps(value, default=str)


def save_bundle(conn: Any, bundle: PlaceBundle, stub: Dict[str, Any], run_id: str,
                source: str = SOURCE) -> Dict[str, int]:
    """Upsert one place and everything collected for it. Caller commits."""
    d = bundle.details or {}
    pid = bundle.place_id
    src_url = f"https://www.google.com/maps/place/?q=place_id:{stub.get('place_id') or pid}"
    counts = {"details": 0, "services": 0, "reviews": 0, "contacts": 0, "people": 0}

    photos = [p.get("photo_url") for p in d.get("photos", []) if isinstance(p, dict) and p.get("photo_url")]
    categories = [c for c in {stub.get("category"), d.get("category")} if c]

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging_dataextraction.place_details
                (place_id, ftid, company_id, name, categories, address, street_address, city, region,
                 postal_code, country_code, latitude, longitude, phone, website, rating, review_count,
                 timezone, claimed_status, hours, attributes, photo_urls, status, source, source_url,
                 run_id, scraped_at)
            VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,
                    %s::jsonb,%s,%s,%s,%s,NOW())
            ON CONFLICT (place_id) DO UPDATE SET
                ftid = COALESCE(EXCLUDED.ftid, place_details.ftid),
                company_id = COALESCE(EXCLUDED.company_id, place_details.company_id),
                name = COALESCE(EXCLUDED.name, place_details.name),
                categories = CASE WHEN EXCLUDED.categories = '[]'::jsonb THEN place_details.categories
                                  ELSE EXCLUDED.categories END,
                address = COALESCE(EXCLUDED.address, place_details.address),
                street_address = COALESCE(EXCLUDED.street_address, place_details.street_address),
                city = COALESCE(EXCLUDED.city, place_details.city),
                region = COALESCE(EXCLUDED.region, place_details.region),
                postal_code = COALESCE(EXCLUDED.postal_code, place_details.postal_code),
                country_code = COALESCE(EXCLUDED.country_code, place_details.country_code),
                latitude = COALESCE(EXCLUDED.latitude, place_details.latitude),
                longitude = COALESCE(EXCLUDED.longitude, place_details.longitude),
                phone = COALESCE(EXCLUDED.phone, place_details.phone),
                website = COALESCE(EXCLUDED.website, place_details.website),
                rating = COALESCE(EXCLUDED.rating, place_details.rating),
                review_count = COALESCE(EXCLUDED.review_count, place_details.review_count),
                timezone = COALESCE(EXCLUDED.timezone, place_details.timezone),
                claimed_status = COALESCE(EXCLUDED.claimed_status, place_details.claimed_status),
                hours = CASE WHEN EXCLUDED.hours = '[]'::jsonb THEN place_details.hours ELSE EXCLUDED.hours END,
                attributes = CASE WHEN EXCLUDED.attributes = '[]'::jsonb THEN place_details.attributes
                                  ELSE EXCLUDED.attributes END,
                photo_urls = CASE WHEN EXCLUDED.photo_urls = '[]'::jsonb THEN place_details.photo_urls
                                  ELSE EXCLUDED.photo_urls END,
                status = EXCLUDED.status,
                source_url = EXCLUDED.source_url,
                run_id = EXCLUDED.run_id,
                scraped_at = NOW()
            """,
            (
                pid, stub.get("ftid"), stub.get("company_id") or f"gmaps_{pid}",
                d.get("name") or stub.get("name"), _j(categories),
                d.get("address") or stub.get("address"), d.get("street_address") or stub.get("street_address"),
                d.get("city") or stub.get("city"), d.get("region") or stub.get("region") or stub.get("state"),
                d.get("postal_code") or stub.get("postal_code"),
                d.get("country_code") or stub.get("country_code"),
                d.get("latitude") or stub.get("latitude"), d.get("longitude") or stub.get("longitude"),
                d.get("phone") or stub.get("phone"), d.get("website") or stub.get("website"),
                d.get("rating") if d.get("rating") is not None else stub.get("rating"),
                d.get("review_count") if d.get("review_count") is not None else stub.get("review_count"),
                d.get("timezone"), d.get("claimed_status"),
                _j(d.get("hours", [])), _j(d.get("attributes", [])), _j(photos),
                bundle.status, source, src_url, run_id,
            ),
        )
        counts["details"] = 1

        if bundle.services:
            execute_values(
                cur,
                """
                INSERT INTO staging_dataextraction.place_services
                    (place_id, group_name, service_name, is_enabled, display_value, origin, source,
                     source_url, run_id)
                VALUES %s
                ON CONFLICT (place_id, group_name, service_name) DO UPDATE SET
                    is_enabled = EXCLUDED.is_enabled,
                    display_value = COALESCE(EXCLUDED.display_value, place_services.display_value),
                    run_id = EXCLUDED.run_id, scraped_at = NOW()
                """,
                [(s["place_id"], s.get("group_name") or "", s["service_name"], s.get("is_enabled", True),
                  s.get("display_value"), s.get("origin", "attribute"), source, s.get("source_url"), run_id)
                 for s in bundle.services],
            )
            counts["services"] = len(bundle.services)

        if bundle.reviews:
            execute_values(
                cur,
                """
                INSERT INTO staging_dataextraction.place_reviews
                    (place_id, review_id, reviewer_name, reviewer_name_hash, reviewer_id, rating,
                     review_text, language, published_at, relative_date, owner_response_text,
                     owner_response_date, reaction_count, photo_urls, sentiment, topics, source,
                     source_url, run_id)
                VALUES %s
                ON CONFLICT (place_id, review_id) DO UPDATE SET
                    reviewer_name = EXCLUDED.reviewer_name,
                    reviewer_name_hash = EXCLUDED.reviewer_name_hash,
                    reviewer_id = EXCLUDED.reviewer_id,
                    rating = EXCLUDED.rating,
                    review_text = COALESCE(EXCLUDED.review_text, place_reviews.review_text),
                    published_at = COALESCE(EXCLUDED.published_at, place_reviews.published_at),
                    relative_date = EXCLUDED.relative_date,
                    owner_response_text = COALESCE(EXCLUDED.owner_response_text, place_reviews.owner_response_text),
                    owner_response_date = COALESCE(EXCLUDED.owner_response_date, place_reviews.owner_response_date),
                    reaction_count = EXCLUDED.reaction_count,
                    photo_urls = EXCLUDED.photo_urls,
                    sentiment = COALESCE(EXCLUDED.sentiment, place_reviews.sentiment),
                    topics = CASE WHEN EXCLUDED.topics = '[]'::jsonb THEN place_reviews.topics
                                  ELSE EXCLUDED.topics END,
                    run_id = EXCLUDED.run_id, scraped_at = NOW()
                """,
                [(r["place_id"], r["review_id"], r.get("reviewer_name"), r.get("reviewer_name_hash"),
                  r.get("reviewer_id"), r.get("rating"), r.get("review_text"), r.get("language"),
                  r.get("published_at"), r.get("relative_date"), r.get("owner_response_text"),
                  r.get("owner_response_date"), r.get("reaction_count") or 0, r.get("photo_urls") or "[]",
                  r.get("sentiment"), _j(r.get("topics") or []), source, r.get("source_url"), run_id)
                 for r in bundle.reviews],
                template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,%s)",
            )
            counts["reviews"] = len(bundle.reviews)

        if bundle.contacts:
            execute_values(
                cur,
                """
                INSERT INTO staging_dataextraction.place_contacts
                    (place_id, contact_type, value, label, extraction_method, source, source_url, run_id)
                VALUES %s
                ON CONFLICT (place_id, contact_type, value) DO UPDATE SET
                    label = COALESCE(EXCLUDED.label, place_contacts.label),
                    run_id = EXCLUDED.run_id, scraped_at = NOW()
                """,
                [(c["place_id"], c["contact_type"], c["value"], c.get("label"),
                  c.get("extraction_method", "regex"), source, c.get("source_url"), run_id)
                 for c in bundle.contacts],
            )
            counts["contacts"] = len(bundle.contacts)

        if bundle.people:
            execute_values(
                cur,
                """
                INSERT INTO staging_dataextraction.place_people
                    (place_id, full_name, role_title, email, phone, profile_url, extraction_method,
                     source, source_url, run_id)
                VALUES %s
                ON CONFLICT (place_id, full_name, role_title) DO UPDATE SET
                    email = COALESCE(EXCLUDED.email, place_people.email),
                    phone = COALESCE(EXCLUDED.phone, place_people.phone),
                    run_id = EXCLUDED.run_id, scraped_at = NOW()
                """,
                [(p["place_id"], p["full_name"], p.get("role_title") or "", p.get("email"), p.get("phone"),
                  p.get("profile_url"), p.get("extraction_method", "regex"), source, p.get("source_url"), run_id)
                 for p in bundle.people],
            )
            counts["people"] = len(bundle.people)
    return counts


def start_run(conn: Any, run_id: str, requested: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO staging_dataextraction.place_extraction_runs (run_id, status, requested)
            VALUES (%s, 'running', %s::jsonb)
            ON CONFLICT (run_id) DO UPDATE SET status = 'running', requested = EXCLUDED.requested,
                started_at = NOW(), finished_at = NULL, error = NULL
            """,
            (run_id, _j(requested)),
        )


def finish_run(conn: Any, run_id: str, status: str, places_done: int, reviews_saved: int,
               error: Optional[str] = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE staging_dataextraction.place_extraction_runs
            SET status = %s, places_done = %s, reviews_saved = %s, error = %s, finished_at = NOW()
            WHERE run_id = %s
            """,
            (status, places_done, reviews_saved, error, run_id),
        )
