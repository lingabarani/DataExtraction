"""
OneExtraction — Dead-Letter Queue (DLQ) & Resilience Engine

Provides zero-data-loss failure capture, audit tracking, and replay capabilities
for malformed, rate-limited, or unprocessable ingestion records.

If database insertion fails, transparently falls back to local disk-persisted JSONL logs.
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from db_connector import get_cursor

logger = logging.getLogger("oneextraction.dlq")

_BASE_DIR = Path(__file__).resolve().parent
_FALLBACK_DIR = _BASE_DIR / "output" / "logs" / "dlq"
_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
_FALLBACK_FILE = _FALLBACK_DIR / "dlq_fallback.jsonl"


def _safe_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return json.dumps({"raw": str(obj)})


def enqueue_dead_letter(
    conn,
    source_name: str,
    entity_type: str,
    raw_payload: Any,
    error_reason: str,
    error_traceback: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Optional[int]:
    """
    Persists a failed ingestion record into the dead_letter_queue table.
    Falls back to a disk-persisted JSONL log if the database is unreachable.
    Returns the generated record ID, or None if logged to fallback.
    """
    if not source_name:
        source_name = "UNKNOWN_SOURCE"
    if not entity_type:
        entity_type = "company"

    payload_json = _safe_json_dumps(raw_payload)
    reason_clean = str(error_reason)[:1000] if error_reason else "Unknown error"
    tb_clean = str(error_traceback)[:4000] if error_traceback else None

    # 1. Attempt database persistence
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO dead_letter_queue
                    (run_id, source_name, entity_type, raw_payload, error_reason,
                     error_traceback, status, retry_count, created_at)
                VALUES
                    (%s, %s, %s, %s::jsonb, %s, %s, 'PENDING', 0, NOW())
                RETURNING id
            """, (run_id, source_name, entity_type, payload_json, reason_clean, tb_clean))
            new_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            logger.info("Enqueued dead-letter record id=%d for source=%s (reason=%s)",
                        new_id, source_name, reason_clean)
            return new_id
        except Exception as db_err:
            logger.warning("Database insert failed for DLQ record (fallback to disk): %s", db_err)
            try:
                conn.rollback()
            except Exception:
                pass

    # 2. Resilient disk fallback (zero data loss guarantee)
    try:
        fallback_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "source_name": source_name,
            "entity_type": entity_type,
            "error_reason": reason_clean,
            "error_traceback": tb_clean,
            "raw_payload": raw_payload if isinstance(raw_payload, dict) else payload_json,
        }
        with open(_FALLBACK_FILE, "a", encoding="utf-8") as f:
            f.write(_safe_json_dumps(fallback_record) + "\n")
        logger.info("Persisted DLQ record to fallback file: %s", _FALLBACK_FILE)
    except Exception as disk_err:
        logger.critical("Catastrophic DLQ disk fallback failure: %s", disk_err)

    return None


def drain_fallback_to_db(conn, fallback_file: Optional[Path] = None) -> Dict[str, Any]:
    """
    Drains locally buffered dead-letter records from disk fallback log
    into the primary PostgreSQL dead_letter_queue table.
    Ensures zero data loss during database outages or failovers.
    """
    target_file = fallback_file or _FALLBACK_FILE
    if not target_file.exists():
        return {"drained": 0, "status": "NO_FALLBACK_FILE"}

    try:
        with open(target_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
    except Exception as e:
        logger.error("Failed to read DLQ fallback file %s: %s", target_file, e)
        return {"drained": 0, "error": str(e), "status": "READ_ERROR"}

    if not lines:
        return {"drained": 0, "status": "EMPTY"}

    if not conn:
        return {"drained": 0, "error": "No database connection available", "status": "NO_DB_CONNECTION"}

    drained_count = 0
    cur = conn.cursor()
    try:
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue

            run_id = rec.get("run_id")
            source_name = rec.get("source_name", "UNKNOWN_SOURCE")
            entity_type = rec.get("entity_type", "company")
            payload = rec.get("raw_payload", {})
            reason = str(rec.get("error_reason", "Recovered from disk fallback"))[:1000]
            tb = str(rec.get("error_traceback"))[:4000] if rec.get("error_traceback") else None

            payload_json = _safe_json_dumps(payload)
            cur.execute("""
                INSERT INTO dead_letter_queue
                    (run_id, source_name, entity_type, raw_payload, error_reason,
                     error_traceback, status, retry_count, created_at)
                VALUES
                    (%s, %s, %s, %s::jsonb, %s, %s, 'PENDING', 0, NOW())
            """, (run_id, source_name, entity_type, payload_json, reason, tb))
            drained_count += 1

        conn.commit()

        # Archive/rotate the fallback file once successfully persisted
        archive_name = target_file.with_name(
            f"dlq_fallback_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.drained.jsonl"
        )
        try:
            target_file.rename(archive_name)
        except Exception:
            with open(target_file, "w", encoding="utf-8") as f:
                f.truncate(0)

        logger.info("Successfully drained %d DLQ fallback records to database. Archived to %s",
                    drained_count, archive_name.name)
        return {"drained": drained_count, "archive": archive_name.name, "status": "SUCCESS"}

    except Exception as db_err:
        logger.error("Failed to drain DLQ fallback records into database: %s", db_err)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"drained": 0, "error": str(db_err), "status": "DB_ERROR"}
    finally:
        cur.close()


def get_dead_letter_records(
    conn,
    source_name: Optional[str] = None,
    status: str = "PENDING",
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Retrieves paginated dead-letter records."""
    if not conn:
        return []
    try:
        cur = get_cursor(conn, dict_cursor=True)
    except Exception:
        cur = conn.cursor()

    try:
        conditions = []
        params = []

        if status and status.upper() != "ALL":
            conditions.append("status = %s")
            params.append(status.upper())
        if source_name:
            conditions.append("source_name = %s")
            params.append(source_name)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT id, run_id, source_name, entity_type, raw_payload,
                   error_reason, status, retry_count, created_at,
                   last_retried_at, resolved_at
            FROM dead_letter_queue
            {where}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([max(1, limit), max(0, offset)])
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Error retrieving dead-letter records: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return []
    finally:
        cur.close()


def get_dead_letter_stats(conn) -> Dict[str, Any]:
    """Returns aggregated DLQ metrics and status breakdown."""
    if not conn:
        return {"total": 0, "pending": 0, "resolved": 0, "discarded": 0, "by_source": []}

    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                COUNT(1) AS total,
                COUNT(1) FILTER (WHERE status = 'PENDING') AS pending,
                COUNT(1) FILTER (WHERE status = 'RESOLVED') AS resolved,
                COUNT(1) FILTER (WHERE status = 'DISCARDED') AS discarded
            FROM dead_letter_queue
        """)
        row = cur.fetchone()
        stats = {
            "total": int(row[0] or 0),
            "pending": int(row[1] or 0),
            "resolved": int(row[2] or 0),
            "discarded": int(row[3] or 0),
        }

        # Breakdown by source
        cur.execute("""
            SELECT source_name, status, COUNT(1)
            FROM dead_letter_queue
            GROUP BY source_name, status
            ORDER BY source_name ASC
        """)
        by_source_rows = cur.fetchall()
        by_source = {}
        for src, st, cnt in by_source_rows:
            if src not in by_source:
                by_source[src] = {"source": src, "pending": 0, "resolved": 0, "discarded": 0, "total": 0}
            by_source[src]["total"] += cnt
            if st.lower() in by_source[src]:
                by_source[src][st.lower()] += cnt

        stats["by_source"] = list(by_source.values())
        return stats
    except Exception as e:
        logger.error("Error retrieving DLQ stats: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"total": 0, "pending": 0, "resolved": 0, "discarded": 0, "by_source": []}
    finally:
        cur.close()


def replay_dead_letter(
    conn,
    dlq_id: int,
    processor_func: Callable[[Dict[str, Any]], bool],
    max_retries: int = 3,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Replays a specific dead-letter record using a custom processor function.
    Marks record as RESOLVED if processor returns True.
    Increments retry_count and marks DISCARDED if max_retries exceeded.
    """
    if not conn:
        return {"success": False, "error": "No database connection"}

    try:
        cur = get_cursor(conn, dict_cursor=True)
    except Exception:
        cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM dead_letter_queue WHERE id = %s", (dlq_id,))
        record = cur.fetchone()
        if not record:
            return {"success": False, "error": f"DLQ record {dlq_id} not found"}

        record_dict = dict(record)
        raw_payload = record_dict.get("raw_payload")
        if isinstance(raw_payload, str):
            try:
                raw_payload = json.loads(raw_payload)
            except Exception:
                pass

        if dry_run:
            return {"success": True, "dry_run": True, "record_id": dlq_id, "action": "SIMULATED_REPLAY"}

        # Attempt replay execution
        try:
            success = processor_func(raw_payload)
        except Exception as proc_err:
            success = False
            error_msg = f"Replay processor failed: {proc_err}\n{traceback.format_exc()}"
        else:
            error_msg = None

        cur_write = conn.cursor()
        now_iso = datetime.now(timezone.utc).isoformat()
        current_retries = int(record_dict.get("retry_count", 0)) + 1

        if success:
            cur_write.execute("""
                UPDATE dead_letter_queue
                SET status = 'RESOLVED',
                    retry_count = %s,
                    last_retried_at = NOW(),
                    resolved_at = NOW()
                WHERE id = %s
            """, (current_retries, dlq_id))
            conn.commit()
            cur_write.close()
            logger.info("Successfully replayed DLQ record id=%d", dlq_id)
            return {"success": True, "record_id": dlq_id, "status": "RESOLVED"}
        else:
            new_status = "DISCARDED" if current_retries >= max_retries else "PENDING"
            cur_write.execute("""
                UPDATE dead_letter_queue
                SET status = %s,
                    retry_count = %s,
                    last_retried_at = NOW(),
                    error_reason = COALESCE(%s, error_reason)
                WHERE id = %s
            """, (new_status, current_retries, error_msg[:1000] if error_msg else None, dlq_id))
            conn.commit()
            cur_write.close()
            logger.warning("Replay failed for DLQ record id=%d (status=%s, retries=%d)",
                           dlq_id, new_status, current_retries)
            return {"success": False, "record_id": dlq_id, "status": new_status, "error": error_msg}

    except Exception as e:
        logger.error("Error executing DLQ replay: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return {"success": False, "error": str(e)}
    finally:
        cur.close()


def discard_dead_letter(conn, dlq_id: int, reason: str = "Manually discarded") -> bool:
    """Marks a DLQ record as DISCARDED."""
    if not conn:
        return False
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE dead_letter_queue
            SET status = 'DISCARDED',
                error_reason = %s,
                last_retried_at = NOW()
            WHERE id = %s
        """, (f"DISCARDED: {reason}"[:1000], dlq_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error("Error discarding DLQ record %d: %s", dlq_id, e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        cur.close()
