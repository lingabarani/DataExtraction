"""
Review Repository for Staged Chatbot Discoveries.
Enforces non-destructive staging: newly discovered information remains PENDING
until explicit human approval.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from packages.infrastructure.db_connector import get_db_cursor

logger = logging.getLogger("dataextraction.chatbot.review_repo")


def _safe_json_load(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list, int, float, bool)):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return s
    return val


class ReviewRepository:
    def add_review_item(
        self,
        session_id: str,
        company_id: str,
        company_name: str,
        field_name: str,
        discovered_value: Any,
        source_type: str,
        source_url: Optional[str] = None,
        existing_value: Any = None,
        evidence: Optional[str] = None,
        field_confidence: float = 0.8,
        verification_status: str = "UNVERIFIED",
        conflict_details: Optional[Dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        item_id = str(uuid4())
        sql = """
            INSERT INTO chat_dataextraction.chat_review_items
                (id, session_id, run_id, company_id, company_name, field_name,
                 existing_value, discovered_value, source_url, source_type,
                 evidence, field_confidence, verification_status, conflict_details, review_status)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb, 'PENDING')
            RETURNING id::text, session_id::text, run_id::text, company_id, company_name, field_name,
                      existing_value, discovered_value, source_url, source_type, evidence,
                      field_confidence, verification_status, conflict_details, review_status, created_at;
        """
        with get_db_cursor() as (conn, cur):
            # Deduplication check: prevent duplicate PENDING review items for same company & field
            cur.execute(
                """
                SELECT id::text, session_id::text, run_id::text, company_id, company_name, field_name,
                       existing_value, discovered_value, source_url, source_type, evidence,
                       field_confidence, verification_status, conflict_details, review_status, created_at
                FROM chat_dataextraction.chat_review_items
                WHERE company_id = %s AND field_name = %s AND review_status = 'PENDING'
                LIMIT 1;
                """,
                (company_id, field_name),
            )
            existing = cur.fetchone()
            if existing:
                return {
                    "id": str(existing[0]),
                    "session_id": str(existing[1]),
                    "run_id": str(existing[2]) if existing[2] else None,
                    "company_id": existing[3],
                    "company_name": existing[4],
                    "field_name": existing[5],
                    "existing_value": _safe_json_load(existing[6]),
                    "discovered_value": _safe_json_load(existing[7]),
                    "source_url": existing[8],
                    "source_type": existing[9],
                    "evidence": existing[10],
                    "field_confidence": float(existing[11]) if existing[11] is not None else 0.8,
                    "verification_status": existing[12],
                    "conflict_details": _safe_json_load(existing[13]),
                    "review_status": existing[14],
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "rejection_reason": None,
                    "created_at": existing[15].isoformat() if hasattr(existing[15], "isoformat") else str(existing[15]),
                }

            cur.execute(
                sql,
                (
                    item_id,
                    session_id,
                    run_id,
                    company_id,
                    company_name,
                    field_name,
                    json.dumps(existing_value) if existing_value is not None else None,
                    json.dumps(discovered_value),
                    source_url,
                    source_type,
                    evidence,
                    field_confidence,
                    verification_status,
                    json.dumps(conflict_details) if conflict_details else None,
                ),
            )
            r = cur.fetchone()
            conn.commit()
            return {
                "id": str(r[0]),
                "session_id": str(r[1]),
                "run_id": str(r[2]) if r[2] else None,
                "company_id": r[3],
                "company_name": r[4],
                "field_name": r[5],
                "existing_value": _safe_json_load(r[6]),
                "discovered_value": _safe_json_load(r[7]),
                "source_url": r[8],
                "source_type": r[9],
                "evidence": r[10],
                "field_confidence": float(r[11]) if r[11] is not None else 0.8,
                "verification_status": r[12],
                "conflict_details": _safe_json_load(r[13]),
                "review_status": r[14],
                "reviewed_by": None,
                "reviewed_at": None,
                "rejection_reason": None,
                "created_at": r[15].isoformat() if hasattr(r[15], "isoformat") else str(r[15]),
            }

    def list_review_items(
        self,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        company_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        sql = """
            SELECT id::text, session_id::text, run_id::text, company_id, company_name, field_name,
                   existing_value, discovered_value, source_url, source_type, evidence,
                   field_confidence, verification_status, conflict_details, review_status,
                   reviewed_by, reviewed_at, rejection_reason, created_at
            FROM chat_dataextraction.chat_review_items
            WHERE 1=1
        """
        params: List[Any] = []
        if status:
            sql += " AND review_status = %s"
            params.append(status.upper())
        if session_id:
            sql += " AND session_id = %s"
            params.append(session_id)
        if company_id:
            sql += " AND company_id = %s"
            params.append(company_id)

        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s;"
        params += [limit, offset]

        with get_db_cursor() as (conn, cur):
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "session_id": str(r[1]),
                    "run_id": str(r[2]) if r[2] else None,
                    "company_id": r[3],
                    "company_name": r[4],
                    "field_name": r[5],
                    "existing_value": _safe_json_load(r[6]),
                    "discovered_value": _safe_json_load(r[7]),
                    "source_url": r[8],
                    "source_type": r[9],
                    "evidence": r[10],
                    "field_confidence": float(r[11]) if r[11] is not None else 0.8,
                    "verification_status": r[12],
                    "conflict_details": _safe_json_load(r[13]),
                    "review_status": r[14],
                    "reviewed_by": r[15],
                    "reviewed_at": r[16].isoformat() if r[16] and hasattr(r[16], "isoformat") else (str(r[16]) if r[16] else None),
                    "rejection_reason": r[17],
                    "created_at": r[18].isoformat() if hasattr(r[18], "isoformat") else str(r[18]),
                }
                for r in rows
            ]

    def get_review_item(self, review_id: str) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT id::text, session_id::text, run_id::text, company_id, company_name, field_name,
                   existing_value, discovered_value, source_url, source_type, evidence,
                   field_confidence, verification_status, conflict_details, review_status,
                   reviewed_by, reviewed_at, rejection_reason, created_at
            FROM chat_dataextraction.chat_review_items
            WHERE id = %s;
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, (review_id,))
            r = cur.fetchone()
            if not r:
                return None
            return {
                "id": str(r[0]),
                "session_id": str(r[1]),
                "run_id": str(r[2]) if r[2] else None,
                "company_id": r[3],
                "company_name": r[4],
                "field_name": r[5],
                "existing_value": _safe_json_load(r[6]),
                "discovered_value": _safe_json_load(r[7]),
                "source_url": r[8],
                "source_type": r[9],
                "evidence": r[10],
                "field_confidence": float(r[11]) if r[11] is not None else 0.8,
                "verification_status": r[12],
                "conflict_details": _safe_json_load(r[13]),
                "review_status": r[14],
                "reviewed_by": r[15],
                "reviewed_at": r[16].isoformat() if r[16] and hasattr(r[16], "isoformat") else (str(r[16]) if r[16] else None),
                "rejection_reason": r[17],
                "created_at": r[18].isoformat() if hasattr(r[18], "isoformat") else str(r[18]),
            }

    def approve_review_item(self, review_id: str, reviewer: str = "admin", notes: Optional[str] = None) -> bool:
        """
        Approves discovered item, updating review_status to APPROVED.
        Safely applies the approved field into the organization records.
        """
        item = self.get_review_item(review_id)
        if not item or item["review_status"] != "PENDING":
            return False

        sql_update_review = """
            UPDATE chat_dataextraction.chat_review_items
            SET review_status = 'APPROVED',
                reviewed_by = %s,
                reviewed_at = NOW()
            WHERE id = %s AND review_status = 'PENDING';
        """

        with get_db_cursor() as (conn, cur):
            cur.execute(sql_update_review, (reviewer, review_id))
            if cur.rowcount == 0:
                return False

            # Apply promotion into discovery organizations if ID is valid
            company_id = item["company_id"]
            field_name = item["field_name"]
            discovered_val = item["discovered_value"]

            try:
                # Update discovery_dataextraction.organizations if company matches UUID
                if field_name == "website" and isinstance(discovered_val, str):
                    cur.execute(
                        "UPDATE discovery_dataextraction.organizations SET website = %s WHERE id::text = %s",
                        (discovered_val, company_id),
                    )
                elif field_name == "domain" and isinstance(discovered_val, str):
                    cur.execute(
                        "UPDATE discovery_dataextraction.organizations SET domain = %s WHERE id::text = %s",
                        (discovered_val, company_id),
                    )
                elif field_name == "email":
                    email_str = discovered_val if isinstance(discovered_val, str) else str(discovered_val.get("value", ""))
                    if email_str:
                        cur.execute(
                            """
                            UPDATE discovery_dataextraction.organizations
                            SET emails = emails || %s::jsonb
                            WHERE id::text = %s;
                            """,
                            (json.dumps([{"value": email_str, "label": "verified", "source": item["source_type"]}]), company_id),
                        )
                elif field_name == "phone":
                    phone_str = discovered_val if isinstance(discovered_val, str) else str(discovered_val.get("number", ""))
                    if phone_str:
                        cur.execute(
                            """
                            UPDATE discovery_dataextraction.organizations
                            SET phones = phones || %s::jsonb
                            WHERE id::text = %s;
                            """,
                            (json.dumps([{"number": phone_str, "type": "work", "verified": True}]), company_id),
                        )
            except Exception as prom_err:
                logger.warning("Could not automatically promote approved field to organization %s: %s", company_id, prom_err)

            conn.commit()
            return True

    def reject_review_item(self, review_id: str, reviewer: str = "admin", reason: Optional[str] = None) -> bool:
        """
        Rejects discovered item without modifying canonical data.
        """
        sql = """
            UPDATE chat_dataextraction.chat_review_items
            SET review_status = 'REJECTED',
                reviewed_by = %s,
                reviewed_at = NOW(),
                rejection_reason = %s
            WHERE id = %s AND review_status = 'PENDING';
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, (reviewer, reason or "Rejected during human review", review_id))
            updated = cur.rowcount > 0
            conn.commit()
            return updated
