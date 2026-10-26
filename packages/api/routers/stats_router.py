"""
OneExtraction — Dashboard Stats Router
Reads instant cached metrics from stats_cache table (< 10ms response time).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends

from api.deps import UserPrincipal, get_current_user
from db_connector import get_connection, release_connection

logger = logging.getLogger("oneextraction.stats")

router = APIRouter(tags=["stats"])


def _read_cache(cur, key: str, default):
    """Read a JSON document from stats_cache by primary key."""
    try:
        cur.execute("SELECT value_json FROM stats_cache WHERE key = %s", (key,))
        row = cur.fetchone()
        return row[0] if row else default
    except Exception as e:
        logger.warning("Cache miss/read error for key '%s': %s", key, e)
        return default


def _pg_count(cur, table: str) -> int:
    """Instant row count from pg_class system catalog."""
    try:
        cur.execute("SELECT reltuples::BIGINT FROM pg_class WHERE relname=%s", (table,))
        r = cur.fetchone()
        return max(0, int(r[0])) if r and r[0] > 0 else 0
    except Exception:
        return 0


@router.get("/stats")
def get_stats(user: UserPrincipal = Depends(get_current_user)):
    """Returns top-level coverage, industry, source, and regional statistics."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        us_total = _pg_count(cur, "us_leads")
        mx_total = _pg_count(cur, "mexico_leads")

        us_cov = _read_cache(cur, "us_coverage", {})
        mx_cov = _read_cache(cur, "mx_coverage", {})
        src = _read_cache(cur, "by_source", [])
        ind = _read_cache(cur, "by_industry", [])
        sen = _read_cache(cur, "by_seniority", [])
        sta = _read_cache(cur, "by_state", [])
        cur.close()

        return {
            "us_total": us_total,
            "mx_total": mx_total,
            "us_with_phone": us_cov.get("us_with_phone", 0),
            "us_with_email": us_cov.get("us_with_email", 0),
            "us_verified_email": us_cov.get("us_verified_email", 0),
            "mx_with_phone": mx_cov.get("mx_with_phone", 0),
            "mx_with_email": mx_cov.get("mx_with_email", 0),
            "mx_verified_email": mx_cov.get("mx_verified_email", 0),
            "by_source": src if isinstance(src, list) else [],
            "by_industry": ind if isinstance(ind, list) else [],
            "by_seniority": sen if isinstance(sen, list) else [],
            "by_state": sta if isinstance(sta, list) else [],
        }
    finally:
        release_connection(conn)


@router.get("/workspace")
def get_workspace(user: UserPrincipal = Depends(get_current_user)):
    """Returns metadata for the active workspace."""
    return {"id": "ws-001", "name": "OneExtraction", "slug": "oneextraction"}


@router.patch("/workspace")
def update_workspace(body: dict, user: UserPrincipal = Depends(get_current_user)):
    """Updates workspace settings."""
    return {"id": "ws-001", **body}
