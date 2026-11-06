"""
DataExtraction Enterprise — SOC-2 Type II Access Audit Trail Repository
Records immutable audit logs of all PII access, export, query, and compliance operations.
"""

import json
import logging
import sys
import uuid
from typing import Any, Dict, List, Optional
from packages.infrastructure.db_connector import get_connection, release_connection, DATABASE_TYPE

logger = logging.getLogger("dataextraction.audit")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [AUDIT] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


class AuditTrailRepository:
    """Enterprise repository persisting immutable access and mutation records."""

    @staticmethod
    def record_access_event(
        user_id: str,
        user_email: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        status_code: int = 200,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Records an audit event into kg_audit.access_logs.
        Returns the generated event UUID string.
        """
        event_id = str(uuid.uuid4())
        meta_json = json.dumps(metadata or {})
        conn = get_connection()

        try:
            cur = conn.cursor()
            if DATABASE_TYPE == "postgresql":
                cur.execute(
                    """
                    INSERT INTO kg_audit.access_logs (
                        log_id, timestamp, user_id, user_email, action,
                        resource_type, resource_id, ip_address, user_agent,
                        status_code, metadata
                    )
                    VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        event_id,
                        user_id,
                        user_email,
                        action,
                        resource_type,
                        resource_id,
                        ip_address,
                        (user_agent or "")[:500],
                        status_code,
                        meta_json,
                    ),
                )
            else:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS access_logs (
                        log_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                        user_id TEXT NOT NULL,
                        user_email TEXT NOT NULL,
                        action TEXT NOT NULL,
                        resource_type TEXT NOT NULL,
                        resource_id TEXT,
                        ip_address TEXT,
                        user_agent TEXT,
                        status_code INTEGER DEFAULT 200,
                        metadata TEXT DEFAULT '{}'
                    );
                    """
                )
                cur.execute(
                    """
                    INSERT INTO access_logs (
                        log_id, user_id, user_email, action,
                        resource_type, resource_id, ip_address, user_agent,
                        status_code, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        user_id,
                        user_email,
                        action,
                        resource_type,
                        resource_id,
                        ip_address,
                        user_agent,
                        status_code,
                        meta_json,
                    ),
                )
            conn.commit()
            cur.close()
            logger.debug("Recorded audit event %s for user %s: action=%s resource=%s",
                         event_id, user_email, action, resource_type)
            return event_id
        except Exception as exc:
            logger.error("Failed to persist access audit log: %s", exc)
            if hasattr(conn, "rollback"):
                try:
                    conn.rollback()
                except Exception:
                    pass
            return event_id
        finally:
            release_connection(conn)

    @staticmethod
    def query_access_logs(
        limit: int = 50,
        offset: int = 0,
        action: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Queries recent audit logs for compliance review and security auditing."""
        conn = get_connection()
        logs: List[Dict[str, Any]] = []

        try:
            cur = conn.cursor()
            table_name = "kg_audit.access_logs" if DATABASE_TYPE == "postgresql" else "access_logs"
            conditions = []
            params: List[Any] = []

            if action:
                conditions.append("action = %s" if DATABASE_TYPE == "postgresql" else "action = ?")
                params.append(action)
            if user_id:
                conditions.append("user_id = %s" if DATABASE_TYPE == "postgresql" else "user_id = ?")
                params.append(user_id)

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""
                SELECT log_id, timestamp, user_id, user_email, action,
                       resource_type, resource_id, ip_address, user_agent,
                       status_code, metadata
                FROM {table_name}
                {where_clause}
                ORDER BY timestamp DESC
                LIMIT {limit} OFFSET {offset}
            """
            cur.execute(query, tuple(params))
            for row in cur.fetchall():
                logs.append({
                    "log_id": str(row[0]),
                    "timestamp": str(row[1]),
                    "user_id": row[2],
                    "user_email": row[3],
                    "action": row[4],
                    "resource_type": row[5],
                    "resource_id": row[6],
                    "ip_address": row[7],
                    "user_agent": row[8],
                    "status_code": row[9],
                    "metadata": row[10] if isinstance(row[10], dict) else json.loads(row[10] or "{}"),
                })
            cur.close()
        except Exception as exc:
            logger.error("Failed to query access logs: %s", exc)
        finally:
            release_connection(conn)

        return logs

