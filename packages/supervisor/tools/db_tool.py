"""
DataExtraction — Platform SRE Supervisor Read-Only Database Tool
===============================================================
Provides safe, read-only analytical queries for platform supervisors to observe
database state, connection health, and Dead Letter Queue volumes without side effects.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("dataextraction.supervisor.tools.db")


async def get_dlq_stats() -> Dict[str, Any]:
    """
    Retrieves Dead Letter Queue statistics.
    Returns:
        {"dlq_pending": int, "oldest_age_hours": float, "by_source": dict, "total_replayed": int}
    """
    try:
        from packages.infrastructure.db_connector import get_connection, release_connection
        from packages.infrastructure.dead_letter_queue import get_dead_letter_stats
        conn = get_connection()
        if conn:
            try:
                stats = get_dead_letter_stats(conn)
                return {
                    "dlq_pending": stats.get("total_pending", 0),
                    "oldest_age_hours": stats.get("oldest_record_age_hours", 0.0),
                    "by_source": stats.get("pending_by_source", {}),
                    "total_replayed": stats.get("total_replayed", 0),
                }
            finally:
                release_connection(conn)
        return {"dlq_pending": 0, "oldest_age_hours": 0.0, "by_source": {}, "total_replayed": 0}
    except Exception as exc:
        logger.warning("Failed to query DLQ stats: %s", exc)
        return {"dlq_pending": 0, "oldest_age_hours": 0.0, "by_source": {}, "total_replayed": 0, "error": str(exc)}


async def get_table_counts(tables: Optional[List[str]] = None) -> Dict[str, int]:
    """
    Returns row counts for specified PostgreSQL Knowledge Graph tables.
    """
    target_tables = tables or [
        "kg_core.organizations",
        "kg_core.people",
        "kg_core.relationships",
        "kg_core.observations",
        "kg_resolution.isolation_review_queue",
        "companies",
        "people",
    ]

    counts: Dict[str, int] = {}
    conn = None
    try:
        from packages.infrastructure.db_connector import get_connection, release_connection, _assert_safe_identifier
        conn = get_connection()
        if not conn:
            return {t: 0 for t in target_tables}

        cur = conn.cursor()
        for tbl in target_tables:
            try:
                # Sanitized table identifier verification
                parts = tbl.split(".")
                for p in parts:
                    _assert_safe_identifier(p)
                cur.execute(f"SELECT COUNT(1) FROM {tbl}")
                row = cur.fetchone()
                counts[tbl] = int(row[0]) if row else 0
            except Exception as t_err:
                logger.debug("Table count query notice for %s: %s", tbl, t_err)
                counts[tbl] = 0
                if conn:
                    conn.rollback()
        cur.close()
    except Exception as exc:
        logger.warning("Database unavailable for supervisor table counts: %s", exc)
        return {t: 0 for t in target_tables}
    finally:
        if conn:
            release_connection(conn)

    return counts


async def get_source_freshness() -> Dict[str, Any]:
    """
    Checks the most recent observation ingested per source.
    """
    freshness: Dict[str, Any] = {}
    conn = None
    try:
        from packages.infrastructure.db_connector import get_connection, release_connection
        conn = get_connection()
        if not conn:
            return {}

        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT source_system, MAX(observed_at) as last_seen, COUNT(1) as total
                FROM kg_core.observations
                GROUP BY source_system
                """
            )
            for row in cur.fetchall():
                freshness[row[0]] = {
                    "last_seen": row[1].isoformat() if row[1] else None,
                    "total_observations": row[2]
                }
        except Exception as q_err:
            logger.debug("Source freshness query notice: %s", q_err)
            if conn:
                conn.rollback()
        finally:
            cur.close()
    except Exception as exc:
        logger.warning("Database unavailable for supervisor source freshness: %s", exc)
    finally:
        if conn:
            release_connection(conn)

    return freshness


__all__ = [
    "get_dlq_stats",
    "get_table_counts",
    "get_source_freshness",
]
