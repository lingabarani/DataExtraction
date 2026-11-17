"""
Runs deep place extraction for a batch of places and stores the results.

Framework-free on purpose: Temporal activities, the API and tests all call
`run_deep_extraction()`. Network client, LLM and DB connection factory can be injected.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_GMAPS_SRC = Path(__file__).resolve().parent / "src"
if str(_GMAPS_SRC) not in sys.path:
    sys.path.insert(0, str(_GMAPS_SRC))

from packages.scrapers.google_maps.deep_place import DeepPlaceExtractor, reviewer_mode  # noqa: E402
from packages.scrapers.google_maps.deep_place_writer import (  # noqa: E402
    Suppressor, finish_run, save_bundle, start_run,
)

logger = logging.getLogger("dataextraction.gmaps.deep_runner")

Heartbeat = Callable[[Dict[str, Any]], None]


def select_stubs(conn: Any, request: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Resolve the places to extract from explicit ids or a region/category filter."""
    limit = max(1, min(int(request.get("limit") or 25), 500))
    place_ids = [str(p).removeprefix("gmaps_") for p in (request.get("place_ids") or []) if p]
    refresh_days = int(request.get("refresh_days") or os.getenv("PLACE_REFRESH_DAYS", "14"))

    sql = [
        "SELECT sc.id, sc.name, sc.website, sc.phone, sc.city, sc.state, sc.state_code, sc.zip_code,",
        "       sc.industry, sc.raw_payload",
        "FROM staging_dataextraction.staging_companies sc",
        "LEFT JOIN staging_dataextraction.place_details pd ON pd.place_id = sc.raw_payload->>'cid'",
        "WHERE sc.source = 'GOOGLE_MAPS' AND sc.raw_payload->>'cid' IS NOT NULL",
    ]
    params: List[Any] = []
    if place_ids:
        sql.append("AND sc.raw_payload->>'cid' = ANY(%s)")
        params.append(place_ids)
    else:
        sql.append("AND (pd.place_id IS NULL OR pd.scraped_at < NOW() - (%s || ' days')::interval)")
        params.append(str(refresh_days))
        region = (request.get("region") or "").upper().split("-")[-1]
        if region:
            sql.append("AND (UPPER(sc.state_code) = %s OR UPPER(sc.state) = %s)")
            params.extend([region, region])
        if request.get("category"):
            sql.append("AND sc.industry ILIKE %s")
            params.append(f"%{request['category']}%")
    sql.append("ORDER BY pd.scraped_at NULLS FIRST, sc.updated_at DESC LIMIT %s")
    params.append(limit)

    with conn.cursor() as cur:
        cur.execute("\n".join(sql), tuple(params))
        rows = cur.fetchall()

    stubs = []
    for (cid_row, name, website, phone, city, state, state_code, zip_code, industry, raw) in rows:
        raw = raw or {}
        stubs.append({
            "company_id": cid_row,
            "cid": str(raw.get("cid")),
            "ftid": raw.get("ftid"),
            "place_id": raw.get("place_id"),
            "name": name or raw.get("name"),
            "website": website,
            "phone": phone,
            "city": city or raw.get("city"),
            "region": state_code or state,
            "postal_code": zip_code or raw.get("postal_code"),
            "country_code": raw.get("country_code"),
            "address": raw.get("address"),
            "street_address": raw.get("street_address"),
            "latitude": raw.get("latitude"),
            "longitude": raw.get("longitude"),
            "category": industry or raw.get("category"),
            "rating": raw.get("rating"),
            "review_count": raw.get("review_count"),
        })
    return stubs


def _default_conn_factory():
    from packages.infrastructure.db_connector import get_connection, release_connection
    return get_connection, release_connection


async def run_deep_extraction(
    request: Dict[str, Any],
    *,
    http_client: Any = None,
    llm: Any = None,
    get_conn: Optional[Callable[[], Any]] = None,
    release_conn: Optional[Callable[[Any], None]] = None,
    heartbeat: Optional[Heartbeat] = None,
    delay_range: Optional[tuple] = None,
    crawler: Any = None,
) -> Dict[str, Any]:
    """
    request keys: place_ids | region+category, limit, run_id, with_llm, max_reviews, dry_run.
    Returns a summary dict. Never raises for per-place failures.
    """
    run_id = str(request.get("run_id") or f"deep_{int(time.time())}_{uuid.uuid4().hex[:6]}")
    if get_conn is None:
        get_conn, release_conn = _default_conn_factory()
    release_conn = release_conn or (lambda c: None)
    hb = heartbeat or (lambda _p: None)
    delay = delay_range if delay_range is not None else (
        float(os.getenv("PLACE_DELAY_MIN_SECONDS", "1.0")), float(os.getenv("PLACE_DELAY_MAX_SECONDS", "3.0")))

    mode = reviewer_mode()  # validates env early
    summary: Dict[str, Any] = {
        "run_id": run_id, "status": "complete", "places_requested": 0, "places_done": 0,
        "places_blocked": 0, "places_failed": 0, "reviews_saved": 0, "contacts_saved": 0,
        "people_saved": 0, "services_saved": 0, "reviewer_mode": mode, "notes": [],
    }

    conn = get_conn()
    try:
        stubs = await asyncio.to_thread(select_stubs, conn, request)
        summary["places_requested"] = len(stubs)
        if request.get("dry_run"):
            summary["status"] = "dry_run"
            summary["place_ids"] = [s["cid"] for s in stubs]
            release_conn(conn)
            return summary
        await asyncio.to_thread(start_run, conn, run_id, {k: v for k, v in request.items() if k != "run_id"})
        conn.commit()
        suppressor = await asyncio.to_thread(Suppressor.load, conn)
        conn.commit()
    except Exception:
        release_conn(conn)
        raise

    own_http = http_client is None
    if own_http:
        from gmaps_scraper.config import load_config
        from gmaps_scraper.http import HttpClient
        http_client = HttpClient(load_config())

    if llm is None and request.get("with_llm", True):
        try:
            from packages.infrastructure.llm import get_llm
            llm = get_llm()
        except Exception as exc:
            summary["notes"].append(f"llm disabled: {type(exc).__name__}")

    extractor = DeepPlaceExtractor(
        http_client, run_id=run_id, mode=mode, llm=llm, crawler=crawler, suppressed=suppressor,
        max_reviews=request.get("max_reviews"),
    )

    try:
        for idx, stub in enumerate(stubs, 1):
            hb({"stage": "extracting", "run_id": run_id, "done": idx - 1, "total": len(stubs),
                "place": stub.get("name")})
            try:
                bundle = await extractor.extract_place(stub)
                if bundle.status == "blocked" and not bundle.reviews and not bundle.details:
                    summary["places_blocked"] += 1
                    summary["status"] = "blocked"
                    summary["notes"].append(f"blocked at place {stub['cid']}; stopping run")
                    # Record the blocked place so the state is visible, then stop hammering Google.
                    await asyncio.to_thread(save_bundle, conn, bundle, stub, run_id)
                    conn.commit()
                    break
                counts = await asyncio.to_thread(save_bundle, conn, bundle, stub, run_id)
                conn.commit()
                summary["places_done"] += 1
                summary["reviews_saved"] += counts["reviews"]
                summary["contacts_saved"] += counts["contacts"]
                summary["people_saved"] += counts["people"]
                summary["services_saved"] += counts["services"]
                if bundle.status == "partial":
                    summary["status"] = "partial" if summary["status"] == "complete" else summary["status"]
                if bundle.notes:
                    summary["notes"].extend(f"{stub['cid']}: {n}" for n in bundle.notes[:3])
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    pass
                summary["places_failed"] += 1
                summary["notes"].append(f"{stub.get('cid')}: {type(exc).__name__}: {str(exc)[:120]}")
                logger.warning("Deep extraction failed for %s: %s", stub.get("cid"), exc)
            if idx < len(stubs) and delay[1] > 0:
                await asyncio.sleep(random.uniform(*delay))
        if summary["places_failed"] and summary["status"] == "complete":
            summary["status"] = "partial"
        finish_status = summary["status"]
        await asyncio.to_thread(finish_run, conn, run_id, finish_status, summary["places_done"],
                                summary["reviews_saved"], "; ".join(summary["notes"][:5]) or None)
        conn.commit()
    finally:
        if own_http:
            try:
                await http_client.close()
            except Exception:
                pass
        release_conn(conn)
    summary["notes"] = summary["notes"][:20]
    return summary
