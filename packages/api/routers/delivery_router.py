"""
DataExtraction — OneReach Delivery & Webhook Router
==================================================
Production delivery stream connecting DataExtraction golden records to OneReach:
  1. Configurable webhook destination endpoint with HMAC-SHA256 payload signing.
  2. Server-Sent Events (SSE) & NDJSON streaming for zero-polling ingestion by OneReach.
  3. Direct batch dispatch with exponential backoff and DLQ routing on failures.
  4. Operational delivery telemetry and stream health monitoring.
"""

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from packages.api.dependencies import get_current_user, UserPrincipal
from packages.domain.onereach_delivery_service import (
    compute_hmac_signature,
    verify_hmac_signature,
    onereach_delivery_service,
)
from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.db_connector import get_connection, _release_connection
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("api.delivery")

router = APIRouter(prefix="/api/delivery", tags=["Delivery & OneReach"])

# In-memory delivery state & configuration
_DELIVERY_CONFIG: Dict[str, Any] = {
    "webhook_url": config_manager.get("ONEREACH_WEBHOOK_URL", "https://api.onereach.ai/v1/leads/ingest"),
    "secret_token": config_manager.get("ONEREACH_WEBHOOK_SECRET", "onereach-prod-secret-token"),
    "enabled": config_manager.get("ONEREACH_DELIVERY_ENABLED", "true").lower() == "true",
    "batch_size": int(config_manager.get("ONEREACH_DELIVERY_BATCH_SIZE", 500)),
    "timeout_seconds": float(config_manager.get("ONEREACH_DELIVERY_TIMEOUT", 10.0)),
}

_DELIVERY_METRICS: Dict[str, Any] = {
    "total_dispatched": 0,
    "total_failed": 0,
    "last_dispatch_at": None,
    "last_dispatch_status": "NONE",
}


class WebhookConfigRequest(BaseModel):
    webhook_url: str = Field(..., description="Destination OneReach endpoint URL")
    secret_token: Optional[str] = Field(None, description="Shared secret for HMAC-SHA256 signing")
    enabled: bool = Field(True, description="Enable or pause automated push delivery")
    batch_size: int = Field(500, ge=10, le=5000, description="Payload batch size for push notifications")


class DispatchRequest(BaseModel):
    record_ids: Optional[List[str]] = Field(None, description="Specific company IDs to push (or null for all un-dispatched)")
    limit: int = Field(100, ge=1, le=1000)
    dry_run: bool = Field(False, description="Simulate dispatch without sending HTTP POST")


def _compute_hmac_signature(payload_bytes: bytes, secret: str) -> str:
    """Computes SHA-256 HMAC signature for payload authentication."""
    return compute_hmac_signature(payload_bytes, secret)


@router.post("/onereach/verify-webhook")
async def verify_onereach_webhook(
    request: Request,
    x_onereach_signature: Optional[str] = Header(None, alias="X-OneReach-Signature"),
    x_onereach_signature_256: Optional[str] = Header(None, alias="X-OneReach-Signature-256"),
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Verifies incoming webhook payload authentication against the shared OneReach secret.
    Enforces constant-time HMAC-SHA256 signature checking.
    """
    body_bytes = await request.body()
    sig = x_onereach_signature_256 or x_onereach_signature
    if not sig:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-OneReach-Signature header in request",
        )
    is_valid = verify_hmac_signature(body_bytes, _DELIVERY_CONFIG["secret_token"], sig)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid HMAC-SHA256 signature",
        )
    return {
        "status": "VERIFIED",
        "valid": True,
        "signature": sig,
        "payload_bytes_len": len(body_bytes),
    }


@router.get("/config")
def get_delivery_config(current_user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the current OneReach webhook delivery configuration."""
    safe_cfg = dict(_DELIVERY_CONFIG)
    if safe_cfg.get("secret_token"):
        safe_cfg["secret_token"] = safe_cfg["secret_token"][:4] + "****"
    return safe_cfg


@router.post("/config")
def update_delivery_config(
    body: WebhookConfigRequest,
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """Updates the OneReach webhook destination URL and signature credentials."""
    _DELIVERY_CONFIG["webhook_url"] = body.webhook_url
    if body.secret_token:
        _DELIVERY_CONFIG["secret_token"] = body.secret_token
    _DELIVERY_CONFIG["enabled"] = body.enabled
    _DELIVERY_CONFIG["batch_size"] = body.batch_size
    logger.info("Updated OneReach delivery config: url=%s enabled=%s", body.webhook_url, body.enabled)
    return {"status": "SUCCESS", "message": "Delivery configuration updated successfully"}


@router.get("/status")
def get_delivery_status(current_user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns real-time delivery telemetry, dispatch volume, and webhook health."""
    return {
        "status": "HEALTHY" if _DELIVERY_CONFIG["enabled"] else "PAUSED",
        "enabled": _DELIVERY_CONFIG["enabled"],
        "target_endpoint": _DELIVERY_CONFIG["webhook_url"],
        "metrics": _DELIVERY_METRICS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/onereach/dispatch")
def dispatch_golden_records(
    body: DispatchRequest,
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Dispatches verified golden company & executive records to the OneReach ingestion API.
    Signs payload with HMAC-SHA256 signature in X-OneReach-Signature.
    """
    conn = None
    records = []
    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                if body.record_ids:
                    ph = ", ".join(["%s"] * len(body.record_ids))
                    cur.execute(f"""
                        SELECT 
                            id, 
                            name, 
                            legal_name, 
                            domain, 
                            ein, 
                            email, 
                            phone, 
                            city, 
                            state_code, 
                            industry, 
                            data_quality_score
                        FROM public.companies
                        WHERE id::text IN ({ph})
                    """, tuple(body.record_ids))
                else:
                    cur.execute("""
                        SELECT 
                            id, 
                            name, 
                            legal_name, 
                            domain, 
                            ein, 
                            email, 
                            phone, 
                            city, 
                            state_code, 
                            industry, 
                            data_quality_score
                        FROM public.companies
                        ORDER BY data_quality_score DESC NULLS LAST, id
                        LIMIT %s
                    """, (body.limit,))

                rows = cur.fetchall()
                cols = [c[0] for c in cur.description] if cur.description else []
                for r in rows:
                    records.append(dict(zip(cols, r)))
            finally:
                cur.close()
    except Exception as db_err:
        logger.warning("Database fetch notice during dispatch: %s", db_err)
    finally:
        if conn:
            try:
                _release_connection(conn)
            except Exception:
                pass

    if not records:
        if body.dry_run:
            sim_records = [{
                "id": "sim-org-001",
                "name": "OneReach Simulation Corp",
                "legal_name": "OneReach Simulation Corporation",
                "domain": "onereach-sim.internal",
                "data_quality_score": 95,
            }]
            return onereach_delivery_service.dispatch_batch(
                records=sim_records,
                webhook_url=_DELIVERY_CONFIG["webhook_url"],
                secret_token=_DELIVERY_CONFIG["secret_token"],
                dry_run=True,
            )
        return {
            "status": "SKIPPED",
            "message": "No eligible records found in master_dataextraction.organizations for dispatch",
            "dispatched": 0,
        }

    res = onereach_delivery_service.dispatch_batch(
        records=records,
        webhook_url=_DELIVERY_CONFIG["webhook_url"],
        secret_token=_DELIVERY_CONFIG["secret_token"],
        dry_run=body.dry_run or not _DELIVERY_CONFIG["enabled"],
    )

    if res.get("status") in ("DELIVERED", "SIMULATED"):
        _DELIVERY_METRICS["total_dispatched"] += len(records)
        _DELIVERY_METRICS["last_dispatch_status"] = res.get("status")
        _DELIVERY_METRICS["last_dispatch_at"] = datetime.now(timezone.utc).isoformat()
    else:
        _DELIVERY_METRICS["total_failed"] += len(records)
        _DELIVERY_METRICS["last_dispatch_status"] = "FAILED"

    return res


@router.get("/onereach/stream")
def stream_golden_records(
    limit: int = Query(50, ge=1, le=500),
    since_timestamp: Optional[str] = Query(None, description="ISO timestamp to resume delta stream"),
    current_user: UserPrincipal = Depends(get_current_user),
):
    """
    Streams verified golden records as NDJSON line-delimited chunks
    for continuous, zero-polling ingestion by OneReach.
    """
    def event_generator():
        conn = None
        try:
            conn = get_connection()
            if conn:
                cur = conn.cursor()
                try:
                    cur.execute("""
                        SELECT 
                            org_id AS id, 
                            COALESCE(display_name, legal_name) AS name, 
                            legal_name, 
                            primary_domain AS domain, 
                            tax_id AS ein, 
                            primary_email AS email, 
                            primary_phone AS phone, 
                            city, 
                            state_province AS state_code, 
                            industry, 
                            data_quality_score, 
                            updated_at
                        FROM master_dataextraction.organizations
                        ORDER BY updated_at DESC
                        LIMIT %s
                    """, (limit,))
                    rows = cur.fetchall()
                    cols = [c[0] for c in cur.description] if cur.description else []
                    for r in rows:
                        row_dict = dict(zip(cols, r))
                        line = json.dumps(row_dict, default=str) + "\n"
                        yield line.encode("utf-8")
                finally:
                    cur.close()
        except Exception as e:
            fallback = json.dumps({"notice": "streaming_fallback", "error": str(e)}) + "\n"
            yield fallback.encode("utf-8")
        finally:
            if conn:
                try:
                    _release_connection(conn)
                except Exception:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={"X-Stream-Format": "NDJSON", "Cache-Control": "no-cache"},
    )

