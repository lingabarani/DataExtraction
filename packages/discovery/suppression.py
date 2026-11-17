"""
Suppression Enforcement for Discovery Engine.
Checks identifiers (person names, emails, phones) against kg_audit.suppression_lists (GDPR/CCPA).
Suppressed records are never persisted, returned in SSE, or displayed in UI.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import List, Optional, Set

from packages.discovery.models import OrgRecord, PersonRecord
from packages.infrastructure.db_connector import get_connection, release_connection

logger = logging.getLogger("discovery.suppression")

_ACTIVE_HASHES: Set[str] = set()
_LAST_LOADED: float = 0.0
_TTL_SECONDS: float = 60.0


def hash_identifier(value: str) -> str:
    """Returns SHA-256 hex digest of stripped lowercase identifier."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def load_suppression_hashes(force: bool = False) -> Set[str]:
    """Loads active suppression hashes from kg_audit.suppression_lists with 60s TTL."""
    global _ACTIVE_HASHES, _LAST_LOADED
    now = time.monotonic()
    # An empty list is a valid cached result: without this check every call re-queried the database.
    if not force and _LAST_LOADED and (now - _LAST_LOADED < _TTL_SECONDS):
        return _ACTIVE_HASHES

    conn = None
    try:
        conn = get_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT hashed_identifier FROM kg_audit.suppression_lists WHERE is_active = true"
                )
                rows = cur.fetchall()
                _ACTIVE_HASHES = {str(r[0]).strip().lower() for r in rows if r[0]}
                _LAST_LOADED = now or 1e-9
    except Exception as exc:
        logger.debug("Failed to load suppression hashes: %s", exc)
    finally:
        if conn:
            release_connection(conn)
    return _ACTIVE_HASHES


def is_suppressed(val: Optional[str]) -> bool:
    """Returns True if identifier's sha256 hash or exact string is in active suppression list."""
    if not val or not val.strip():
        return False
    hashes = load_suppression_hashes()
    if not hashes:
        return False
    h = hash_identifier(val)
    return h in hashes or val.strip().lower() in hashes


def add_to_suppression_list(identifier: str, reason: str = "user_request") -> bool:
    """Adds an identifier to active suppression list in database and local cache."""
    h = hash_identifier(identifier)
    conn = None
    try:
        conn = get_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kg_audit.suppression_lists (hashed_identifier, identifier_type, reason, is_active)
                    VALUES (%s, %s, %s, true)
                    ON CONFLICT DO NOTHING;
                    """,
                    (h, "identifier", reason),
                )
                conn.commit()
            _ACTIVE_HASHES.add(h)
            return True
    except Exception as exc:
        logger.warning("Failed to insert into suppression list: %s", exc)
    finally:
        if conn:
            release_connection(conn)
    return False


def filter_people(people: List[PersonRecord]) -> List[PersonRecord]:
    """Filters out any suppressed individuals."""
    allowed: List[PersonRecord] = []
    for p in people:
        if is_suppressed(p.name) or is_suppressed(p.full_name):
            continue
        # Check emails
        filtered_emails = [e for e in p.emails if not is_suppressed(e.value)]
        p.emails = filtered_emails
        allowed.append(p)
    return allowed


def filter_organization(org: OrgRecord) -> OrgRecord:
    """Filters suppressed contacts, people, and emails out of an organization record."""
    org.people = filter_people(org.people)
    org.emails = [e for e in org.emails if not is_suppressed(e.value)]
    org.phones = [ph for ph in org.phones if not is_suppressed(ph.number)]
    return org
