"""
DataExtraction - Enterprise PostgreSQL Google Maps Scraper Storage Adapter
==========================================================================
Replaces legacy SQLite scraper storage (`gmaps.sqlite`) with high-throughput,
ACID-compliant PostgreSQL tables in the `staging_dataextraction` schema:
  - staging_dataextraction.scraper_jobs
  - staging_dataextraction.scraper_tiles (with FOR UPDATE SKIP LOCKED distributed leases)
  - staging_dataextraction.scraper_results (high-performance bulk upserts via execute_values)
  - staging_dataextraction.scraper_job_events (audit telemetry)

Production Standards:
  - Connection pooling via db_connector
  - ACID guarantees & zero table-level locking
  - Distributed worker lease engine with lease expiry & auto-heartbeating
  - High-throughput batch ingestion
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

# Path setup to import db_connector cleanly
_PKG_DIR = Path(__file__).resolve().parents[2]
_INFRA_DIR = _PKG_DIR / "infrastructure"
for p in [str(_INFRA_DIR), str(_PKG_DIR)]:
    if p not in sys.path:
        sys.path.append(p)

from db_connector import get_connection, release_connection
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

logger = logging.getLogger("dataextraction.scrapers.gmaps.postgres_storage")


class EnterpriseGMapsStorage:
    """
    PostgreSQL-native storage engine for Google Maps extraction,
    supporting distributed worker leasing and high-throughput upsert pipelines.
    """

    def __init__(self):
        self._ensure_connectivity()

    def _ensure_connectivity(self):
        """Validates connection to PostgreSQL on initialization."""
        conn = None
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
            logger.info("EnterpriseGMapsStorage successfully connected to PostgreSQL.")
        except Exception as exc:
            logger.warning("EnterpriseGMapsStorage initial ping notice: %s", exc)
        finally:
            if conn:
                release_connection(conn)

    # --------------------------------------------------------------------------
    # Job Lifecycle
    # --------------------------------------------------------------------------
    def create_job(
        self,
        job_type: str,
        target_country: str,
        target_region: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Creates a new extraction job in staging_dataextraction.scraper_jobs."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staging_dataextraction.scraper_jobs (
                        job_type, target_country, target_region, parameters, status
                    ) VALUES (%s, %s, %s, %s, 'RUNNING')
                    RETURNING job_id::text;
                    """,
                    (
                        job_type,
                        target_country.upper(),
                        target_region.upper() if target_region else None,
                        json.dumps(parameters or {}),
                    ),
                )
                job_id = cur.fetchone()[0]
                conn.commit()
                return str(job_id)
        finally:
            release_connection(conn)

    def update_job_status(
        self,
        job_id: str,
        status: str,
        completed_tiles: Optional[int] = None,
        failed_tiles: Optional[int] = None,
        records_collected: Optional[int] = None,
    ) -> bool:
        """Updates job progress and status in staging_dataextraction.scraper_jobs."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                updates = ["status = %s", "updated_at = NOW()"]
                params = [status.upper()]
                if completed_tiles is not None:
                    updates.append("completed_tiles = %s")
                    params.append(completed_tiles)
                if failed_tiles is not None:
                    updates.append("failed_tiles = %s")
                    params.append(failed_tiles)
                if records_collected is not None:
                    updates.append("records_collected = %s")
                    params.append(records_collected)

                params.append(job_id)
                cur.execute(
                    f"UPDATE staging_dataextraction.scraper_jobs SET {', '.join(updates)} WHERE job_id = %s::uuid;",
                    tuple(params),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            release_connection(conn)

    # --------------------------------------------------------------------------
    # Tile Registration & Distributed Leasing Engine (FOR UPDATE SKIP LOCKED)
    # --------------------------------------------------------------------------
    def register_tiles(self, job_id: str, tiles: List[Dict[str, Any]]) -> int:
        """
        Batch registers geographic tiles into staging_dataextraction.scraper_tiles.
        Uses ON CONFLICT DO NOTHING for idempotent resume support.
        """
        if not tiles:
            return 0

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                insert_data = []
                for t in tiles:
                    insert_data.append((
                        t["tile_id"],
                        job_id,
                        t.get("country_code", "US").upper(),
                        t.get("region", "UNKNOWN").upper(),
                        float(t["min_lat"]),
                        float(t["max_lat"]),
                        float(t["min_lng"]),
                        float(t["max_lng"]),
                        int(t.get("priority", 100)),
                        "PENDING",
                        int(t.get("max_retries", 3)),
                    ))

                query = """
                INSERT INTO staging_dataextraction.scraper_tiles (
                    tile_id, job_id, country_code, region, min_lat, max_lat,
                    min_lng, max_lng, priority, status, max_retries
                ) VALUES %s
                ON CONFLICT (tile_id) DO UPDATE SET
                    job_id = EXCLUDED.job_id,
                    updated_at = NOW();
                """
                execute_values(cur, query, insert_data, page_size=1000)

                # Update total_tiles count in scraper_jobs
                cur.execute(
                    """
                    UPDATE staging_dataextraction.scraper_jobs
                    SET total_tiles = (
                        SELECT count(*) FROM staging_dataextraction.scraper_tiles WHERE job_id = %s::uuid
                    ), updated_at = NOW()
                    WHERE job_id = %s::uuid;
                    """,
                    (job_id, job_id),
                )
                conn.commit()
                return len(insert_data)
        finally:
            release_connection(conn)

    def claim_next_tile(
        self,
        worker_id: str,
        lease_seconds: int = 300,
        country_code: Optional[str] = None,
        region: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Atomically leases the next eligible tile using `FOR UPDATE SKIP LOCKED`.
        Eligible tiles are:
          1. status = 'PENDING'
          2. status = 'LEASED' AND lease_expires_at < NOW() (expired worker lease)
          3. status = 'FAILED' AND retry_count < max_retries
        """
        conn = get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                WITH candidate AS (
                    SELECT tile_id
                    FROM staging_dataextraction.scraper_tiles
                    WHERE (
                        status = 'PENDING'
                        OR (status = 'LEASED' AND lease_expires_at < NOW())
                        OR (status = 'FAILED' AND retry_count < max_retries)
                    )
                    AND (%s IS NULL OR country_code = %s)
                    AND (%s IS NULL OR region = %s)
                    AND (%s IS NULL OR job_id = %s::uuid)
                    ORDER BY priority DESC, created_at ASC
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE staging_dataextraction.scraper_tiles t
                SET status = 'LEASED',
                    worker_id = %s,
                    lease_expires_at = NOW() + (%s || ' seconds')::INTERVAL,
                    updated_at = NOW()
                FROM candidate
                WHERE t.tile_id = candidate.tile_id
                RETURNING
                    t.tile_id,
                    t.job_id::text,
                    t.country_code,
                    t.region,
                    t.min_lat::float,
                    t.max_lat::float,
                    t.min_lng::float,
                    t.max_lng::float,
                    t.priority,
                    t.status,
                    t.worker_id,
                    t.lease_expires_at,
                    t.retry_count;
                """
                c_code = country_code.upper() if country_code else None
                r_code = region.upper() if region else None
                cur.execute(
                    query,
                    (c_code, c_code, r_code, r_code, job_id, job_id, worker_id, str(lease_seconds)),
                )
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None
        finally:
            release_connection(conn)

    def heartbeat_tile(self, tile_id: str, worker_id: str, extension_seconds: int = 300) -> bool:
        """Renews worker lease expiration for a currently leased tile."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging_dataextraction.scraper_tiles
                    SET lease_expires_at = NOW() + (%s || ' seconds')::INTERVAL,
                        updated_at = NOW()
                    WHERE tile_id = %s AND worker_id = %s AND status = 'LEASED';
                    """,
                    (str(extension_seconds), tile_id, worker_id),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            release_connection(conn)

    def complete_tile(self, tile_id: str, worker_id: str, records_count: int = 0) -> bool:
        """Marks a tile as COMPLETED and records collected record counts."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging_dataextraction.scraper_tiles
                    SET status = 'COMPLETED',
                        lease_expires_at = NULL,
                        records_count = %s,
                        updated_at = NOW()
                    WHERE tile_id = %s;
                    """,
                    (records_count, tile_id),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            release_connection(conn)

    def fail_tile(self, tile_id: str, worker_id: str, error_msg: str) -> bool:
        """Increments retry counter and records failure on a tile."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging_dataextraction.scraper_tiles
                    SET status = 'FAILED',
                        retry_count = retry_count + 1,
                        last_error = %s,
                        lease_expires_at = NULL,
                        updated_at = NOW()
                    WHERE tile_id = %s;
                    """,
                    (str(error_msg)[:1000], tile_id),
                )
                conn.commit()
                return cur.rowcount > 0
        finally:
            release_connection(conn)

    # --------------------------------------------------------------------------
    # High-Performance Bulk Ingestion (execute_values)
    # --------------------------------------------------------------------------
    def bulk_upsert_results(
        self,
        results: List[Dict[str, Any]],
        batch_size: int = 1000,
    ) -> int:
        """
        High-throughput bulk upsert into `staging_dataextraction.scraper_results` via `psycopg2.extras.execute_values`.
        Guarantees idempotency via `ON CONFLICT (cid) DO UPDATE`.
        """
        if not results:
            return 0

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                records = []
                for r in results:
                    cid = str(r.get("cid") or r.get("place_id") or "").strip()
                    if not cid:
                        continue

                    records.append((
                        cid,
                        r.get("tile_id"),
                        r.get("name") or "Unknown Business",
                        r.get("category"),
                        r.get("vertical"),
                        r.get("vertical_raw"),
                        r.get("phone"),
                        r.get("phone_e164"),
                        r.get("website") or r.get("website_url"),
                        r.get("normalized_domain"),
                        r.get("address") or r.get("street_address"),
                        r.get("city"),
                        r.get("region") or r.get("state_code"),
                        r.get("country_code") or "US",
                        r.get("postal_code"),
                        float(r["latitude"]) if r.get("latitude") is not None else None,
                        float(r["longitude"]) if r.get("longitude") is not None else None,
                        float(r["rating"]) if r.get("rating") is not None else None,
                        int(r.get("review_count") or 0),
                        r.get("timezone"),
                        int(r.get("claimed_status") or 0),
                        json.dumps(r.get("raw_payload") or {}),
                    ))

                query = """
                INSERT INTO staging_dataextraction.scraper_results (
                    cid, tile_id, name, category, vertical, vertical_raw,
                    phone, phone_e164, website_url, normalized_domain,
                    street_address, city, state_code, country_code, postal_code,
                    latitude, longitude, rating, review_count, timezone,
                    claimed_status, raw_payload
                ) VALUES %s
                ON CONFLICT (cid) DO UPDATE SET
                    name = EXCLUDED.name,
                    category = COALESCE(EXCLUDED.category, staging_dataextraction.scraper_results.category),
                    vertical = COALESCE(EXCLUDED.vertical, staging_dataextraction.scraper_results.vertical),
                    phone = COALESCE(EXCLUDED.phone, staging_dataextraction.scraper_results.phone),
                    phone_e164 = COALESCE(EXCLUDED.phone_e164, staging_dataextraction.scraper_results.phone_e164),
                    website_url = COALESCE(EXCLUDED.website_url, staging_dataextraction.scraper_results.website_url),
                    normalized_domain = COALESCE(EXCLUDED.normalized_domain, staging_dataextraction.scraper_results.normalized_domain),
                    street_address = COALESCE(EXCLUDED.street_address, staging_dataextraction.scraper_results.street_address),
                    city = COALESCE(EXCLUDED.city, staging_dataextraction.scraper_results.city),
                    state_code = COALESCE(EXCLUDED.state_code, staging_dataextraction.scraper_results.state_code),
                    country_code = COALESCE(EXCLUDED.country_code, staging_dataextraction.scraper_results.country_code),
                    postal_code = COALESCE(EXCLUDED.postal_code, staging_dataextraction.scraper_results.postal_code),
                    latitude = COALESCE(EXCLUDED.latitude, staging_dataextraction.scraper_results.latitude),
                    longitude = COALESCE(EXCLUDED.longitude, staging_dataextraction.scraper_results.longitude),
                    rating = COALESCE(EXCLUDED.rating, staging_dataextraction.scraper_results.rating),
                    review_count = GREATEST(EXCLUDED.review_count, staging_dataextraction.scraper_results.review_count),
                    raw_payload = EXCLUDED.raw_payload,
                    updated_at = NOW();
                """
                execute_values(cur, query, records, page_size=batch_size)
                conn.commit()
                return len(records)
        finally:
            release_connection(conn)

    # --------------------------------------------------------------------------
    # Telemetry and Audit Logging
    # --------------------------------------------------------------------------
    def log_event(
        self,
        job_id: str,
        event_type: str,
        worker_id: Optional[str] = None,
        message: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Appends audit event to staging_dataextraction.scraper_job_events."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staging_dataextraction.scraper_job_events (
                        job_id, event_type, worker_id, message, payload
                    ) VALUES (%s::uuid, %s, %s, %s, %s)
                    RETURNING event_id;
                    """,
                    (
                        job_id,
                        event_type.upper(),
                        worker_id,
                        message,
                        json.dumps(payload or {}),
                    ),
                )
                event_id = cur.fetchone()[0]
                conn.commit()
                return int(event_id)
        finally:
            release_connection(conn)
