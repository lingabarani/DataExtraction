"""
OneExtraction — Dead-Letter Queue (DLQ) & Pipeline Health Router
Endpoints:
  GET  /api/dlq/stats         — Aggregated DLQ status breakdown and metrics
  GET  /api/dlq/records       — Paginated dead-letter records with status filters
  POST /api/dlq/replay/{id}   — Replay a specific dead-letter record
  POST /api/dlq/discard/{id}  — Manually discard a dead-letter record
  GET  /api/pipeline/health   — System and database pool telemetry
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.deps import UserPrincipal, get_current_user
from db_connector import get_connection, release_connection
from dead_letter_queue import (
    get_dead_letter_records,
    get_dead_letter_stats,
    replay_dead_letter,
    discard_dead_letter,
    drain_fallback_to_db,
)
from config_manager import config_manager
from structured_logger import get_pipeline_health_metrics

logger = logging.getLogger("oneextraction.dlq_router")

router = APIRouter(prefix="/dlq", tags=["dlq"])


class ReplayRequest(BaseModel):
    dry_run: bool = False


@router.get("/stats")
def get_stats(user: UserPrincipal = Depends(get_current_user)):
    """Returns aggregated DLQ metrics and status breakdown."""
    conn = get_connection()
    try:
        stats = get_dead_letter_stats(conn)
        pending = stats.get("pending_count", 0)
        threshold = int(config_manager.get("DLQ_ALERT_THRESHOLD", 100))
        stats["alert_threshold"] = threshold
        stats["alert_triggered"] = pending > threshold
        if pending > threshold:
            logger.warning("DLQ backpressure alert: %d pending records exceed threshold %d", pending, threshold)
        return stats
    finally:
        release_connection(conn)


@router.get("/records")
def list_records(
    source: Optional[str] = Query(None),
    status_filter: str = Query("PENDING", alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: UserPrincipal = Depends(get_current_user),
):
    """Retrieves paginated dead-letter failure records."""
    conn = get_connection()
    try:
        records = get_dead_letter_records(
            conn=conn,
            source_name=source,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
        return {
            "records": records,
            "count": len(records),
            "limit": limit,
            "offset": offset,
        }
    finally:
        release_connection(conn)


@router.post("/replay/{record_id}")
def replay_record(
    record_id: int,
    body: ReplayRequest = ReplayRequest(),
    user: UserPrincipal = Depends(get_current_user),
):
    """Replays a specific dead-letter record through the ingestion pipeline."""
    conn = get_connection()
    try:
        def default_processor(payload):
            # Sample default processor: checks payload validity
            if isinstance(payload, dict) and (payload.get("name") or payload.get("company_name")):
                return True
            return False

        res = replay_dead_letter(
            conn=conn,
            dlq_id=record_id,
            processor_func=default_processor,
            dry_run=body.dry_run,
        )
        if not res.get("success") and not body.dry_run and res.get("error") == f"DLQ record {record_id} not found":
            raise HTTPException(status_code=404, detail=f"DLQ record {record_id} not found")
        return res
    finally:
        release_connection(conn)


@router.post("/discard/{record_id}")
def discard_record(
    record_id: int,
    reason: str = Query("Manually discarded by admin"),
    user: UserPrincipal = Depends(get_current_user),
):
    """Discards a dead-letter record."""
    conn = get_connection()
    try:
        ok = discard_dead_letter(conn, record_id, reason=reason)
        if not ok:
            raise HTTPException(status_code=400, detail="Failed to discard record")
        return {"status": "DISCARDED", "record_id": record_id}
    finally:
        release_connection(conn)


@router.post("/drain-fallback")
def drain_fallback(user: UserPrincipal = Depends(get_current_user)):
    """
    Drains locally buffered dead-letter records from disk fallback log
    into the primary PostgreSQL dead_letter_queue table after database recovery.
    """
    conn = get_connection()
    try:
        res = drain_fallback_to_db(conn)
        return res
    finally:
        release_connection(conn)


# Mount health check under /pipeline/health
health_router = APIRouter(prefix="/pipeline", tags=["pipeline"])

@health_router.get("/health")
def pipeline_health(user: UserPrincipal = Depends(get_current_user)):
    """Returns pipeline system health and connection pool telemetry."""
    return get_pipeline_health_metrics()
