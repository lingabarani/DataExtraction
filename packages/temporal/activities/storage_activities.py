"""
DataExtraction — Storage & DLQ Activities
==========================================
Temporal activity wrappers for database read/write operations and
Dead Letter Queue management. Used by agent workflows and DLQReplayWorkflow.
"""

import logging
import sys
from pathlib import Path
from typing import Any

from temporalio import activity

INFRA_PATH = Path(__file__).resolve().parents[3] / "infrastructure"
if str(INFRA_PATH.parent) not in sys.path:
    sys.path.insert(0, str(INFRA_PATH.parent))

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

    from infrastructure.dead_letter_queue import fetch_pending  # type: ignore

    records = fetch_pending(
        limit=config.get("limit", 100),
        status=config.get("status", "PENDING"),
        source=config.get("source"),
    )
    return {"records": [r.to_dict() for r in records], "total": len(records)}


@activity.defn(name="resolve_dlq_record")
async def resolve_dlq_record_activity(record_id: str, status: str, notes: str = "") -> dict:
    """
    Marks a DLQ record as RESOLVED or ESCALATED.

    Args:
        record_id: UUID of the DLQ record
        status: "RESOLVED" | "ESCALATED"
        notes: Optional resolution notes

    Returns:
        {"record_id": str, "status": str, "updated": bool}
    """
    activity.logger.info("Resolving DLQ record: id=%s status=%s", record_id, status)

    from infrastructure.dead_letter_queue import update_status  # type: ignore

    updated = update_status(record_id=record_id, status=status, notes=notes)
    return {"record_id": record_id, "status": status, "updated": updated}


@activity.defn(name="get_dlq_stats")
async def get_dlq_stats_activity(_: dict = None) -> dict:
    """
    Returns current DLQ statistics for monitoring by agents.

    Returns:
        {
            "dlq_pending": int,
            "dlq_failed": int,
            "dlq_resolved": int,
            "oldest_age_hours": float,
            "by_source": dict[str, int]
        }
    """
    from infrastructure.dead_letter_queue import get_stats  # type: ignore

    stats = get_stats()
    return stats.to_dict()


@activity.defn(name="storage_query")
async def storage_query_activity(query_name: str, params: dict = None) -> dict:
    """
    Executes a named read-only storage query. Used by agents to observe state
    without direct DB access.

    Args:
        query_name: Named query identifier (defined in infrastructure/db_connector.py)
        params: Query parameters

    Returns:
        Query result as dict
    """
    activity.logger.info("Storage query: %s params=%s", query_name, params or {})

    from infrastructure.db_connector import named_query  # type: ignore

    result = named_query(query_name, params or {})
    return {"query": query_name, "result": result}


@activity.defn(name="check_gmp_budget")
async def check_gmp_budget_activity(_: dict = None) -> dict:
    """
    Checks remaining Google Maps Platform daily budget.
    Used as a pre-condition gate before GMP enrichment activities.

    Returns:
        {"budget_remaining_usd": float, "budget_limit_usd": float, "authorized": bool}
    """
    import os
    from infrastructure.db_connector import named_query  # type: ignore

    limit = float(os.getenv("GOOGLE_MAPS_DAILY_BUDGET_USD", "50.0"))
    enabled = os.getenv("GOOGLE_MAPS_ENRICHMENT_ENABLED", "false").lower() == "true"

    if not enabled:
        return {"budget_remaining_usd": 0.0, "budget_limit_usd": limit, "authorized": False,
                "reason": "GMP enrichment disabled via GOOGLE_MAPS_ENRICHMENT_ENABLED"}

    result = named_query("gmp_today_spend", {})
    spent = result.get("total_spend_usd", 0.0)
    remaining = max(0.0, limit - spent)

    return {
        "budget_remaining_usd": remaining,
        "budget_limit_usd": limit,
        "authorized": remaining > 0,
        "spent_today_usd": spent,
    }
