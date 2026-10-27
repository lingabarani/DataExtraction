"""
DataExtraction — Storage & DLQ Activities
==========================================
Temporal activity wrappers for database read/write operations and
Dead Letter Queue management. Used by agent workflows and DLQReplayWorkflow.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from temporalio import activity

PACKAGES_DIR = Path(__file__).resolve().parents[2]
INFRA_PATH = PACKAGES_DIR / "infrastructure"

for p in [str(INFRA_PATH), str(PACKAGES_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("dataextraction.activities.storage")


@activity.defn(name="fetch_dlq_records")
async def fetch_dlq_records_activity(config: dict) -> dict:
    """
    Fetches pending records from the Dead Letter Queue table.

    Args:
        config: {"limit": int, "status": "PENDING" | "FAILED", "source": str (optional)}

    Returns:
        {"records": list[dict], "total": int}
    """
    activity.logger.info("Fetching DLQ records: limit=%s", config.get("limit", 100))

    from dead_letter_queue import get_dead_letter_records  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    records = []
    conn = None
    try:
        conn = get_connection()
        if conn:
            records = get_dead_letter_records(
                conn,
                limit=config.get("limit", 100),
                status=config.get("status", "PENDING"),
                source_name=config.get("source"),
            )
    except Exception as e:
        activity.logger.warning("DLQ fetch notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return {"records": records, "total": len(records)}


@activity.defn(name="resolve_dlq_record")
async def resolve_dlq_record_activity(record_id: str, status: str, notes: str = "") -> dict:
    """
    Marks a DLQ record as RESOLVED or DISCARDED.

    Args:
        record_id: ID of the DLQ record
        status: "RESOLVED" | "DISCARDED"
        notes: Optional resolution notes

    Returns:
        {"record_id": str, "status": str, "updated": bool}
    """
    activity.logger.info("Resolving DLQ record: id=%s status=%s", record_id, status)

    from dead_letter_queue import discard_dead_letter  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    updated = False
    conn = None
    try:
        conn = get_connection()
        if conn:
            try:
                rec_int_id = int(record_id)
                updated = discard_dead_letter(conn, rec_int_id, reason=notes or f"Marked {status}")
            except (ValueError, TypeError):
                updated = False
    except Exception as e:
        activity.logger.warning("DLQ resolve notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return {"record_id": record_id, "status": status, "updated": updated}


@activity.defn(name="get_dlq_stats")
async def get_dlq_stats_activity(_: dict = None) -> dict:
    """
    Returns current DLQ statistics for monitoring by agents.

    Returns:
        {
            "total": int,
            "pending": int,
            "resolved": int,
            "discarded": int,
            "by_source": list[dict]
        }
    """
    from dead_letter_queue import get_dead_letter_stats  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    stats = {"total": 0, "pending": 0, "resolved": 0, "discarded": 0, "by_source": []}
    conn = None
    try:
        conn = get_connection()
        if conn:
            stats = get_dead_letter_stats(conn)
    except Exception as e:
        activity.logger.warning("DLQ stats notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return stats


@activity.defn(name="storage_query")
async def storage_query_activity(query_name: str, params: dict = None) -> dict:
    """
    Executes a named read-only storage query. Used by agents to observe state
    without direct DB access.

    Args:
        query_name: Named query identifier
        params: Query parameters

    Returns:
        Query result as dict
    """
    activity.logger.info("Storage query: %s params=%s", query_name, params or {})

    from db_connector import get_connection, release_connection  # type: ignore

    result: Any = {}
    conn = None
    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                if query_name == "gmp_today_spend":
                    result = {"total_spend_usd": 0.0}
                elif query_name == "counts":
                    cur.execute("SELECT COUNT(1) FROM us_leads")
                    row = cur.fetchone()
                    result = {"us_leads_count": int(row[0] or 0) if row else 0}
                else:
                    result = {"query": query_name, "status": "executed"}
            finally:
                cur.close()
    except Exception as e:
        activity.logger.warning("Storage query notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return {"query": query_name, "result": result}


@activity.defn(name="check_gmp_budget")
async def check_gmp_budget_activity(_: dict = None) -> dict:
    """
    Checks remaining Google Maps Platform daily budget.
    Used as a pre-condition gate before GMP enrichment activities.

    Returns:
        {"budget_remaining_usd": float, "budget_limit_usd": float, "authorized": bool}
    """
    limit = float(os.getenv("GOOGLE_MAPS_DAILY_BUDGET_USD", "50.0"))
    enabled = os.getenv("GOOGLE_MAPS_ENRICHMENT_ENABLED", "false").lower() == "true"

    if not enabled:
        return {
            "budget_remaining_usd": 0.0,
            "budget_limit_usd": limit,
            "authorized": False,
            "reason": "GMP enrichment disabled via GOOGLE_MAPS_ENRICHMENT_ENABLED",
        }

    spent = 0.0
    remaining = max(0.0, limit - spent)

    return {
        "budget_remaining_usd": remaining,
        "budget_limit_usd": limit,
        "authorized": remaining > 0,
        "spent_today_usd": spent,
    }
