"""
Enterprise ACID State Checkpoint Manager for Open Map Extraction Engine.
Embedded in OneExtraction platform.
"""

import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

logger = logging.getLogger("OSMCheckpoint")


class EnterpriseCheckpointManager:
    """
    Guarantees ACID crash safety, zero phantom duplicates, and reliable resume
    for state-by-state, field-by-field, chunk-by-chunk Overpass data collection.
    """

    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.progress_dir = os.path.join(self.workspace_dir, "data", "progress")
        os.makedirs(self.progress_dir, exist_ok=True)

        self.db_path = os.path.join(self.progress_dir, "osm_state_progress.db")
        self.legacy_json_path = os.path.join(self.progress_dir, "osm_progress.json")
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chunks (
                    state_name TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    parent_id TEXT,
                    depth INTEGER DEFAULT 0,
                    min_lat REAL,
                    min_lon REAL,
                    max_lat REAL,
                    max_lon REAL,
                    status TEXT NOT NULL,
                    records_count INTEGER DEFAULT 0,
                    raw_path TEXT,
                    proc_path TEXT,
                    error_message TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (state_name, field_name, chunk_id)
                );

                CREATE TABLE IF NOT EXISTS field_status (
                    state_name TEXT NOT NULL,
                    field_name TEXT NOT NULL,
                    state_code TEXT,
                    field_group TEXT,
                    status TEXT NOT NULL,
                    total_chunks INTEGER DEFAULT 0,
                    completed_chunks INTEGER DEFAULT 0,
                    failed_chunks INTEGER DEFAULT 0,
                    split_chunks INTEGER DEFAULT 0,
                    records_collected INTEGER DEFAULT 0,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (state_name, field_name)
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_status ON chunks(state_name, field_name, status);
            """)

    def init_field(
        self,
        state_name: str,
        state_code: str,
        field_name: str,
        field_group: str,
        total_chunks: int,
        chunks_info: List[Dict[str, Any]]
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO field_status (
                    state_name, field_name, state_code, field_group, status,
                    total_chunks, completed_chunks, failed_chunks, split_chunks,
                    records_collected, started_at, updated_at
                ) VALUES (?, ?, ?, ?, 'in_progress', ?, 0, 0, 0, 0, ?, ?)
                ON CONFLICT(state_name, field_name) DO UPDATE SET
                    total_chunks = excluded.total_chunks,
                    updated_at = excluded.updated_at;
            """, (state_name, field_name, state_code, field_group, total_chunks, now_iso, now_iso))

            for c in chunks_info:
                cid = c["chunk_id"]
                s, w, n, e = c["bbox"]
                conn.execute("""
                    INSERT OR IGNORE INTO chunks (
                        state_name, field_name, chunk_id, parent_id, depth,
                        min_lat, min_lon, max_lat, max_lon, status, updated_at
                    ) VALUES (?, ?, ?, NULL, 0, ?, ?, ?, ?, 'PENDING', ?)
                """, (state_name, field_name, cid, s, w, n, e, now_iso))

        self._sync_stats(state_name, field_name)

    def mark_chunk_in_progress(
        self,
        state_name: str,
        field_name: str,
        chunk_id: str,
        bbox: Tuple[float, float, float, float],
        depth: int = 0,
        parent_id: Optional[str] = None
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        s, w, n, e = bbox
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO chunks (
                    state_name, field_name, chunk_id, parent_id, depth,
                    min_lat, min_lon, max_lat, max_lon, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'IN_PROGRESS', ?)
                ON CONFLICT(state_name, field_name, chunk_id) DO UPDATE SET
                    status = 'IN_PROGRESS',
                    updated_at = excluded.updated_at;
            """, (state_name, field_name, chunk_id, parent_id, depth, s, w, n, e, now_iso))

    def mark_chunk_completed(
        self,
        state_name: str,
        field_name: str,
        chunk_id: str,
        records_count: int,
        raw_path: str,
        proc_path: str
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE chunks SET
                    status = 'COMPLETED',
                    records_count = ?,
                    raw_path = ?,
                    proc_path = ?,
                    error_message = NULL,
                    updated_at = ?
                WHERE state_name = ? AND field_name = ? AND chunk_id = ?;
            """, (records_count, raw_path, proc_path, now_iso, state_name, field_name, chunk_id))
        self._sync_stats(state_name, field_name)

    def mark_chunk_failed(
        self,
        state_name: str,
        field_name: str,
        chunk_id: str,
        error_message: str
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE chunks SET
                    status = 'FAILED',
                    error_message = ?,
                    updated_at = ?
                WHERE state_name = ? AND field_name = ? AND chunk_id = ?;
            """, (error_message, now_iso, state_name, field_name, chunk_id))
        self._sync_stats(state_name, field_name)

    def mark_chunk_split(
        self,
        state_name: str,
        field_name: str,
        parent_chunk_id: str,
        child_chunks: List[Dict[str, Any]]
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE chunks SET status = 'SPLIT', updated_at = ?
                WHERE state_name = ? AND field_name = ? AND chunk_id = ?;
            """, (now_iso, state_name, field_name, parent_chunk_id))

            for child in child_chunks:
                cid = child["chunk_id"]
                depth = child["depth"]
                s, w, n, e = child["bbox"]
                conn.execute("""
                    INSERT INTO chunks (
                        state_name, field_name, chunk_id, parent_id, depth,
                        min_lat, min_lon, max_lat, max_lon, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                    ON CONFLICT(state_name, field_name, chunk_id) DO UPDATE SET
                        status = 'PENDING',
                        updated_at = excluded.updated_at;
                """, (state_name, field_name, cid, parent_chunk_id, depth, s, w, n, e, now_iso))

        self._sync_stats(state_name, field_name)

    def _sync_stats(self, state_name: str, field_name: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed,
                    SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
                    SUM(CASE WHEN status = 'SPLIT' THEN 1 ELSE 0 END) as split,
                    SUM(CASE WHEN status = 'COMPLETED' THEN records_count ELSE 0 END) as records
                FROM chunks
                WHERE state_name = ? AND field_name = ?;
            """, (state_name, field_name)).fetchone()

            if row:
                total = row["total"] or 0
                completed = row["completed"] or 0
                failed = row["failed"] or 0
                split = row["split"] or 0
                records = row["records"] or 0

                status = "completed" if (completed + split == total and failed == 0 and total > 0) else "in_progress"
                completed_at = now_iso if status == "completed" else None

                conn.execute("""
                    UPDATE field_status SET
                        completed_chunks = ?,
                        failed_chunks = ?,
                        split_chunks = ?,
                        records_collected = ?,
                        status = ?,
                        completed_at = COALESCE(completed_at, ?),
                        updated_at = ?
                    WHERE state_name = ? AND field_name = ?;
                """, (completed, failed, split, records, status, completed_at, now_iso, state_name, field_name))

        self.export_to_legacy_json()

    def get_completed_chunk_ids(self, state_name: str, field_name: str) -> Set[str]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT chunk_id FROM chunks
                WHERE state_name = ? AND field_name = ? AND status = 'COMPLETED';
            """, (state_name, field_name)).fetchall()
            return {r["chunk_id"] for r in rows}

    def get_failed_chunk_ids(self, state_name: str, field_name: str) -> List[str]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT chunk_id FROM chunks
                WHERE state_name = ? AND field_name = ? AND status = 'FAILED'
                ORDER BY chunk_id;
            """, (state_name, field_name)).fetchall()
            return [r["chunk_id"] for r in rows]

    def is_field_completed(self, state_name: str, field_name: str) -> bool:
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT status, completed_chunks, total_chunks, failed_chunks
                FROM field_status
                WHERE state_name = ? AND field_name = ?;
            """, (state_name, field_name)).fetchone()
            if not row:
                return False
            return row["status"] == "completed" and row["failed_chunks"] == 0

    def reconcile_disk_state(
        self,
        state_name: str,
        field_name: str,
        proc_field_dir: str
    ) -> Tuple[int, int]:
        repaired = 0
        valid = 0
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT chunk_id, proc_path FROM chunks
                WHERE state_name = ? AND field_name = ? AND status = 'COMPLETED';
            """, (state_name, field_name)).fetchall()

            for r in rows:
                cid = r["chunk_id"]
                p_path = r["proc_path"] or os.path.join(proc_field_dir, f"{cid}.json")

                is_valid = False
                if os.path.exists(p_path) and os.path.getsize(p_path) > 2:
                    try:
                        with open(p_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                is_valid = True
                                valid += 1
                    except Exception:
                        is_valid = False

                if not is_valid:
                    conn.execute("""
                        UPDATE chunks SET status = 'PENDING', records_count = 0, proc_path = NULL
                        WHERE state_name = ? AND field_name = ? AND chunk_id = ?;
                    """, (state_name, field_name, cid))
                    repaired += 1
                    logger.warning(f"[RECONCILE] Repaired orphaned chunk {cid}: file missing/invalid at {p_path}")

        if repaired > 0:
            self._sync_stats(state_name, field_name)
        return valid, repaired

    def export_to_legacy_json(self) -> None:
        legacy_data: Dict[str, Any] = {}
        with self._get_connection() as conn:
            fields = conn.execute("SELECT * FROM field_status;").fetchall()
            for f in fields:
                s_name = f["state_name"]
                f_name = f["field_name"]

                if s_name not in legacy_data:
                    legacy_data[s_name] = {}

                c_rows = conn.execute("""
                    SELECT chunk_id, status, error_message, raw_path, proc_path
                    FROM chunks WHERE state_name = ? AND field_name = ?;
                """, (s_name, f_name)).fetchall()

                completed_ids = [r["chunk_id"] for r in c_rows if r["status"] == "COMPLETED"]
                failed_ids = [r["chunk_id"] for r in c_rows if r["status"] == "FAILED" and r["chunk_id"] not in completed_ids]

                artifacts = {}
                for r in c_rows:
                    if r["status"] == "COMPLETED":
                        artifacts[r["chunk_id"]] = {
                            "raw": os.path.basename(r["raw_path"]) if r["raw_path"] else f"{r['chunk_id']}.json",
                            "processed": os.path.basename(r["proc_path"]) if r["proc_path"] else f"{r['chunk_id']}.json",
                        }

                legacy_data[s_name][f_name] = {
                    "state": s_name,
                    "state_code": f["state_code"],
                    "field_group": f["field_group"],
                    "field": f_name,
                    "status": f["status"],
                    "started_at": f["started_at"],
                    "completed_at": f["completed_at"],
                    "chunks_total": f["total_chunks"],
                    "chunks_completed": len(completed_ids),
                    "total_chunks": f["total_chunks"],
                    "completed_chunks": len(completed_ids),
                    "completed_chunk_ids": sorted(completed_ids),
                    "failed_chunk_ids": sorted(failed_ids),
                    "records_collected": f["records_collected"],
                    "chunk_artifacts": artifacts,
                    "stats": {
                        "total_chunks": f["total_chunks"],
                        "successful_chunks": len(completed_ids),
                        "failed_chunks": len(failed_ids),
                        "split_chunks": f["split_chunks"],
                        "records_collected": f["records_collected"],
                    }
                }

        tmp_json = f"{self.legacy_json_path}.tmp"
        try:
            with open(tmp_json, "w", encoding="utf-8") as out:
                json.dump(legacy_data, out, indent=2)
            os.replace(tmp_json, self.legacy_json_path)
        except Exception as e:
            logger.error(f"[CHECKPOINT] Failed writing legacy JSON: {e}")

    def get_all_status(self) -> Dict[str, Any]:
        """Returns comprehensive status dictionary for API endpoints."""
        self.export_to_legacy_json()
        if os.path.exists(self.legacy_json_path):
            try:
                with open(self.legacy_json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_field_status(self, state_name: str, field_name: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("""
                SELECT * FROM field_status
                WHERE state_name = ? AND field_name = ?;
            """, (state_name, field_name)).fetchone()
            return dict(row) if row else None

    def set_field_status(
        self,
        state_name: str,
        field_name: str,
        status: str,
        records_collected: int = 0,
        state_code: Optional[str] = None,
        field_group: Optional[str] = None
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO field_status (
                    state_name, field_name, state_code, field_group, status,
                    records_collected, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(state_name, field_name) DO UPDATE SET
                    status = excluded.status,
                    records_collected = excluded.records_collected,
                    updated_at = excluded.updated_at;
            """, (state_name, field_name, state_code, field_group, status, records_collected, now_iso))

    def sync_to_legacy_json(self) -> None:
        self.export_to_legacy_json()

    def get_summary(self) -> Dict[str, Any]:
        with self._get_connection() as conn:
            rows = conn.execute("""
                SELECT state_name,
                       COUNT(*) as total_fields,
                       SUM(CASE WHEN LOWER(status) = 'completed' THEN 1 ELSE 0 END) as completed_fields,
                       SUM(records_collected) as records
                FROM field_status
                GROUP BY state_name;
            """).fetchall()

            completed_states = [
                r["state_name"] for r in rows
                if (r["total_fields"] >= 13 and r["completed_fields"] == r["total_fields"])
            ]
            total_records = sum((r["records"] or 0) for r in rows)

            chunk_row = conn.execute("""
                SELECT COUNT(*) as total_chunks,
                       SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_chunks
                FROM chunks;
            """).fetchone()

            return {
                "completed_states": completed_states,
                "total_records_collected": total_records,
                "total_chunks_processed": chunk_row["completed_chunks"] if (chunk_row and chunk_row["completed_chunks"]) else 0,
                "states": {r["state_name"]: dict(r) for r in rows}
            }

