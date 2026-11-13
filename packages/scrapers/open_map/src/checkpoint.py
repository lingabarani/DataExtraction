"""
Enterprise ACID State Checkpoint Manager for Open Map Extraction Engine (PostgreSQL Enterprise Edition)
========================================================================================================
PostgreSQL-backed ACID state checkpoint manager replacing legacy SQLite implementation.
Features:
  - High-throughput connection pooling via packages.infrastructure.db_connector
  - Distributed worker lease locking with SELECT FOR UPDATE SKIP LOCKED
  - Zero local SQLite file locking or single-writer bottlenecks
  - Automatic synchronization to legacy JSON files for backward compatibility
"""

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from packages.infrastructure.db_connector import get_connection, release_connection

logger = logging.getLogger("OSMCheckpoint.Postgres")
_LEGACY_JSON_LOCK = threading.RLock()


class EnterpriseCheckpointManager:
    """
    Guarantees ACID crash safety, zero phantom duplicates, and reliable resume
    for state-by-state, field-by-field, chunk-by-chunk Overpass data collection
    using PostgreSQL 18 enterprise staging tables.
    """

    def __init__(self, workspace_dir: Optional[str] = None):
        self.workspace_dir = os.path.abspath(workspace_dir) if workspace_dir else os.getcwd()
        self.progress_dir = os.path.join(self.workspace_dir, "data", "progress")
        os.makedirs(self.progress_dir, exist_ok=True)
        self.legacy_json_path = os.path.join(self.progress_dir, "osm_progress.json")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Verifies PostgreSQL staging tables exist."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE SCHEMA IF NOT EXISTS staging_dataextraction;
                    CREATE TABLE IF NOT EXISTS staging_dataextraction.osm_chunks (
                        state_name VARCHAR(100) NOT NULL,
                        field_name VARCHAR(50) NOT NULL,
                        chunk_id VARCHAR(100) NOT NULL,
                        parent_id VARCHAR(100),
                        depth INT NOT NULL DEFAULT 0,
                        min_lat NUMERIC(10,7) NOT NULL,
                        min_lon NUMERIC(10,7) NOT NULL,
                        max_lat NUMERIC(10,7) NOT NULL,
                        max_lon NUMERIC(10,7) NOT NULL,
                        status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                        worker_id VARCHAR(100),
                        lease_expires_at TIMESTAMPTZ,
                        records_count INT NOT NULL DEFAULT 0,
                        raw_path TEXT,
                        proc_path TEXT,
                        raw_s3_key TEXT,
                        proc_s3_key TEXT,
                        error_message TEXT,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (state_name, field_name, chunk_id)
                    );
                    CREATE TABLE IF NOT EXISTS staging_dataextraction.osm_progress (
                        state_name VARCHAR(100) NOT NULL,
                        field_name VARCHAR(50) NOT NULL,
                        state_code VARCHAR(10),
                        field_group VARCHAR(50),
                        total_chunks INT NOT NULL DEFAULT 0,
                        completed_chunks INT NOT NULL DEFAULT 0,
                        failed_chunks INT NOT NULL DEFAULT 0,
                        split_chunks INT NOT NULL DEFAULT 0,
                        records_collected INT NOT NULL DEFAULT 0,
                        status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
                        started_at TIMESTAMPTZ DEFAULT NOW(),
                        completed_at TIMESTAMPTZ,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (state_name, field_name)
                    );
                """)
            conn.commit()
        finally:
            release_connection(conn)

    def init_field(
        self,
        state_name: str,
        state_code: str,
        field_name: str,
        field_group: str,
        total_chunks: int,
        chunks_info: List[Dict[str, Any]],
    ) -> None:
        """Initializes or updates field tracking with all state chunks in PostgreSQL."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staging_dataextraction.osm_progress (
                        state_name, field_name, state_code, field_group, status,
                        total_chunks, completed_chunks, failed_chunks, split_chunks,
                        records_collected, started_at, updated_at
                    ) VALUES (%s, %s, %s, %s, 'in_progress', %s, 0, 0, 0, 0, NOW(), NOW())
                    ON CONFLICT(state_name, field_name) DO UPDATE SET
                        total_chunks = EXCLUDED.total_chunks,
                        state_code = COALESCE(EXCLUDED.state_code, staging_dataextraction.osm_progress.state_code),
                        field_group = COALESCE(EXCLUDED.field_group, staging_dataextraction.osm_progress.field_group),
                        updated_at = NOW();
                    """,
                    (state_name, field_name, state_code, field_group, total_chunks),
                )

                # Batch insert chunks using execute_batch
                chunk_params = []
                for c in chunks_info:
                    cid = c["chunk_id"]
                    s, w, n, e = c["bbox"]
                    chunk_params.append((state_name, field_name, cid, s, w, n, e))

                if chunk_params:
                    from psycopg2.extras import execute_batch
                    execute_batch(
                        cur,
                        """
                        INSERT INTO staging_dataextraction.osm_chunks (
                            state_name, field_name, chunk_id, parent_id, depth,
                            min_lat, min_lon, max_lat, max_lon, status, updated_at
                        ) VALUES (%s, %s, %s, NULL, 0, %s, %s, %s, %s, 'PENDING', NOW())
                        ON CONFLICT (state_name, field_name, chunk_id) DO NOTHING;
                        """,
                        chunk_params,
                        page_size=1000,
                    )
            conn.commit()
            self._sync_stats(state_name, field_name)
        finally:
            release_connection(conn)

    def mark_chunk_in_progress(
        self,
        state_name: str,
        field_name: str,
        chunk_id: str,
        bbox: Tuple[float, float, float, float],
        depth: int = 0,
        parent_id: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> None:
        """Sets chunk status to IN_PROGRESS atomically with worker leasing."""
        s, w, n, e = bbox
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staging_dataextraction.osm_chunks (
                        state_name, field_name, chunk_id, parent_id, depth,
                        min_lat, min_lon, max_lat, max_lon, status, worker_id, lease_expires_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'IN_PROGRESS', %s, NOW() + INTERVAL '10 min', NOW())
                    ON CONFLICT(state_name, field_name, chunk_id) DO UPDATE SET
                        status = 'IN_PROGRESS',
                        worker_id = COALESCE(EXCLUDED.worker_id, staging_dataextraction.osm_chunks.worker_id),
                        lease_expires_at = NOW() + INTERVAL '10 min',
                        updated_at = NOW();
                    """,
                    (state_name, field_name, chunk_id, parent_id, depth, s, w, n, e, worker_id),
                )
            conn.commit()
        finally:
            release_connection(conn)

    def mark_chunk_completed(
        self,
        state_name: str,
        field_name: str,
        chunk_id: str,
        records_count: int,
        raw_path: str,
        proc_path: str,
    ) -> None:
        """Marks chunk as COMPLETED, clears error and lease."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging_dataextraction.osm_chunks SET
                        status = 'COMPLETED',
                        records_count = %s,
                        raw_path = %s,
                        proc_path = %s,
                        error_message = NULL,
                        lease_expires_at = NULL,
                        updated_at = NOW()
                    WHERE state_name = %s AND field_name = %s AND chunk_id = %s;
                    """,
                    (records_count, raw_path, proc_path, state_name, field_name, chunk_id),
                )
            conn.commit()
            self._sync_stats(state_name, field_name)
        finally:
            release_connection(conn)

    def mark_chunk_failed(
        self,
        state_name: str,
        field_name: str,
        chunk_id: str,
        error_message: str = "",
        error: Optional[str] = None,
    ) -> None:
        """Marks chunk as FAILED with error message."""
        err_msg = str(error or error_message or "Unknown failure")[:1000]
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging_dataextraction.osm_chunks SET
                        status = 'FAILED',
                        error_message = %s,
                        lease_expires_at = NULL,
                        updated_at = NOW()
                    WHERE state_name = %s AND field_name = %s AND chunk_id = %s;
                    """,
                    (err_msg, state_name, field_name, chunk_id),
                )
            conn.commit()
            self._sync_stats(state_name, field_name)
        finally:
            release_connection(conn)

    def mark_chunk_split(
        self,
        state_name: str,
        field_name: str,
        parent_chunk_id: str,
        child_chunks: List[Dict[str, Any]],
    ) -> None:
        """Marks parent chunk as SPLIT, and registers child quadrant chunks as PENDING."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging_dataextraction.osm_chunks SET status = 'SPLIT', lease_expires_at = NULL, updated_at = NOW()
                    WHERE state_name = %s AND field_name = %s AND chunk_id = %s;
                    """,
                    (state_name, field_name, parent_chunk_id),
                )

                for child in child_chunks:
                    cid = child["chunk_id"]
                    depth = child["depth"]
                    s, w, n, e = child["bbox"]
                    cur.execute(
                        """
                        INSERT INTO staging_dataextraction.osm_chunks (
                            state_name, field_name, chunk_id, parent_id, depth,
                            min_lat, min_lon, max_lat, max_lon, status, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'PENDING', NOW())
                        ON CONFLICT(state_name, field_name, chunk_id) DO UPDATE SET
                            status = 'PENDING',
                            updated_at = NOW();
                        """,
                        (state_name, field_name, cid, parent_chunk_id, depth, s, w, n, e),
                    )
            conn.commit()
            self._sync_stats(state_name, field_name)
        finally:
            release_connection(conn)

    def _sync_stats(self, state_name: str, field_name: str) -> None:
        """Synchronizes and recalculates aggregate chunk stats in PostgreSQL."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed,
                        SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
                        SUM(CASE WHEN status = 'SPLIT' THEN 1 ELSE 0 END) as split,
                        SUM(CASE WHEN status = 'COMPLETED' THEN records_count ELSE 0 END) as records
                    FROM staging_dataextraction.osm_chunks
                    WHERE state_name = %s AND field_name = %s;
                    """,
                    (state_name, field_name),
                )
                row = cur.fetchone()
                if row:
                    total = row[0] or 0
                    completed = row[1] or 0
                    failed = row[2] or 0
                    split = row[3] or 0
                    records = row[4] or 0

                    status = "completed" if (completed + split == total and failed == 0 and total > 0) else "in_progress"
                    
                    cur.execute(
                        """
                        UPDATE staging_dataextraction.osm_progress SET
                            completed_chunks = %s,
                            failed_chunks = %s,
                            split_chunks = %s,
                            records_collected = %s,
                            status = %s,
                            completed_at = CASE WHEN %s = 'completed' AND completed_at IS NULL THEN NOW() ELSE completed_at END,
                            updated_at = NOW()
                        WHERE state_name = %s AND field_name = %s;
                        """,
                        (completed, failed, split, records, status, status, state_name, field_name),
                    )
            conn.commit()
        finally:
            release_connection(conn)

    def get_completed_chunk_ids(self, state_name: str, field_name: str) -> Set[str]:
        """Returns set of all chunk_ids that have been COMPLETED."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chunk_id FROM staging_dataextraction.osm_chunks
                    WHERE state_name = %s AND field_name = %s AND status = 'COMPLETED';
                    """,
                    (state_name, field_name),
                )
                return {r[0] for r in cur.fetchall()}
        finally:
            release_connection(conn)

    def reclaim_expired_leases(self, state_name: str, field_name: str) -> int:
        """Resets expired IN_PROGRESS chunk leases back to PENDING so crashed workers recover cleanly."""
        conn = get_connection()
        if not conn:
            return 0
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging_dataextraction.osm_chunks
                    SET status = 'PENDING',
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        updated_at = NOW()
                    WHERE state_name = %s
                      AND field_name = %s
                      AND status = 'IN_PROGRESS'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at < NOW();
                    """,
                    (state_name, field_name),
                )
                reclaimed = cur.rowcount or 0
            conn.commit()
            if reclaimed:
                logger.info(
                    "[CHECKPOINT] Reclaimed %d expired IN_PROGRESS chunk leases for %s/%s",
                    reclaimed,
                    state_name,
                    field_name,
                )
            return reclaimed
        except Exception:
            conn.rollback()
            raise
        finally:
            release_connection(conn)

    def claim_pending_chunks(
        self,
        state_name: str,
        field_name: str,
        worker_id: str,
        limit: int = 10,
        lease_minutes: int = 10,
    ) -> List[Dict[str, Any]]:
        """Atomically claims pending/expired chunks via FOR UPDATE SKIP LOCKED."""
        conn = get_connection()
        if not conn:
            return []
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH next_chunks AS (
                        SELECT state_name, field_name, chunk_id
                        FROM staging_dataextraction.osm_chunks
                        WHERE state_name = %s
                          AND field_name = %s
                          AND (
                              status = 'PENDING'
                              OR (status = 'IN_PROGRESS' AND lease_expires_at IS NOT NULL AND lease_expires_at < NOW())
                          )
                        ORDER BY depth ASC, chunk_id ASC
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE staging_dataextraction.osm_chunks c
                    SET status = 'IN_PROGRESS',
                        worker_id = %s,
                        lease_expires_at = NOW() + (%s || ' minutes')::INTERVAL,
                        updated_at = NOW()
                    FROM next_chunks nc
                    WHERE c.state_name = nc.state_name
                      AND c.field_name = nc.field_name
                      AND c.chunk_id = nc.chunk_id
                    RETURNING c.chunk_id, c.min_lat, c.min_lon, c.max_lat, c.max_lon, c.depth, c.parent_id;
                    """,
                    (state_name, field_name, int(limit), worker_id, str(int(lease_minutes))),
                )
                rows = cur.fetchall()
            conn.commit()
            return [
                {
                    "chunk_id": r[0],
                    "bbox": (float(r[1]), float(r[2]), float(r[3]), float(r[4])),
                    "depth": int(r[5] or 0),
                    "parent_id": r[6],
                }
                for r in rows
            ]
        except Exception:
            conn.rollback()
            raise
        finally:
            release_connection(conn)

    def get_failed_chunk_ids(self, state_name: str, field_name: str) -> List[str]:
        """Returns list of chunk_ids that are currently FAILED."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chunk_id FROM staging_dataextraction.osm_chunks
                    WHERE state_name = %s AND field_name = %s AND status = 'FAILED'
                    ORDER BY depth, chunk_id;
                    """,
                    (state_name, field_name),
                )
                return [r[0] for r in cur.fetchall()]
        finally:
            release_connection(conn)

    def is_field_completed(self, state_name: str, field_name: str) -> bool:
        """Returns True if all chunks in field are COMPLETED or SPLIT and zero FAILED."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status FROM staging_dataextraction.osm_progress
                    WHERE state_name = %s AND field_name = %s;
                    """,
                    (state_name, field_name),
                )
                row = cur.fetchone()
                if row and row[0] == "completed":
                    return True

                cur.execute(
                    """
                    SELECT COUNT(*) FROM staging_dataextraction.osm_chunks
                    WHERE state_name = %s AND field_name = %s AND status NOT IN ('COMPLETED', 'SPLIT');
                    """,
                    (state_name, field_name),
                )
                cnt = cur.fetchone()[0]
                return cnt == 0
        finally:
            release_connection(conn)

    def reconcile_disk_state(
        self, state_name: str, field_name: str, proc_field_dir: str
    ) -> Tuple[int, int]:
        """Heuristic reconciliation validating processed files on disk against PostgreSQL."""
        if not os.path.exists(proc_field_dir):
            return (0, 0)

        actual_cids: Set[str] = set()
        for fname in os.listdir(proc_field_dir):
            if fname.endswith(".json"):
                actual_cids.add(fname[:-5])

        db_completed = self.get_completed_chunk_ids(state_name, field_name)
        recovered_count = 0

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                for cid in actual_cids - db_completed:
                    fpath = os.path.join(proc_field_dir, f"{cid}.json")
                    try:
                        sz = os.path.getsize(fpath)
                        if sz > 2:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                data = json.load(f)
                            cnt = len(data) if isinstance(data, list) else 1
                            cur.execute(
                                """
                                UPDATE staging_dataextraction.osm_chunks SET
                                    status = 'COMPLETED',
                                    records_count = %s,
                                    proc_path = %s,
                                    lease_expires_at = NULL,
                                    updated_at = NOW()
                                WHERE state_name = %s AND field_name = %s AND chunk_id = %s;
                                """,
                                (cnt, fpath, state_name, field_name, cid),
                            )
                            recovered_count += 1
                    except Exception:
                        pass
            conn.commit()
            if recovered_count > 0:
                self._sync_stats(state_name, field_name)
        finally:
            release_connection(conn)

        return (len(actual_cids), recovered_count)

    def get_field_status(self, state_name: str, field_name: str) -> Optional[Dict[str, Any]]:
        """Returns the current progress dict for a field."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT state_name, field_name, state_code, field_group, status,
                           total_chunks, completed_chunks, failed_chunks, split_chunks,
                           records_collected, started_at, completed_at, updated_at
                    FROM staging_dataextraction.osm_progress
                    WHERE state_name = %s AND field_name = %s;
                    """,
                    (state_name, field_name),
                )
                row = cur.fetchone()
                if row:
                    return {
                        "state_name": row[0],
                        "field_name": row[1],
                        "state_code": row[2],
                        "field_group": row[3],
                        "status": row[4],
                        "total_chunks": row[5],
                        "completed_chunks": row[6],
                        "failed_chunks": row[7],
                        "split_chunks": row[8],
                        "records_collected": row[9],
                        "started_at": row[10].isoformat() if row[10] else None,
                        "completed_at": row[11].isoformat() if row[11] else None,
                        "updated_at": row[12].isoformat() if row[12] else None,
                    }
                return None
        finally:
            release_connection(conn)

    def set_field_status(
        self,
        state_name: str,
        field_name: str,
        status: str,
        records_collected: int = 0,
        state_code: Optional[str] = None,
        field_group: Optional[str] = None,
    ) -> None:
        """Sets field-level status directly in PostgreSQL."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO staging_dataextraction.osm_progress (
                        state_name, field_name, state_code, field_group, status,
                        records_collected, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT(state_name, field_name) DO UPDATE SET
                        status = EXCLUDED.status,
                        records_collected = CASE WHEN EXCLUDED.records_collected > 0 THEN EXCLUDED.records_collected ELSE staging_dataextraction.osm_progress.records_collected END,
                        completed_at = CASE WHEN EXCLUDED.status = 'completed' AND staging_dataextraction.osm_progress.completed_at IS NULL THEN NOW() ELSE staging_dataextraction.osm_progress.completed_at END,
                        updated_at = NOW();
                    """,
                    (state_name, field_name, state_code, field_group, status, records_collected),
                )
            conn.commit()
        finally:
            release_connection(conn)

    def export_to_legacy_json(self) -> None:
        """Atomically exports current PostgreSQL progress to backward-compatible osm_progress.json."""
        summary = self.get_summary()
        with _LEGACY_JSON_LOCK:
            tmp_path = None
            try:
                os.makedirs(self.progress_dir, exist_ok=True)
                fd, tmp_path = tempfile.mkstemp(prefix="osm_progress_", suffix=".tmp", dir=self.progress_dir)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(summary, f, indent=2, default=str)
                os.replace(tmp_path, self.legacy_json_path)
            except Exception as exc:
                logger.warning("Failed to export legacy JSON: %s", exc)
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    def sync_to_legacy_json(self) -> None:
        """Alias for export_to_legacy_json."""
        self.export_to_legacy_json()

    def sync_legacy_json(self) -> None:
        """Backward-compatible alias for export_to_legacy_json."""
        self.export_to_legacy_json()

    def get_summary(self) -> Dict[str, Any]:
        """Returns full hierarchy summary from PostgreSQL."""
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM staging_dataextraction.osm_progress ORDER BY state_name, field_name;")
                cols = [desc[0] for desc in cur.description]
                fields = [dict(zip(cols, r)) for r in cur.fetchall()]

                result: Dict[str, Any] = {}
                for f in fields:
                    s_name = f["state_name"]
                    f_name = f["field_name"]
                    if s_name not in result:
                        result[s_name] = {
                            "state_name": s_name,
                            "state_code": f.get("state_code", ""),
                            "fields": {},
                        }

                    cur.execute(
                        """
                        SELECT chunk_id, status, records_count, depth, error_message
                        FROM staging_dataextraction.osm_chunks
                        WHERE state_name = %s AND field_name = %s;
                        """,
                        (s_name, f_name),
                    )
                    c_cols = ["chunk_id", "status", "records_count", "depth", "error_message"]
                    c_rows = [dict(zip(c_cols, cr)) for cr in cur.fetchall()]

                    chunks_dict = {
                        c["chunk_id"]: {
                            "status": c["status"],
                            "records": c["records_count"],
                            "depth": c["depth"],
                            "error": c["error_message"],
                        }
                        for c in c_rows
                    }

                    result[s_name]["fields"][f_name] = {
                        "status": f["status"],
                        "total_chunks": f["total_chunks"],
                        "completed_chunks": f["completed_chunks"],
                        "failed_chunks": f["failed_chunks"],
                        "split_chunks": f["split_chunks"],
                        "records_collected": f["records_collected"],
                        "chunks": chunks_dict,
                    }
                return result
        finally:
            release_connection(conn)
