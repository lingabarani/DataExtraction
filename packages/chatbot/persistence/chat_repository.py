"""
Chat Repository for sessions, messages, and execution runs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from packages.infrastructure.db_connector import get_db_cursor

logger = logging.getLogger("dataextraction.chatbot.chat_repo")


class ChatRepository:
    def create_session(
        self,
        user_id: str = "anonymous",
        title: str = "New Conversation",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session_id = str(uuid4())
        ctx_json = json.dumps(context or {})
        sql = """
            INSERT INTO chat_dataextraction.chat_sessions (id, user_id, title, context)
            VALUES (%s, %s, %s, %s::jsonb)
            RETURNING id::text, user_id, title, context, created_at, updated_at;
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, (session_id, user_id, title, ctx_json))
            row = cur.fetchone()
            conn.commit()
            return {
                "id": str(row[0]),
                "user_id": row[1],
                "title": row[2],
                "context": row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}"),
                "created_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                "updated_at": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
            }

    def get_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        sql = """
            SELECT id::text, user_id, title, context, created_at, updated_at
            FROM chat_dataextraction.chat_sessions
            WHERE id = %s
        """
        params: List[Any] = [session_id]
        if user_id and user_id != "admin":
            sql += " AND user_id = %s"
            params.append(user_id)

        with get_db_cursor() as (conn, cur):
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": str(row[0]),
                "user_id": row[1],
                "title": row[2],
                "context": row[3] if isinstance(row[3], dict) else json.loads(row[3] or "{}"),
                "created_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                "updated_at": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
            }

    def list_sessions(self, user_id: str = "anonymous", limit: int = 50) -> List[Dict[str, Any]]:
        sql = """
            SELECT id::text, user_id, title, context, created_at, updated_at
            FROM chat_dataextraction.chat_sessions
        """
        params: List[Any] = []
        if user_id and user_id != "admin":
            sql += " WHERE user_id = %s"
            params.append(user_id)
        sql += " ORDER BY updated_at DESC LIMIT %s"
        params.append(limit)

        with get_db_cursor() as (conn, cur):
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "user_id": r[1],
                    "title": r[2],
                    "context": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"),
                    "created_at": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
                    "updated_at": r[5].isoformat() if hasattr(r[5], "isoformat") else str(r[5]),
                }
                for r in rows
            ]

    def update_session_context(
        self,
        session_id: str,
        context: Dict[str, Any],
        title: Optional[str] = None,
    ) -> None:
        ctx_json = json.dumps(context)
        if title:
            sql = """
                UPDATE chat_dataextraction.chat_sessions
                SET context = %s::jsonb, title = %s, updated_at = NOW()
                WHERE id = %s;
            """
            params = (ctx_json, title, session_id)
        else:
            sql = """
                UPDATE chat_dataextraction.chat_sessions
                SET context = %s::jsonb, updated_at = NOW()
                WHERE id = %s;
            """
            params = (ctx_json, session_id)

        with get_db_cursor() as (conn, cur):
            cur.execute(sql, params)
            conn.commit()

    def delete_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        sql = "DELETE FROM chat_dataextraction.chat_sessions WHERE id = %s"
        params: List[Any] = [session_id]
        if user_id and user_id != "admin":
            sql += " AND user_id = %s"
            params.append(user_id)
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, tuple(params))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        structured_plan: Optional[Dict[str, Any]] = None,
        completeness_report: Optional[Dict[str, Any]] = None,
        results_summary: Optional[Dict[str, Any]] = None,
        search_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        msg_id = str(uuid4())
        sql = """
            INSERT INTO chat_dataextraction.chat_messages
                (id, session_id, role, content, structured_plan, completeness_report, results_summary, search_run_id)
            VALUES
                (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
            RETURNING id::text, session_id::text, role, content, structured_plan, completeness_report, results_summary, created_at;
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(
                sql,
                (
                    msg_id,
                    session_id,
                    role,
                    content,
                    json.dumps(structured_plan) if structured_plan else None,
                    json.dumps(completeness_report) if completeness_report else None,
                    json.dumps(results_summary) if results_summary else None,
                    search_run_id,
                ),
            )
            row = cur.fetchone()
            # Also touch session updated_at
            cur.execute("UPDATE chat_dataextraction.chat_sessions SET updated_at = NOW() WHERE id = %s", (session_id,))
            conn.commit()
            return {
                "id": str(row[0]),
                "session_id": str(row[1]),
                "role": row[2],
                "content": row[3],
                "structured_plan": row[4] if isinstance(row[4], dict) else (json.loads(row[4]) if row[4] else None),
                "completeness_report": row[5] if isinstance(row[5], dict) else (json.loads(row[5]) if row[5] else None),
                "results_summary": row[6] if isinstance(row[6], dict) else (json.loads(row[6]) if row[6] else None),
                "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
            }

    def list_messages(self, session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        sql = """
            SELECT id::text, session_id::text, role, content, structured_plan, completeness_report, results_summary, created_at
            FROM chat_dataextraction.chat_messages
            WHERE session_id = %s
            ORDER BY created_at ASC
            LIMIT %s;
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, (session_id, limit))
            rows = cur.fetchall()
            return [
                {
                    "id": str(r[0]),
                    "session_id": str(r[1]),
                    "role": r[2],
                    "content": r[3],
                    "structured_plan": r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else None),
                    "completeness_report": r[5] if isinstance(r[5], dict) else (json.loads(r[5]) if r[5] else None),
                    "results_summary": r[6] if isinstance(r[6], dict) else (json.loads(r[6]) if r[6] else None),
                    "created_at": r[7].isoformat() if hasattr(r[7], "isoformat") else str(r[7]),
                }
                for r in rows
            ]

    def create_execution_run(
        self,
        session_id: str,
        message_id: Optional[str],
        run_type: str,
        plan: Dict[str, Any],
    ) -> str:
        run_id = str(uuid4())
        sql = """
            INSERT INTO chat_dataextraction.chat_execution_runs
                (id, session_id, message_id, run_type, status, plan)
            VALUES
                (%s, %s, %s, %s, 'running', %s::jsonb);
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(sql, (run_id, session_id, message_id, run_type, json.dumps(plan)))
            conn.commit()
            return run_id

    def update_execution_run(
        self,
        run_id: str,
        status: str,
        db_matches_count: int = 0,
        discovered_matches_count: int = 0,
        timings: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        sql = """
            UPDATE chat_dataextraction.chat_execution_runs
            SET status = %s,
                db_matches_count = %s,
                discovered_matches_count = %s,
                timings = %s::jsonb,
                error_message = %s,
                finished_at = NOW()
            WHERE id = %s;
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(
                sql,
                (
                    status,
                    db_matches_count,
                    discovered_matches_count,
                    json.dumps(timings or {}),
                    error_message,
                    run_id,
                ),
            )
            conn.commit()
