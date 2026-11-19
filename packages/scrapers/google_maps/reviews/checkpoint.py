"""
DataExtraction — Google Maps Review Checkpoint Store
====================================================
Tracks crash-safe pagination tokens and extraction states in PostgreSQL:
`staging_dataextraction.place_review_checkpoints`.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("dataextraction.gmaps.reviews.checkpoint")


class ReviewCheckpointStore:
    def __init__(self, get_conn_fn: Callable[[], Any], release_conn_fn: Callable[[Any], None]):
        self._get_conn = get_conn_fn
        self._release_conn = release_conn_fn

    def get_checkpoint(self, place_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves existing checkpoint state for a place."""
        conn = self._get_conn()
        if not conn:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT place_id, next_pagination_token, reviews_extracted, status,
                           last_extracted_at, run_id, updated_at
                    FROM staging_dataextraction.place_review_checkpoints
                    WHERE place_id = %s
                    """,
                    (place_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "place_id": row[0],
                    "next_pagination_token": row[1],
                    "reviews_extracted": row[2],
                    "status": row[3],
                    "last_extracted_at": row[4],
                    "run_id": row[5],
                    "updated_at": row[6],
                }
        except Exception as exc:
            logger.warning("Error fetching review checkpoint for place %s: %s", place_id, exc)
            return None
        finally:
            self._release_conn(conn)

    def save_checkpoint(
        self,
        place_id: str,
        token: Optional[str],
        reviews_added: int,
        status: str = "in_progress",
        run_id: Optional[str] = None,
    ) -> None:
        """Atomically upserts checkpoint token and increments extracted count."""
        conn = self._get_conn()
        if not conn:
            return
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staging_dataextraction.place_review_checkpoints (
                        place_id, next_pagination_token, reviews_extracted, status,
                        last_extracted_at, run_id, updated_at
                    ) VALUES (%s, %s, %s, %s, NOW(), %s, NOW())
                    ON CONFLICT (place_id) DO UPDATE SET
                        next_pagination_token = EXCLUDED.next_pagination_token,
                        reviews_extracted = staging_dataextraction.place_review_checkpoints.reviews_extracted + EXCLUDED.reviews_extracted,
                        status = EXCLUDED.status,
                        last_extracted_at = NOW(),
                        run_id = COALESCE(EXCLUDED.run_id, staging_dataextraction.place_review_checkpoints.run_id),
                        updated_at = NOW()
                    """,
                    (place_id, token, reviews_added, status, run_id),
                )
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("Failed to save review checkpoint for place %s: %s", place_id, exc)
        finally:
            self._release_conn(conn)
