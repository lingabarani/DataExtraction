"""
DataExtraction — Google Maps Review Scraper
===========================================
Dedicated, unconstrained Google Maps review extraction engine.
Supports incremental batch persistence, crash-resilient pagination resumption,
review suppression, and privacy-preserving reviewer identity hashing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_GMAPS_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_GMAPS_SRC) not in sys.path:
    sys.path.insert(0, str(_GMAPS_SRC))

from gmaps_scraper.reviews import build_boq_reviews_url, parse_reviews_response
from gmaps_scraper.http import HttpClient, _is_blocked_response
from packages.scrapers.google_maps.deep_place import (
    build_review_row,
    reviewer_identity,
    reviewer_mode,
    _hash_key,
)
from packages.scrapers.google_maps.reviews.checkpoint import ReviewCheckpointStore

logger = logging.getLogger("dataextraction.gmaps.reviews.scraper")


class GoogleMapsReviewScraper:
    def __init__(
        self,
        http_client: Optional[HttpClient] = None,
        get_conn_fn: Optional[Callable[[], Any]] = None,
        release_conn_fn: Optional[Callable[[Any], None]] = None,
        mode: Optional[str] = None,
        page_size: int = 10,
        delay_range: Tuple[float, float] = (0.5, 1.5),
        suppressed_fn: Optional[Callable[[Optional[str]], bool]] = None,
    ):
        self._http = http_client
        self._get_conn = get_conn_fn
        self._release_conn = release_conn_fn
        self._mode = mode or os.getenv("REVIEWER_NAME_MODE", "hash").strip().lower()
        salt = os.getenv("REVIEWER_HASH_SALT") or os.getenv("SECRETS_MASTER_KEY") or "default_dataextraction_reviewer_hash_salt"
        self._key = salt.encode("utf-8") if self._mode == "hash" else None
        self._page_size = page_size
        self._delay_range = delay_range
        self._suppressed = suppressed_fn or (lambda _v: False)
        self._checkpoint_store = ReviewCheckpointStore(self._get_conn, self._release_conn)

    async def _get_http(self) -> HttpClient:
        if self._http is None:
            from gmaps_scraper.config import load_config
            self._http = HttpClient(load_config())
        return self._http

    async def extract_reviews_for_place(
        self,
        place_stub: Dict[str, Any],
        run_id: str,
        max_reviews: Optional[int] = None,
        resume: bool = True,
        heartbeat: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        Extracts reviews for a single place.
        Supports unconstrained pagination (when max_reviews is None or <= 0).
        Resumes from stored checkpoint token if available.
        Persists reviews incrementally per page.
        """
        place_id = str(place_stub.get("place_id") or place_stub.get("cid"))
        ftid = place_stub.get("ftid")
        if not ftid:
            # Try to get ftid from place_details if available
            ftid = self._lookup_ftid(place_id)

        if not ftid:
            logger.info("Skipping review extraction for %s: missing ftid", place_id)
            return {"place_id": place_id, "reviews_saved": 0, "status": "skipped_no_ftid"}

        client = await self._get_http()
        token: Optional[str] = None
        already_extracted = 0

        if resume:
            cp = self._checkpoint_store.get_checkpoint(place_id)
            if cp:
                token = cp.get("next_pagination_token")
                already_extracted = int(cp.get("reviews_extracted") or 0)
                if cp.get("status") == "complete" and not token:
                    logger.debug("Place %s reviews already completed (%d reviews)", place_id, already_extracted)
                    return {
                        "place_id": place_id,
                        "reviews_saved": 0,
                        "total_extracted": already_extracted,
                        "status": "already_completed",
                    }

        total_target = max_reviews if (max_reviews and max_reviews > 0) else 10**9
        saved_count = 0
        seen_ids = set()
        status = "complete"

        source_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

        while (already_extracted + saved_count) < total_target:
            url = build_boq_reviews_url(ftid, page_size=self._page_size, sort_code=1, pagination_token=token)
            try:
                resp = await client.get(url)
            except Exception as exc:
                logger.warning("Network error fetching reviews for %s: %s", place_id, exc)
                status = "error"
                break

            if _is_blocked_response(resp):
                logger.warning("Place %s review request was blocked/rate-limited", place_id)
                self._checkpoint_store.save_checkpoint(
                    place_id=place_id,
                    token=token,
                    reviews_added=0,
                    status="blocked",
                    run_id=run_id,
                )
                return {
                    "place_id": place_id,
                    "reviews_saved": saved_count,
                    "total_extracted": already_extracted + saved_count,
                    "status": "blocked",
                }

            parsed, next_token = parse_reviews_response(resp.text, place_id)
            if not parsed:
                break

            fresh_reviews = []
            for r in parsed:
                rid = str(r["review_id"])
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                if self._suppressed(r.get("author_name")):
                    continue
                row = build_review_row(
                    r,
                    place_id,
                    run_id,
                    self._mode,
                    source_url=source_url,
                    key=self._key,
                )
                fresh_reviews.append(row)

            # Persist batch incrementally
            if fresh_reviews:
                n_inserted = self._persist_reviews_batch(fresh_reviews)
                saved_count += n_inserted
                self._checkpoint_store.save_checkpoint(
                    place_id=place_id,
                    token=next_token,
                    reviews_added=n_inserted,
                    status="in_progress" if next_token else "complete",
                    run_id=run_id,
                )

            if heartbeat:
                heartbeat({
                    "stage": "extracting_reviews",
                    "place_id": place_id,
                    "reviews_saved": saved_count,
                    "has_more": bool(next_token),
                })

            if not next_token or next_token == token:
                break
            token = next_token

            if self._delay_range[1] > 0:
                await asyncio.sleep(random.uniform(*self._delay_range))

        final_status = "complete" if not token else "partial"
        self._checkpoint_store.save_checkpoint(
            place_id=place_id,
            token=token,
            reviews_added=0,
            status=final_status,
            run_id=run_id,
        )

        return {
            "place_id": place_id,
            "reviews_saved": saved_count,
            "total_extracted": already_extracted + saved_count,
            "status": final_status,
        }

    def _lookup_ftid(self, place_id: str) -> Optional[str]:
        conn = self._get_conn()
        if not conn:
            return None
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ftid FROM staging_dataextraction.place_details WHERE place_id = %s",
                    (place_id,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    return row[0]
                cur.execute(
                    "SELECT raw_payload->>'ftid' FROM staging_dataextraction.staging_companies WHERE raw_payload->>'cid' = %s LIMIT 1",
                    (place_id,),
                )
                row2 = cur.fetchone()
                return row2[0] if (row2 and row2[0]) else None
        except Exception:
            return None
        finally:
            self._release_conn(conn)

    def _persist_reviews_batch(self, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        conn = self._get_conn()
        if not conn:
            return 0
        try:
            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                query = """
                INSERT INTO staging_dataextraction.place_reviews (
                    place_id, review_id, reviewer_name, reviewer_name_hash, reviewer_id,
                    rating, review_text, language, published_at, relative_date,
                    owner_response_text, owner_response_date, reaction_count, photo_urls,
                    source, source_url, run_id, scraped_at
                ) VALUES %s
                ON CONFLICT (place_id, review_id) DO UPDATE SET
                    rating = COALESCE(EXCLUDED.rating, staging_dataextraction.place_reviews.rating),
                    review_text = COALESCE(EXCLUDED.review_text, staging_dataextraction.place_reviews.review_text),
                    owner_response_text = COALESCE(EXCLUDED.owner_response_text, staging_dataextraction.place_reviews.owner_response_text),
                    owner_response_date = COALESCE(EXCLUDED.owner_response_date, staging_dataextraction.place_reviews.owner_response_date),
                    reaction_count = GREATEST(EXCLUDED.reaction_count, staging_dataextraction.place_reviews.reaction_count)
                """
                tuples = [
                    (
                        r["place_id"],
                        r["review_id"],
                        r.get("reviewer_name"),
                        r.get("reviewer_name_hash"),
                        r.get("reviewer_id"),
                        r.get("rating"),
                        r.get("review_text"),
                        r.get("language"),
                        r.get("published_at"),
                        r.get("relative_date"),
                        r.get("owner_response_text"),
                        r.get("owner_response_date"),
                        r.get("reaction_count", 0),
                        r.get("photo_urls", "[]"),
                        r.get("source", "GOOGLE_MAPS"),
                        r.get("source_url"),
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
            logger.error("Failed to insert reviews batch: %s", exc)
            return 0
        finally:
            self._release_conn(conn)
