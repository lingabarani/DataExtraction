"""
Encrypted API key store backed by PostgreSQL (ops_dataextraction.api_keys).

All SQL is parameterized. Values are Fernet-encrypted; only `last4` is kept in
clear for display. This class is the only place that touches the table.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from packages.infrastructure.key_vault import crypto
from packages.infrastructure.log_redaction import mask

logger = logging.getLogger("dataextraction.secrets.store")

VALID_STATUSES = ("active", "disabled", "invalid", "expired")


@dataclass
class KeyRecord:
    """A usable credential. `value` is plaintext and must never be logged."""
    id: str
    provider: str
    value: str
    label: str = ""
    priority: int = 100
    source: str = "db"            # db | aws | env
    last_used_at: Optional[datetime] = None

    def __repr__(self) -> str:  # never leak the value through repr()
        return f"KeyRecord(id={self.id!r}, provider={self.provider!r}, label={self.label!r}, value={mask(self.value)!r})"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DbKeyStore:
    """Persistence for API keys. `conn_factory` yields (conn, cursor) context managers."""

    def __init__(self, cursor_ctx=None):
        if cursor_ctx is None:
            from packages.infrastructure.db_connector import get_db_cursor
            cursor_ctx = get_db_cursor
        self._cursor_ctx = cursor_ctx

    # ── reads ────────────────────────────────────────────────────────────────
    def usable_keys(self, provider: str) -> List[KeyRecord]:
        """Active, non-expired, not-in-cooldown keys, decrypted."""
        sql = """
            SELECT id::text, provider, ciphertext, label, priority, last_used_at
            FROM ops_dataextraction.api_keys
            WHERE provider = %s
              AND status = 'active'
              AND (expires_at IS NULL OR expires_at > NOW())
              AND (cooldown_until IS NULL OR cooldown_until <= NOW())
            ORDER BY priority ASC, last_used_at ASC NULLS FIRST
        """
        out: List[KeyRecord] = []
        with self._cursor_ctx() as (_conn, cur):
            cur.execute(sql, (provider,))
            rows = cur.fetchall()
        for row in rows:
            try:
                value = crypto.decrypt(row[2])
            except Exception as exc:
                logger.error("Skipping undecryptable key %s: %s", row[0], exc)
                continue
            out.append(KeyRecord(id=row[0], provider=row[1], value=value, label=row[3] or "",
                                 priority=row[4], source="db", last_used_at=row[5]))
        return out

    def list_keys(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Masked listing. Never returns ciphertext or plaintext."""
        sql = """
            SELECT id::text, provider, label, last4, status, priority, expires_at,
                   cooldown_until, fail_count, last_used_at, created_by, created_at
            FROM ops_dataextraction.api_keys
            {where}
            ORDER BY provider, priority, created_at
        """
        where, params = ("WHERE provider = %s", (provider,)) if provider else ("", ())
        with self._cursor_ctx() as (_conn, cur):
            cur.execute(sql.format(where=where), params)
            rows = cur.fetchall()
        cols = ("id", "provider", "label", "last4", "status", "priority", "expires_at",
                "cooldown_until", "fail_count", "last_used_at", "created_by", "created_at")
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            d["masked"] = "****" + (d["last4"] or "")
            result.append(d)
        return result

    # ── writes ───────────────────────────────────────────────────────────────
    def add_key(self, provider: str, value: str, label: str = "", priority: int = 100,
                expires_at: Optional[datetime] = None, created_by: Optional[str] = None) -> str:
        if not value or not value.strip():
            raise ValueError("API key value is empty")
        value = value.strip()
        ciphertext = crypto.encrypt(value)
        sql = """
            INSERT INTO ops_dataextraction.api_keys
                (provider, label, ciphertext, last4, priority, expires_at, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id::text
        """
        with self._cursor_ctx() as (_conn, cur):
            cur.execute(sql, (provider, label, ciphertext, value[-4:], priority, expires_at, created_by))
            return cur.fetchone()[0]

    def update_key(self, key_id: str, *, status: Optional[str] = None, priority: Optional[int] = None,
                   expires_at: Optional[datetime] = None, clear_expiry: bool = False) -> bool:
        sets: List[str] = []
        params: List[Any] = []
        if status is not None:
            if status not in VALID_STATUSES:
                raise ValueError(f"status must be one of {VALID_STATUSES}")
            sets.append("status = %s")
            params.append(status)
            if status == "active":
                sets.append("fail_count = 0")
                sets.append("cooldown_until = NULL")
        if priority is not None:
            sets.append("priority = %s")
            params.append(priority)
        if clear_expiry:
            sets.append("expires_at = NULL")
        elif expires_at is not None:
            sets.append("expires_at = %s")
            params.append(expires_at)
        if not sets:
            return False
        sets.append("updated_at = NOW()")
        params.append(key_id)
        sql = "UPDATE ops_dataextraction.api_keys SET " + ", ".join(sets) + " WHERE id = %s::uuid"
        with self._cursor_ctx() as (_conn, cur):
            cur.execute(sql, tuple(params))
            return cur.rowcount > 0

    def delete_key(self, key_id: str) -> bool:
        with self._cursor_ctx() as (_conn, cur):
            cur.execute("DELETE FROM ops_dataextraction.api_keys WHERE id = %s::uuid", (key_id,))
            return cur.rowcount > 0

    def get_key(self, key_id: str) -> Optional[KeyRecord]:
        with self._cursor_ctx() as (_conn, cur):
            cur.execute(
                "SELECT id::text, provider, ciphertext, label, priority, last_used_at "
                "FROM ops_dataextraction.api_keys WHERE id = %s::uuid", (key_id,))
            row = cur.fetchone()
        if not row:
            return None
        return KeyRecord(id=row[0], provider=row[1], value=crypto.decrypt(row[2]), label=row[3] or "",
                         priority=row[4], source="db", last_used_at=row[5])

    def mark_used(self, key_id: str) -> None:
        with self._cursor_ctx() as (_conn, cur):
            cur.execute("UPDATE ops_dataextraction.api_keys SET last_used_at = NOW() WHERE id = %s::uuid",
                        (key_id,))

    def mark_failed(self, key_id: str, status_code: Optional[int], cooldown_s: int) -> None:
        """401/403 -> invalid. 429 -> cooldown. Anything else only bumps the counter."""
        with self._cursor_ctx() as (_conn, cur):
            if status_code in (401, 403):
                cur.execute(
                    "UPDATE ops_dataextraction.api_keys SET status='invalid', fail_count=fail_count+1, "
                    "updated_at=NOW() WHERE id = %s::uuid", (key_id,))
            elif status_code == 429:
                until = _now() + timedelta(seconds=max(1, cooldown_s))
                cur.execute(
                    "UPDATE ops_dataextraction.api_keys SET cooldown_until=%s, fail_count=fail_count+1, "
                    "updated_at=NOW() WHERE id = %s::uuid", (until, key_id))
            else:
                cur.execute(
                    "UPDATE ops_dataextraction.api_keys SET fail_count=fail_count+1 WHERE id = %s::uuid",
                    (key_id,))
