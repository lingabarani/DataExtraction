"""
DataExtraction — Google Maps Service Extractor
==============================================
Dedicated service extraction and taxonomy classification engine for Google Maps places.
Maps raw place attributes and services to hierarchical categories and persists them into
`staging_dataextraction.place_services`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from packages.scrapers.google_maps.services.taxonomy import ServiceTaxonomyClassifier

logger = logging.getLogger("dataextraction.gmaps.services.extractor")


AMENITY_GROUPS = {
    "accessibility", "amenities", "payments", "atmosphere", "crowd",
    "parking", "planning", "recycling", "restroom", "seating"
}


class GoogleMapsServiceExtractor:
    def __init__(
        self,
        get_conn_fn: Callable[[], Any],
        release_conn_fn: Callable[[Any], None],
        classifier: Optional[ServiceTaxonomyClassifier] = None,
    ):
        self._get_conn = get_conn_fn
        self._release_conn = release_conn_fn
        self._classifier = classifier or ServiceTaxonomyClassifier()

    def extract_from_place_details(
        self,
        place_id: str,
        details: Dict[str, Any],
        run_id: str,
        source_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Converts Google place details attributes and service options into taxonomy-classified service rows.
        Distinguishes business services from ordinary place amenities (e.g. accessibility, payments).
        """
        attributes = details.get("attributes") or []
        rows: List[Dict[str, Any]] = []
        seen = set()

        for attr in attributes:
            name = (attr.get("attribute_name") or "").strip()
            group = (attr.get("group_name") or "").strip()
            if not name:
                continue

            key = (group.lower(), name.lower())
            if key in seen:
                continue
            seen.add(key)

            classified = self._classifier.classify_service(name, group)
            is_amenity = group.lower() in AMENITY_GROUPS
            origin = "amenity" if is_amenity else "service"

            rows.append({
                "place_id": place_id,
                "group_name": group,
                "service_name": name,
                "main_category": classified["main_category"],
                "subcategory": classified["subcategory"],
                "is_enabled": bool(attr.get("is_enabled", True)),
                "display_value": attr.get("display_value"),
                "origin": origin,
                "source": "GOOGLE_MAPS",
                "source_url": source_url or f"https://www.google.com/maps/place/?q=place_id:{place_id}",
                "tags": classified["tags"],
                "taxonomy_version": classified["taxonomy_version"],
                "run_id": run_id,
            })

        return rows

    def persist_services(self, rows: List[Dict[str, Any]]) -> int:
        """Upserts classified services into staging_dataextraction.place_services."""
        if not rows:
            return 0

        conn = self._get_conn()
        if not conn:
            return 0

        try:
            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                query = """
                INSERT INTO staging_dataextraction.place_services (
                    place_id, group_name, service_name, main_category, subcategory,
                    is_enabled, display_value, origin, source, source_url, tags,
                    taxonomy_version, run_id, scraped_at
                ) VALUES %s
                ON CONFLICT (place_id, group_name, service_name) DO UPDATE SET
                    main_category = COALESCE(EXCLUDED.main_category, staging_dataextraction.place_services.main_category),
                    subcategory = COALESCE(EXCLUDED.subcategory, staging_dataextraction.place_services.subcategory),
                    is_enabled = EXCLUDED.is_enabled,
                    display_value = COALESCE(EXCLUDED.display_value, staging_dataextraction.place_services.display_value),
                    tags = EXCLUDED.tags,
                    taxonomy_version = EXCLUDED.taxonomy_version,
                    scraped_at = NOW()
                """
                tuples = [
                    (
                        r["place_id"],
                        r["group_name"],
                        r["service_name"],
                        r.get("main_category"),
                        r.get("subcategory"),
                        r.get("is_enabled", True),
                        r.get("display_value"),
                        r.get("origin", "attribute"),
                        r.get("source", "GOOGLE_MAPS"),
                        r.get("source_url"),
                        json.dumps(r.get("tags") or []),
                        r.get("taxonomy_version"),
                        r.get("run_id"),
                        datetime.now(timezone.utc),
                    )
                    for r in rows
                ]
                execute_values(cur, query, tuples)
            conn.commit()
            return len(rows)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("Failed to persist place services: %s", exc)
            return 0
        finally:
            self._release_conn(conn)

    def classify_existing_place_services(self, limit: int = 500) -> int:
        """Classifies previously extracted place_services missing taxonomy categories."""
        conn = self._get_conn()
        if not conn:
            return 0

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, service_name, group_name
                    FROM staging_dataextraction.place_services
                    WHERE main_category IS NULL OR taxonomy_version IS NULL
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()

            if not rows:
                return 0

            updates = []
            for (pk_id, s_name, g_name) in rows:
                c = self._classifier.classify_service(s_name, g_name)
                updates.append((
                    pk_id,
                    c["main_category"],
                    c["subcategory"],
                    json.dumps(c["tags"]),
                    c["taxonomy_version"],
                ))

            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    """
                    UPDATE staging_dataextraction.place_services AS ps SET
                        main_category = val.main_category,
                        subcategory = val.subcategory,
                        tags = val.tags::jsonb,
                        taxonomy_version = val.taxonomy_version
                    FROM (VALUES %s) AS val(id, main_category, subcategory, tags, taxonomy_version)
                    WHERE ps.id = val.id
                    """,
                    updates,
                )
            conn.commit()
            return len(updates)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("Failed classifying existing place services: %s", exc)
            return 0
        finally:
            self._release_conn(conn)
