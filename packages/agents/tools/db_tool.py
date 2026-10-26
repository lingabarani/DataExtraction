"""
DataExtraction — Agent Read-Only Database Tool
==============================================
Provides safe, read-only analytical queries for agents to observe database state
without side effects or write capabilities.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("dataextraction.agents.tools.db")


async def get_dlq_stats() -> Dict[str, Any]:
    """
    Retrieves Dead Letter Queue statistics.
    Returns:
        {"dlq_pending": int, "oldest_age_hours": float, "by_source": dict}
    """
    try:
        from packages.infrastructure.dead_letter_queue import dead_letter_queue
        stats = dead_letter_queue.get_stats()
        return {
            "dlq_pending": stats.get("total_pending", 0),
            "oldest_age_hours": stats.get("oldest_record_age_hours", 0.0),
            "by_source": stats.get("pending_by_source", {}),
            "total_replayed": stats.get("total_replayed", 0),
        }
    except Exception as exc:
        logger.warning("Failed to query DLQ stats: %s", exc)
        return {"dlq_pending": 0, "oldest_age_hours": 0.0, "by_source": {}, "error": str(exc)}


async def get_table_counts(tables: Optional[List[str]] = None) -> Dict[str, int]:
    """
    Queries row counts for specified tables using read-only db_connector.
    """
    if tables is None:
        tables = ["us_companies", "federal_leads", "us_leads", "dlq_quarantine"]

    counts: Dict[str, int] = {}
    try:
        from packages.infrastructure.db_connector import get_db_cursor
        with get_db_cursor() as (conn, cur):
            for tbl in tables:
                try:
                    cur.execute(f"SELECT COUNT(1) FROM {tbl}")
                    row = cur.fetchone()
                    counts[tbl] = row[0] if row else 0
                except Exception as tbl_err:
                    conn.rollback()
                    counts[tbl] = -1
    except Exception as exc:
        logger.warning("Failed to query table counts: %s", exc)
    return counts


async def get_source_freshness() -> Dict[str, Any]:
    """
    Queries the latest timestamp recorded per data source.
    """
    freshness: Dict[str, Any] = {}
    try:
        from packages.infrastructure.db_connector import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT source, MAX(created_at) as last_seen, COUNT(1) as total
                FROM us_companies
                GROUP BY source
            """)
            for row in cur.fetchall():
                freshness[row[0]] = {
                    "last_seen": row[1].isoformat() if row[1] else None,
                    "record_count": row[2]
                }
    except Exception as exc:
        logger.warning("Failed to query source freshness: %s", exc)
    return freshness
