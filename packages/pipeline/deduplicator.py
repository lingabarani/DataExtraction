"""
OneExtraction — Enterprise Deduplicator & Entity Resolution Engine

Production-grade multi-tier entity resolution and executive career tracking.
Checks incoming records against the database and determines: INSERT, UPDATE, or SKIP.

Entity Resolution Priority Order:
  Companies : ein → rfc → cik → npi → domain → normalized_name + state_code → fuzzy_name (pg_trgm / Levenshtein)
  People    : linkedin_url → email → full_name + company_id

Enterprise Principles:
  1. Deterministic statutory IDs (EIN, RFC, CIK, NPI) strictly precede web domains.
     (Prevents separate subsidiaries or franchises sharing a parent domain from collapsing).
  2. Non-destructive Provenance Merging:
     Existing non-null attributes are preserved. Incoming sources append to the `source_records` JSONB array.
  3. Executive Job Transition Tracking:
     When an executive moves to a new company or title, previous positions are archived to `career_history` JSONB.
  4. Memory-efficient batch pre-warming via `warm_company_cache`.
  5. High-throughput buffered dedup audit logging (`flush_logs`).
"""

import difflib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("oneextraction.deduplicator")


# ─────────────────────────────────────────────────────────────────────────────
# Result container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DedupResult:
    action: str                            # 'insert' | 'update' | 'skip'
    id: str                                # The canonical ID to use (new or existing)
    updates: Dict[str, Any] = field(default_factory=dict)  # Fields to patch on update
    match_field: Optional[str] = None      # Field that triggered the resolution
    match_value: Optional[str] = None      # Value that matched
    confidence: float = 1.0                # Match confidence score (0.0 - 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# JSON Helper
# ─────────────────────────────────────────────────────────────────────────────

def _safe_json_loads(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        try:
            return json.loads(val)
        except Exception:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Non-destructive Merge Helper
# ─────────────────────────────────────────────────────────────────────────────

def _merge_updates(existing: dict, incoming: dict, entity_type: str = "company") -> dict:
    """
    Return a dict of fields from `incoming` that would fill null/empty
    slots in `existing`. Never overrides a non-null existing value, except
    for quality scores (if higher), provenance records (appended), and career history.
    """
    updates: Dict[str, Any] = {}
    skip_always = {'id', 'created_at', 'raw_payload', 'data_quality_score', 'source_records', 'career_history'}

    # 1. Fill in missing fields
    for key, new_val in incoming.items():
        if key in skip_always:
            continue
        if new_val is None or new_val == '' or new_val == '[]':
            continue
        old_val = existing.get(key)
        if old_val is None or old_val == '' or old_val == '[]':
            updates[key] = new_val

    # 2. Quality score promotion
    inc_score = incoming.get('data_quality_score')
    ext_score = existing.get('data_quality_score')
    if inc_score is not None and (ext_score is None or inc_score > ext_score):
        updates['data_quality_score'] = inc_score

    # 3. Provenance aggregation (source_records JSONB)
    existing_sources = _safe_json_loads(existing.get('source_records')) or []
    if not isinstance(existing_sources, list):
        existing_sources = []

    inc_source = incoming.get('api_source') or incoming.get('source')
    inc_id = incoming.get('id') or 'INCOMING'
    timestamp = datetime.now(timezone.utc).isoformat()

    # If existing had no provenance list, initialize with its own primary source
    if not existing_sources:
        ext_source = existing.get('api_source') or existing.get('source') or 'EXISTING'
        existing_sources.append({
            "source": ext_source,
            "id": existing.get('id'),
            "recorded_at": str(existing.get('created_at') or timestamp),
            "is_primary": True
        })

    # Append incoming source if not already present
    already_recorded = any(
        isinstance(s, dict) and s.get('source') == inc_source and s.get('id') == inc_id
        for s in existing_sources
    )
    if inc_source and not already_recorded:
        existing_sources.append({
            "source": inc_source,
            "id": inc_id,
            "recorded_at": timestamp,
            "is_primary": False
        })
        updates['source_records'] = json.dumps(existing_sources)
        updates['source_count'] = len(existing_sources)

    return updates


STATUTORY_FIELDS = {'ein', 'rfc', 'cik', 'npi'}


def _has_statutory_id_conflict(existing: dict, incoming: dict) -> bool:
    """
    Checks if existing and incoming records have conflicting statutory identifiers.
    Statutory IDs: ein, rfc, cik, npi.
    If both records define the same statutory ID with differing values,
    OR if they have conflicting national statutory jurisdictions (US EIN vs Mexican RFC,
    or different explicit countries), they represent distinct legal entities and must not be merged.
    """
    if not existing or not incoming:
        return False

    # 1. Direct statutory ID value conflicts
    for f in ('ein', 'rfc', 'cik', 'npi'):
        ext_val = existing.get(f)
        inc_val = incoming.get(f)
        if ext_val and inc_val:
            s_ext = str(ext_val).strip().upper().replace("-", "").replace(" ", "")
            s_inc = str(inc_val).strip().upper().replace("-", "").replace(" ", "")
            if s_ext and s_inc and s_ext != s_inc:
                return True

    # 2. Country jurisdiction conflict
    ext_country = (existing.get('country') or existing.get('country_code') or '').strip().upper()
    inc_country = (incoming.get('country') or incoming.get('country_code') or '').strip().upper()
    if ext_country and inc_country and ext_country != inc_country:
        return True

    # 3. Cross-border statutory system conflict (US EIN/CIK vs MX RFC)
    has_us_ext = bool(existing.get('ein') or existing.get('cik'))
    has_mx_ext = bool(existing.get('rfc'))
    has_us_inc = bool(incoming.get('ein') or incoming.get('cik'))
    has_mx_inc = bool(incoming.get('rfc'))

    if (has_us_ext and has_mx_inc and not has_mx_ext) or (has_mx_ext and has_us_inc and not has_us_ext):
        return True

    return False


ALLOWED_COMPANY_QUERY_FIELDS = {
    'id', 'ein', 'rfc', 'cik', 'npi', 'domain', 'name', 'normalized_name', 'state_code'
}
ALLOWED_PERSON_QUERY_FIELDS = {
    'id', 'linkedin_url', 'email', 'full_name', 'company_id'
}


# ─────────────────────────────────────────────────────────────────────────────
# Main Deduplicator Class
# ─────────────────────────────────────────────────────────────────────────────

class Deduplicator:
    """
    Enterprise deduplication and entity resolution controller.
    Ensures zero cross-entity collisions, preserves historical executive positions,
    and aggregates multi-source provenance.
    """

    def __init__(self, conn, run_id: Optional[str] = None):
        self.conn = conn
        self.run_id = run_id or str(uuid.uuid4())[:8]
        # In-memory candidate lookup caches: key -> canonical_id
        self._company_cache: Dict[str, str] = {}
        self._people_cache: Dict[str, str] = {}
        self._company_records_cache: Dict[str, dict] = {}
        self._people_records_cache: Dict[str, dict] = {}
        self._pending_logs: List[Tuple] = []

    # ── Company Entity Resolution ─────────────────────────────────────────────

    def check_company(self, record: dict) -> DedupResult:
        """
        Check if company already exists using multi-tier resolution.
        Priority: ein → rfc → cik → npi → domain → normalized_name+state_code → fuzzy_name
        """
        # 1. Deterministic statutory IDs strictly before domain
        candidates = [
            ('ein',     record.get('ein')),
            ('rfc',     record.get('rfc')),
            ('cik',     record.get('cik')),
            ('npi',     record.get('npi')),
            ('domain',  record.get('domain')),
        ]

        # 2. Composite key: normalized_name + state_code
        norm_name = record.get('normalized_name') or (record.get('name') or '').strip().upper()
        state = record.get('state_code') or record.get('state')
        if norm_name and state:
            state_code = str(state)[:2].upper()
            candidates.append(('normalized_name+state_code', f"{norm_name}|{state_code}"))

        # Check candidates in priority order
        for match_field, match_value in candidates:
            if not match_value:
                continue

            cache_key = f"{match_field}:{match_value}"
            if cache_key in self._company_cache:
                existing_id = self._company_cache[cache_key]
                existing = self._fetch_company(existing_id) or self._company_records_cache.get(existing_id) or {}

                # If matching on non-statutory field (e.g. domain, composite), check for statutory conflict
                if match_field not in STATUTORY_FIELDS and _has_statutory_id_conflict(existing, record):
                    continue

                updates = _merge_updates(existing, record, entity_type="company")
                if updates:
                    if existing_id in self._company_records_cache:
                        self._company_records_cache[existing_id].update(updates)
                    self._log_dedup('company', record.get('id') or 'NEW',
                                    existing_id, match_field, match_value)
                    return DedupResult('update', existing_id, updates, match_field, match_value, confidence=1.0)
                return DedupResult('skip', existing_id, {}, match_field, match_value, confidence=1.0)

            # Query database
            existing = self._find_company(match_field, match_value)
            if existing:
                # If matching on non-statutory field, check for statutory conflict
                if match_field not in STATUTORY_FIELDS and _has_statutory_id_conflict(existing, record):
                    continue

                existing_id = existing['id']
                self._cache_company_record(existing)

                updates = _merge_updates(existing, record, entity_type="company")
                if updates:
                    if existing_id in self._company_records_cache:
                        self._company_records_cache[existing_id].update(updates)
                    self._log_dedup('company', record.get('id') or 'NEW',
                                    existing_id, match_field, match_value)
                    return DedupResult('update', existing_id, updates, match_field, match_value, confidence=1.0)
                return DedupResult('skip', existing_id, {}, match_field, match_value, confidence=1.0)

        # 3. Fuzzy Name Resolution (pg_trgm / SequenceMatcher fallback)
        if norm_name and len(norm_name) >= 4:
            fuzzy_match = self._find_company_fuzzy(norm_name, state_code=state)
            if fuzzy_match:
                if not _has_statutory_id_conflict(fuzzy_match, record):
                    existing_id = fuzzy_match['id']
                    self._cache_company_record(fuzzy_match)
                    updates = _merge_updates(fuzzy_match, record, entity_type="company")
                    if updates:
                        if existing_id in self._company_records_cache:
                            self._company_records_cache[existing_id].update(updates)
                        self._log_dedup('company', record.get('id') or 'NEW',
                                        existing_id, 'fuzzy_name', norm_name)
                        return DedupResult('update', existing_id, updates, 'fuzzy_name', norm_name, confidence=fuzzy_match.get('_similarity', 0.88))
                    return DedupResult('skip', existing_id, {}, 'fuzzy_name', norm_name, confidence=fuzzy_match.get('_similarity', 0.88))

        # 4. No Match Found → INSERT
        new_id = record.get('id') or self._new_company_id()
        record['id'] = new_id

        # Initialize source provenance for new insert
        if 'source_records' not in record or not record['source_records']:
            src = record.get('api_source') or record.get('source') or 'PRIMARY'
            record['source_records'] = json.dumps([{
                "source": src,
                "id": new_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "is_primary": True
            }])

        self._cache_company_record(record)
        return DedupResult('insert', new_id, confidence=1.0)

    # ── Person Entity Resolution & Career Tracking ────────────────────────────

    def check_person(self, record: dict) -> DedupResult:
        """
        Check if person already exists.
        Priority: linkedin_url → email → full_name + company_id.
        Archives prior roles into career_history upon job/company transition.
        """
        candidates = [
            ('linkedin_url', record.get('linkedin_url')),
            ('email',        record.get('email')),
        ]

        full_name = record.get('full_name')
        company_id = record.get('company_id')
        if full_name and company_id:
            candidates.append(
                ('full_name+company_id',
                 f"{full_name.strip().upper()}|{company_id}")
            )

        for match_field, match_value in candidates:
            if not match_value:
                continue

            cache_key = f"{match_field}:{match_value}"
            if cache_key in self._people_cache:
                existing_id = self._people_cache[cache_key]
                existing = self._fetch_person(existing_id) or self._people_records_cache.get(existing_id) or {}
                updates = self._resolve_person_updates(existing, record)
                if updates:
                    if existing_id in self._people_records_cache:
                        self._people_records_cache[existing_id].update(updates)
                    self._log_dedup('person', record.get('id') or 'NEW',
                                    existing_id, match_field, match_value)
                    return DedupResult('update', existing_id, updates, match_field, match_value, confidence=1.0)
                return DedupResult('skip', existing_id, {}, match_field, match_value, confidence=1.0)

            existing = self._find_person(match_field, match_value)
            if existing:
                existing_id = existing['id']
                self._cache_person_record(existing)

                updates = self._resolve_person_updates(existing, record)
                if updates:
                    if existing_id in self._people_records_cache:
                        self._people_records_cache[existing_id].update(updates)
                    self._log_dedup('person', record.get('id') or 'NEW',
                                    existing_id, match_field, match_value)
                    return DedupResult('update', existing_id, updates, match_field, match_value, confidence=1.0)
                return DedupResult('skip', existing_id, {}, match_field, match_value, confidence=1.0)

        # No Match → INSERT
        new_id = record.get('id') or self._new_person_id()
        record['id'] = new_id

        if 'career_history' not in record or not record['career_history']:
            record['career_history'] = '[]'

        if 'source_records' not in record or not record['source_records']:
            src = record.get('api_source') or record.get('source') or 'PRIMARY'
            record['source_records'] = json.dumps([{
                "source": src,
                "id": new_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "is_primary": True
            }])

        self._cache_person_record(record)
        return DedupResult('insert', new_id, confidence=1.0)

    def _resolve_person_updates(self, existing: dict, incoming: dict) -> dict:
        """
        Calculates updates for an existing person, preserving history when
        job title or employer transitions.
        """
        updates = _merge_updates(existing, incoming, entity_type="person")

        # Detect executive job/role change
        inc_company_id = incoming.get('company_id')
        ext_company_id = existing.get('company_id')
        inc_title = incoming.get('title')
        ext_title = existing.get('title')

        is_company_change = inc_company_id and ext_company_id and inc_company_id != ext_company_id
        is_title_change = inc_title and ext_title and inc_title.strip().upper() != ext_title.strip().upper()

        if (is_company_change or is_title_change) and incoming.get('is_current', True):
            # Executive has transitioned to a new role or company!
            career = _safe_json_loads(existing.get('career_history')) or []
            if not isinstance(career, list):
                career = []

            # Archive the prior position
            old_role = {
                "title": ext_title or existing.get("official_title"),
                "standardized_title": existing.get("standardized_title"),
                "company_id": ext_company_id,
                "company_name": existing.get("company_name"),
                "seniority_level": existing.get("seniority_level"),
                "department": existing.get("department"),
                "is_current": False,
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }

            # Avoid duplicate archival of same title & company
            already_in_career = any(
                isinstance(r, dict) and r.get('title') == old_role['title'] and r.get('company_id') == old_role['company_id']
                for r in career
            )
            if (old_role['title'] or old_role['company_id']) and not already_in_career:
                career.append(old_role)

            updates['career_history'] = json.dumps(career)

            # Update current active position
            if inc_company_id:
                updates['company_id'] = inc_company_id
            if incoming.get('company_name'):
                updates['company_name'] = incoming['company_name']
            if inc_title:
                updates['title'] = inc_title
            if incoming.get('official_title'):
                updates['official_title'] = incoming['official_title']
            if incoming.get('standardized_title'):
                updates['standardized_title'] = incoming['standardized_title']
            if incoming.get('seniority_level'):
                updates['seniority_level'] = incoming['seniority_level']
            if incoming.get('department'):
                updates['department'] = incoming['department']
            updates['is_current'] = True

        return updates

    # ── In-Memory Caching Helpers ─────────────────────────────────────────────

    def _cache_company_record(self, record: dict):
        cid = record.get('id')
        if not cid:
            return
        self._company_records_cache[cid] = dict(record)
        for f in ('ein', 'rfc', 'cik', 'npi', 'domain'):
            val = record.get(f)
            if val:
                self._company_cache[f"{f}:{val}"] = cid
        norm_name = record.get('normalized_name')
        state = record.get('state_code') or record.get('state')
        if norm_name and state:
            self._company_cache[f"normalized_name+state_code:{norm_name}|{str(state)[:2].upper()}"] = cid

    def _cache_person_record(self, record: dict):
        pid = record.get('id')
        if not pid:
            return
        self._people_records_cache[pid] = dict(record)
        if record.get('linkedin_url'):
            self._people_cache[f"linkedin_url:{record['linkedin_url']}"] = pid
        if record.get('email'):
            self._people_cache[f"email:{record['email']}"] = pid
        if record.get('full_name') and record.get('company_id'):
            self._people_cache[f"full_name+company_id:{record['full_name'].strip().upper()}|{record['company_id']}"] = pid

    def warm_company_cache(self, domains: list = None, eins: list = None,
                           rfcs: list = None, ciks: list = None, npis: list = None):
        """Batch pre-loads candidate company IDs into cache in a single query."""
        if not self.conn:
            return
        clauses, params = [], []

        def _add_param(field_name: str, values: list):
            clean = [str(v).strip() for v in values if v]
            if clean:
                clauses.append(f"{field_name} = ANY(%s)")
                params.append(clean)

        if domains: _add_param("domain", domains)
        if eins:    _add_param("ein", eins)
        if rfcs:    _add_param("rfc", rfcs)
        if ciks:    _add_param("cik", ciks)
        if npis:    _add_param("npi", npis)

        if not clauses:
            return

        sql = f"SELECT id, domain, ein, cik FROM companies WHERE {' OR '.join(clauses)}"
        try:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            for row in cur.fetchall():
                cid = row[0]
                if len(row) > 1 and row[1]: self._company_cache[f"domain:{row[1]}"] = cid
                if len(row) > 2 and row[2]: self._company_cache[f"ein:{row[2]}"] = cid
                if len(row) > 3 and row[3]: self._company_cache[f"cik:{row[3]}"] = cid
            cur.close()
        except Exception as e:
            logger.debug("warm_company_cache query fallback: %s", e)
            try:
                self.conn.rollback()
            except Exception:
                pass

    # ── Database Lookup Helpers ───────────────────────────────────────────────

    def _find_company(self, field: str, value: str) -> Optional[dict]:
        """Look up a company by a deterministic identifier or composite key."""
        if not self.conn or not value:
            return None
        if field != 'normalized_name+state_code' and field not in ALLOWED_COMPANY_QUERY_FIELDS:
            raise ValueError(f"Disallowed company query field: {field}")
        cur = self._get_dict_cursor()
        try:
            if field == 'normalized_name+state_code':
                name, state = value.split('|', 1)
                cur.execute(
                    "SELECT * FROM companies WHERE normalized_name=%s AND state_code=%s LIMIT 1",
                    (name, state)
                )
            else:
                cur.execute(
                    f"SELECT * FROM companies WHERE \"{field}\"=%s AND \"{field}\" IS NOT NULL LIMIT 1",
                    (value,)
                )
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.debug("Database error querying %s=%s: %s", field, value, e)
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None
        finally:
            cur.close()


    def _find_company_fuzzy(self, normalized_name: str, state_code: Optional[str] = None, threshold: float = 0.88) -> Optional[dict]:
        """
        Fuzzy company name resolution via pg_trgm similarity or SequenceMatcher.
        Threshold: >= threshold similarity.
        """
        if not self.conn or not normalized_name:
            return None
        cur = self._get_dict_cursor()

        # 1. Attempt PostgreSQL pg_trgm similarity search if enabled
        try:
            if state_code:
                st = str(state_code)[:2].upper()
                cur.execute(
                    """
                    SELECT *, similarity(normalized_name, %s) AS _similarity
                    FROM companies
                    WHERE state_code = %s AND similarity(normalized_name, %s) >= %s
                    ORDER BY _similarity DESC
                    LIMIT 1
                    """,
                    (normalized_name, st, normalized_name, threshold)
                )
            else:
                cur.execute(
                    """
                    SELECT *, similarity(normalized_name, %s) AS _similarity
                    FROM companies
                    WHERE similarity(normalized_name, %s) >= %s
                    ORDER BY _similarity DESC
                    LIMIT 1
                    """,
                    (normalized_name, normalized_name, threshold)
                )
            row = cur.fetchone()
            if row:
                return dict(row)
        except Exception:
            # Fall back to in-memory comparison if pg_trgm extension is not installed
            try:
                self.conn.rollback()
            except Exception:
                pass

        # 2. In-memory Levenshtein / SequenceMatcher fallback across candidates in state
        try:
            if state_code:
                cur.execute(
                    "SELECT id, name, normalized_name, state_code FROM companies WHERE state_code = %s LIMIT 100",
                    (str(state_code)[:2].upper(),)
                )
                rows = cur.fetchall()
                best_match = None
                best_ratio = 0.0
                for r in rows:
                    candidate = dict(r)
                    cand_name = candidate.get('normalized_name') or ''
                    ratio = difflib.SequenceMatcher(None, normalized_name, cand_name).ratio()
                    if ratio >= threshold and ratio > best_ratio:
                        best_ratio = ratio
                        best_match = candidate
                if best_match:
                    full_record = self._fetch_company(best_match['id'])
                    if full_record:
                        full_record['_similarity'] = best_ratio
                        return full_record
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
        finally:
            cur.close()

        return None

    def find_company_by_trigram(self, name: str, state_code: Optional[str] = None, threshold: float = 0.85) -> Optional[dict]:
        """
        Public API for trigram fuzzy matching on company name.
        Normalizes company name, applies state_code filter if present, and queries database with similarity threshold.
        """
        if not name or not isinstance(name, str):
            return None
        norm_name = re.sub(r'[^A-Z0-9 ]+', ' ', name.upper()).strip()
        norm_name = ' '.join(norm_name.split())
        if not norm_name:
            return None
        return self._find_company_fuzzy(norm_name, state_code=state_code, threshold=threshold)

    def _fetch_company(self, company_id: str) -> dict:
        if not self.conn or not company_id:
            return {}
        cur = self._get_dict_cursor()
        try:
            cur.execute("SELECT * FROM companies WHERE id=%s LIMIT 1", (company_id,))
            row = cur.fetchone()
            return dict(row) if row else {}
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            return {}
        finally:
            cur.close()

    def _find_person(self, field: str, value: str) -> Optional[dict]:
        if not self.conn or not value:
            return None
        if field != 'full_name+company_id' and field not in ALLOWED_PERSON_QUERY_FIELDS:
            raise ValueError(f"Disallowed person query field: {field}")
        cur = self._get_dict_cursor()
        try:
            if field == 'full_name+company_id':
                name, cid = value.split('|', 1)
                cur.execute(
                    "SELECT * FROM people WHERE UPPER(full_name)=%s AND company_id=%s LIMIT 1",
                    (name, cid)
                )
            else:
                cur.execute(
                    f"SELECT * FROM people WHERE \"{field}\"=%s AND \"{field}\" IS NOT NULL LIMIT 1",
                    (value,)
                )
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.debug("Database error querying person %s=%s: %s", field, value, e)
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None
        finally:
            cur.close()


    def _fetch_person(self, person_id: str) -> dict:
        if not self.conn or not person_id:
            return {}
        cur = self._get_dict_cursor()
        try:
            cur.execute("SELECT * FROM people WHERE id=%s LIMIT 1", (person_id,))
            row = cur.fetchone()
            return dict(row) if row else {}
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            return {}
        finally:
            cur.close()

    def _get_dict_cursor(self):
        try:
            from db_connector import get_cursor
            return get_cursor(self.conn, dict_cursor=True)
        except Exception:
            # Fallback for mock or custom connections
            return self.conn.cursor()

    # ── Resolvers & Utilities ─────────────────────────────────────────────────

    def resolve_company_id(self, domain: str = None, company_name: str = None) -> Optional[str]:
        """
        Given a domain or company_name, return the existing company ID from DB.
        Returns None if not found.
        """
        if domain:
            cache_key = f"domain:{domain}"
            if cache_key in self._company_cache:
                return self._company_cache[cache_key]
            existing = self._find_company('domain', domain)
            if existing:
                cid = existing['id']
                self._company_cache[cache_key] = cid
                return cid

        if company_name:
            norm = company_name.strip().upper()
            cache_key = f"name:{norm}"
            if cache_key in self._company_cache:
                return self._company_cache[cache_key]
            existing = self._find_company_by_name(norm)
            if existing:
                cid = existing['id']
                self._company_cache[cache_key] = cid
                return cid

        return None

    def _find_company_by_name(self, normalized_name: str) -> Optional[dict]:
        if not self.conn:
            return None
        cur = self._get_dict_cursor()
        try:
            cur.execute("SELECT * FROM companies WHERE normalized_name=%s LIMIT 1", (normalized_name,))
            row = cur.fetchone()
            return dict(row) if row else None
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            return None
        finally:
            cur.close()

    # ── ID Generators ─────────────────────────────────────────────────────────

    @staticmethod
    def _new_company_id() -> str:
        return f"co_{uuid.uuid4().hex[:24]}"

    @staticmethod
    def _new_person_id() -> str:
        return f"per_{uuid.uuid4().hex[:24]}"

    # ── Buffered Dedup Logging ────────────────────────────────────────────────

    def _log_dedup(self, entity_type: str, duplicate_id: str,
                   kept_id: str, match_field: str, match_value: str):
        self._pending_logs.append(
            (entity_type, duplicate_id, kept_id, match_field, match_value, self.run_id)
        )
        if len(self._pending_logs) >= 500:
            self.flush_logs()

    def flush_logs(self):
        """Flushes buffered dedup log entries in a single batch insert."""
        if not self._pending_logs or not self.conn:
            return
        entries = self._pending_logs
        self._pending_logs = []
        try:
            from psycopg2.extras import execute_values
            cur = self.conn.cursor()
            execute_values(
                cur,
                """
                INSERT INTO dedup_log
                    (entity_type, duplicate_id, kept_id, match_field, match_value, run_id)
                VALUES %s
                """,
                entries
            )
            self.conn.commit()
            cur.close()
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass

    def cache_stats(self) -> dict:
        return {
            'company_cache_size': len(self._company_cache),
            'people_cache_size':  len(self._people_cache),
            'pending_audit_logs': len(self._pending_logs),
        }


__all__ = [
    "Deduplicator",
    "DedupResult",
    "STATUTORY_FIELDS",
    "ALLOWED_COMPANY_QUERY_FIELDS",
    "ALLOWED_PERSON_QUERY_FIELDS",
    "_has_statutory_id_conflict",
    "_merge_updates",
    "_safe_json_loads",
]

