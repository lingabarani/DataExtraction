"""LLM usage ledger and daily token budget. Stores counters only, never prompt text."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("dataextraction.llm.usage")


def record_usage(*, provider: str, model: str, key_id: Optional[str], purpose: str,
                 prompt_tokens: int, completion_tokens: int, latency_ms: int,
                 status_code: Optional[int], success: bool) -> None:
    """Best-effort insert. A failing ledger must never break an LLM call."""
    # key_id is a UUID only for DB keys; env/aws keys use string ids and are stored as NULL.
    db_key_id = key_id if key_id and ":" not in key_id else None
    try:
        from packages.infrastructure.db_connector import get_db_cursor
        with get_db_cursor() as (_c, cur):
            cur.execute(
                """
                INSERT INTO ops_dataextraction.llm_usage
                    (provider, model, key_id, purpose, prompt_tokens, completion_tokens,
                     latency_ms, status_code, success)
                VALUES (%s, %s, %s::uuid, %s, %s, %s, %s, %s, %s)
                """,
                (provider, model, db_key_id, purpose[:80], int(prompt_tokens), int(completion_tokens),
                 int(latency_ms), status_code, success),
            )
    except Exception as exc:
        logger.debug("llm_usage insert skipped: %s", exc)


def tokens_used_today() -> Optional[int]:
    """Total tokens since UTC midnight, or None when the ledger is unreachable."""
    try:
        from packages.infrastructure.db_connector import get_db_cursor
        with get_db_cursor() as (_c, cur):
            cur.execute(
                """
                SELECT COALESCE(SUM(prompt_tokens + completion_tokens), 0)
                FROM ops_dataextraction.llm_usage
                WHERE ts >= date_trunc('day', NOW() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                """
            )
            return int(cur.fetchone()[0])
    except Exception as exc:
        logger.debug("tokens_used_today unavailable: %s", exc)
        return None


def daily_budget() -> int:
    """0 means unlimited."""
    try:
        return max(0, int(os.getenv("LLM_DAILY_TOKEN_BUDGET", "0")))
    except ValueError:
        return 0


def budget_status() -> Dict[str, Any]:
    budget = daily_budget()
    used = tokens_used_today()
    return {
        "daily_token_budget": budget,
        "tokens_used_today": used,
        "unlimited": budget == 0,
        "remaining": None if (budget == 0 or used is None) else max(0, budget - used),
    }
