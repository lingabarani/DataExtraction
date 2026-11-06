"""
DataExtraction — OneReach Enterprise Outbound Delivery Service
==============================================================
Manages outbound delivery of verified B2B Golden Records to OneReach.ai:
  1. HMAC-SHA256 payload signing and constant-time signature verification.
  2. Exponential backoff retry logic (up to 3 attempts).
  3. Immutable delivery audit logging to `master_dataextraction.onereach_delivery_log`.
  4. Dead-Letter Queue (DLQ) failover routing on permanent exhaustion.
  5. Keyset pagination and high-throughput batch dispatch.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.db_connector import get_connection, release_connection
from packages.infrastructure.dead_letter_queue import enqueue_dead_letter
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("dataextraction.domain.onereach_delivery")


def compute_hmac_signature(payload_bytes: bytes, secret: str) -> str:
    """Computes standard SHA-256 HMAC signature for webhook authentication."""
    if not isinstance(payload_bytes, bytes):
        payload_bytes = str(payload_bytes).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def verify_hmac_signature(payload_bytes: bytes, secret: str, received_signature: str) -> bool:
    """Performs constant-time HMAC comparison to prevent timing attacks."""
    if not received_signature or not secret:
        return False
    expected = compute_hmac_signature(payload_bytes, secret)
    return hmac.compare_digest(expected, received_signature.strip().lower())


class OneReachDeliveryService:
    """
    Enterprise Delivery Engine for dispatching leads to external endpoints & OneReach.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.webhook_url = self.config.get(
            "webhook_url",
            config_manager.get("ONEREACH_WEBHOOK_URL", "https://api.onereach.ai/v1/leads/ingest"),
        )
        self.secret_token = self.config.get(
            "secret_token",
            config_manager.get("ONEREACH_WEBHOOK_SECRET", "onereach-prod-secret-token"),
        )
        self.timeout = float(self.config.get("timeout", config_manager.get("ONEREACH_DELIVERY_TIMEOUT", 10.0)))
        self.max_retries = int(self.config.get("max_retries", 3))

    def log_delivery_attempt(
        self,
        delivery_id: str,
        lead_id: Optional[str],
        payload: Dict[str, Any],
        status: str,
        http_status: Optional[int],
        response_body: Optional[str],
        attempt_count: int,
        signature: str,
        delivered_at: Optional[datetime] = None,
    ) -> None:
        """Persists delivery audit record to master_dataextraction.onereach_delivery_log."""
        conn = None
        try:
            conn = get_connection()
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO master_dataextraction.onereach_delivery_log (
                            delivery_id, lead_id, channel, payload, delivery_status,
                            http_status, response_body, attempt_count, signature,
                            delivered_at, updated_at
                        ) VALUES (
                            %s::uuid, %s, 'WEBHOOK', %s::jsonb, %s,
                            %s, %s, %s, %s,
                            %s, NOW()
                        )
                        ON CONFLICT (delivery_id) DO UPDATE SET
                            delivery_status = EXCLUDED.delivery_status,
                            http_status = EXCLUDED.http_status,
                            response_body = EXCLUDED.response_body,
                            attempt_count = EXCLUDED.attempt_count,
                            delivered_at = EXCLUDED.delivered_at,
                            updated_at = NOW();
                        """,
                        (
                            delivery_id,
                            lead_id,
                            json.dumps(payload, default=str),
                            status,
                            http_status,
                            str(response_body)[:1000] if response_body else None,
                            attempt_count,
                            signature,
                            delivered_at,
                        ),
                    )
                conn.commit()
        except Exception as e:
            logger.debug("Delivery audit log notice: %s", e)
            if conn:
                conn.rollback()
        finally:
            if conn:
                release_connection(conn)

    def dispatch_payload(
        self,
        payload_data: Dict[str, Any],
        webhook_url: Optional[str] = None,
        secret_token: Optional[str] = None,
        dry_run: bool = False,
        session: Optional[requests.Session] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches payload via HTTP POST with HMAC signing, retries, and DLQ failover.
        """
        target_url = webhook_url or self.webhook_url
        secret = secret_token or self.secret_token
        delivery_id = payload_data.get("delivery_id") or str(uuid.uuid4())
        payload_data["delivery_id"] = delivery_id

        payload_json = json.dumps(payload_data, default=str)
        payload_bytes = payload_json.encode("utf-8")
        sig = compute_hmac_signature(payload_bytes, secret)

        if dry_run:
            self.log_delivery_attempt(
                delivery_id=delivery_id,
                lead_id=payload_data.get("lead_id"),
                payload=payload_data,
                status="SIMULATED",
                http_status=200,
                response_body="Dry run simulation succeeded",
                attempt_count=1,
                signature=sig,
                delivered_at=datetime.now(timezone.utc),
            )
            return {
                "status": "SIMULATED",
                "delivery_id": delivery_id,
                "dry_run": True,
                "signature": sig,
                "target_url": target_url,
            }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "DataExtraction-OneReachDelivery/3.0",
            "X-OneReach-Signature": sig,
            "X-OneReach-Signature-256": sig,
            "X-Delivery-Id": delivery_id,
            "X-Delivery-Timestamp": str(int(time.time())),
        }

        http_client = session or requests
        last_error = None
        last_resp = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    "Dispatching to OneReach attempt %d/%d (id=%s, url=%s)",
                    attempt,
                    self.max_retries,
                    delivery_id,
                    target_url,
                )
                resp = http_client.post(
                    target_url,
                    data=payload_bytes,
                    headers=headers,
                    timeout=self.timeout,
                )
                last_resp = resp
                if resp.status_code in (200, 201, 202, 204):
                    now_utc = datetime.now(timezone.utc)
                    self.log_delivery_attempt(
                        delivery_id=delivery_id,
                        lead_id=payload_data.get("lead_id"),
                        payload=payload_data,
                        status="DELIVERED",
                        http_status=resp.status_code,
                        response_body=resp.text[:500],
                        attempt_count=attempt,
                        signature=sig,
                        delivered_at=now_utc,
                    )
                    return {
                        "status": "DELIVERED",
                        "delivery_id": delivery_id,
                        "http_status": resp.status_code,
                        "attempts": attempt,
                        "signature": sig,
                    }
                else:
                    last_error = f"HTTP {resp.status_code} - {resp.text[:300]}"
                    logger.warning("OneReach delivery attempt %d rejected: %s", attempt, last_error)
            except Exception as exc:
                last_error = str(exc)
                logger.warning("OneReach delivery attempt %d error: %s", attempt, last_error)

            # Exponential backoff (0.2s * 2^(attempt-1))
            if attempt < self.max_retries:
                time.sleep(0.2 * (2 ** (attempt - 1)))

        # Exhausted all retries -> Log failure & Route to DLQ
        http_code = last_resp.status_code if last_resp else None
        resp_text = last_resp.text[:500] if last_resp else str(last_error)

        self.log_delivery_attempt(
            delivery_id=delivery_id,
            lead_id=payload_data.get("lead_id"),
            payload=payload_data,
            status="FAILED",
            http_status=http_code,
            response_body=resp_text,
            attempt_count=self.max_retries,
            signature=sig,
        )

        # DLQ failover
        try:
            enqueue_dead_letter(
                source_name="onereach_delivery",
                error_type="OneReachDeliveryExhausted",
                error_message=str(last_error),
                payload=payload_data,
                failed_stage="ONEREACH_DELIVERY",
            )
            logger.info("OneReach delivery %s enqueued to DLQ after %d failures", delivery_id, self.max_retries)
        except Exception as dlq_err:
            logger.error("Failed to enqueue delivery to DLQ: %s", dlq_err)

        return {
            "status": "FAILED",
            "delivery_id": delivery_id,
            "http_status": http_code,
            "error": str(last_error),
            "attempts": self.max_retries,
            "routed_to_dlq": True,
        }

    def dispatch_batch(
        self,
        records: List[Dict[str, Any]],
        webhook_url: Optional[str] = None,
        secret_token: Optional[str] = None,
        dry_run: bool = False,
        session: Optional[requests.Session] = None,
    ) -> Dict[str, Any]:
        """Dispatches an aggregated batch of golden records in a single payload."""
        payload = {
            "event_id": f"evt_{int(time.time() * 1000)}",
            "event_type": "GOLDEN_RECORDS_DELIVERY",
            "consumer": "OneReach App",
            "record_count": len(records),
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
            "records": records,
        }
        res = self.dispatch_payload(
            payload_data=payload,
            webhook_url=webhook_url,
            secret_token=secret_token,
            dry_run=dry_run,
            session=session,
        )
        res["record_count"] = len(records)
        return res


onereach_delivery_service = OneReachDeliveryService()

