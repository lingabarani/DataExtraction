"""
OneExtraction — Map Extraction Engine API Router.
Provides RESTful management, real-time telemetry, asynchronous job execution,
and database deduplication ingestion for the OpenStreetMap Overpass extraction engine.

Endpoints:
  GET  /api/map-extraction/config                — Current Overpass configuration
  PUT  /api/map-extraction/config                — Dynamic runtime configuration update
  GET  /api/map-extraction/mirrors               — Real-time health, counters & cooldowns for mirror pool
  POST /api/map-extraction/mirrors/test          — Active probe test of Overpass API mirrors
  GET  /api/map-extraction/status                — State-by-state & field extraction progress metrics
  GET  /api/map-extraction/states                — 50 US states, bounding boxes, chunk estimations
  GET  /api/map-extraction/fields                — 13 POI taxonomy fields and query templates
  POST /api/map-extraction/start                 — Launch background extraction subprocess
  POST /api/map-extraction/stop                  — Graceful termination of extraction subprocess
  POST /api/map-extraction/ingest                — Batch deduplicated database ingestion
  GET  /api/map-extraction/export/{state}/{field}— Stream exported JSON or CSV files
  POST /api/map-extraction/reconcile             — Reconcile checkpoint database with disk state
"""

import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from api.deps import UserPrincipal, get_optional_user
from openmap_engine import (
    OverpassConfig,
    default_config,
    EndpointCircuitBreaker,
    AdaptiveQuadtree,
    EnterpriseCheckpointManager,
    OpenMapConnector,
    US_STATES,
    STATE_CODES,
    STATE_BOUNDING_BOXES,
    FIELDS_TAXONOMY,
    FIELD_BY_NAME,
    slugify,
    get_state_bbox,
    get_field_info,
)

logger = logging.getLogger("oneextraction.map_extraction_router")

router = APIRouter(prefix="/map-extraction", tags=["map-extraction"])

_BASE = Path(__file__).resolve().parent.parent  # botasaurus/
_REPO_ROOT = _BASE.parent
_ENGINE_DIR = _REPO_ROOT / "Open Map Extraction Engine"
_LOGS_DIR = _BASE / "output" / "logs" / "openmap"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Shared in-memory circuit breaker instance
_circuit_breaker = EndpointCircuitBreaker(
    endpoints=default_config.fallback_endpoints,
    failure_threshold=2,
    cooldown_sec=default_config.circuit_breaker_cooldown_sec,
)

# Background job tracking
_lock = threading.Lock()
_active_procs: Dict[str, subprocess.Popen] = {}
_task_metadata: Dict[str, Dict[str, Any]] = {}


# ── Request / Response Models ──────────────────────────────────────────────────

class ConfigUpdateRequest(BaseModel):
    primary_endpoint: Optional[str] = None
    fallback_endpoints: Optional[List[str]] = None
    custom_endpoint: Optional[str] = None
    connect_timeout_sec: Optional[int] = Field(None, ge=1, le=60)
    read_timeout_sec: Optional[int] = Field(None, ge=5, le=300)
    query_server_timeout_sec: Optional[int] = Field(None, ge=5, le=300)
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    backoff_factor: Optional[float] = Field(None, ge=1.0, le=5.0)
    circuit_breaker_cooldown_sec: Optional[float] = Field(None, ge=10.0, le=600.0)
    enable_adaptive_subdivision: Optional[bool] = None
    max_quadtree_depth: Optional[int] = Field(None, ge=0, le=6)
    chunk_size_deg: Optional[float] = Field(None, ge=0.05, le=5.0)
    min_chunk_deg: Optional[float] = Field(None, ge=0.01, le=1.0)
    rate_limit_delay_sec: Optional[float] = Field(None, ge=0.1, le=10.0)
    contact_email: Optional[str] = None
    user_agent: Optional[str] = None


class MirrorTestRequest(BaseModel):
    url: Optional[str] = None
    timeout_sec: Optional[int] = Field(5, ge=1, le=30)


class StartExtractionRequest(BaseModel):
    state: Optional[str] = None
    states: Optional[List[str]] = None
    field: Optional[str] = None
    fields: Optional[List[str]] = None
    resume: bool = True
    retry_affected: bool = False
    chunk_size_deg: Optional[float] = None
    dry_run: bool = False


class StopExtractionRequest(BaseModel):
    task_id: Optional[str] = None


class IngestRequest(BaseModel):
    state: Optional[str] = None
    field: Optional[str] = None
    file_path: Optional[str] = None
    dry_run: bool = False


class ReconcileRequest(BaseModel):
    dry_run: bool = False


# ── Configuration Endpoints ───────────────────────────────────────────────────

@router.get("/config")
def get_config(user: Optional[UserPrincipal] = Depends(get_optional_user)):
    """Returns the current runtime configuration for Overpass Open Map Extraction."""
    return {
        "primary_endpoint": default_config.primary_endpoint,
        "fallback_endpoints": default_config.fallback_endpoints,
        "custom_endpoint": default_config.custom_endpoint,
        "connect_timeout_sec": default_config.connect_timeout_sec,
        "read_timeout_sec": default_config.read_timeout_sec,
        "query_server_timeout_sec": default_config.query_server_timeout_sec,
        "max_retries": default_config.max_retries,
        "backoff_factor": default_config.backoff_factor,
        "circuit_breaker_cooldown_sec": default_config.circuit_breaker_cooldown_sec,
        "enable_adaptive_subdivision": default_config.enable_adaptive_subdivision,
        "max_quadtree_depth": default_config.max_quadtree_depth,
        "chunk_size_deg": default_config.chunk_size_deg,
        "min_chunk_deg": default_config.min_chunk_deg,
        "rate_limit_delay_sec": default_config.rate_limit_delay_sec,
        "contact_email": default_config.contact_email,
        "user_agent": default_config.user_agent,
    }


@router.put("/config")
def update_config(
    payload: ConfigUpdateRequest,
    user: Optional[UserPrincipal] = Depends(get_optional_user)
):
    updated_fields = {}
    dump_fn = getattr(payload, "model_dump", None) or getattr(payload, "dict")
    for key, val in dump_fn(exclude_unset=True).items():
        if val is not None and hasattr(default_config, key):
            setattr(default_config, key, val)
            updated_fields[key] = val

    if "fallback_endpoints" in updated_fields or "circuit_breaker_cooldown_sec" in updated_fields:
        global _circuit_breaker
        _circuit_breaker = EndpointCircuitBreaker(
            endpoints=default_config.fallback_endpoints,
            failure_threshold=2,
            cooldown_sec=default_config.circuit_breaker_cooldown_sec,
        )

    logger.info("Updated Overpass runtime config: %s", updated_fields)
    return {
        "status": "updated",
        "updated": updated_fields,
        "config": get_config(),
    }


# ── Mirror Health & Probing Endpoints ─────────────────────────────────────────

@router.get("/mirrors")
def get_mirrors_status(user: Optional[UserPrincipal] = Depends(get_optional_user)):
    """Returns real-time health, failure counters, and cooldown metrics for all Overpass mirrors."""
    now = time.time()
    mirror_list = []
    active_endpoint = _circuit_breaker.get_active_endpoint()

    for url in _circuit_breaker.endpoints:
        health = _circuit_breaker.registry.get(url)
        if not health:
            continue
        cooldown_remaining = max(0.0, round(health.cooldown_until - now, 1)) if not health.is_healthy else 0.0
        mirror_list.append({
            "url": url,
            "is_healthy": health.is_healthy,
            "is_active": (url == active_endpoint),
            "consecutive_failures": health.consecutive_failures,
            "total_failures": health.total_failures,
            "total_successes": health.total_successes,
            "last_status_code": health.last_status_code,
            "cooldown_remaining_sec": cooldown_remaining,
            "last_error_message": health.last_error_message,
        })

    healthy_count = sum(1 for m in mirror_list if m["is_healthy"])
    return {
        "total_mirrors": len(mirror_list),
        "healthy_mirrors": healthy_count,
        "active_mirror": active_endpoint,
        "mirrors": mirror_list,
    }


@router.post("/mirrors/test")
def test_mirrors(
    payload: MirrorTestRequest,
    user: Optional[UserPrincipal] = Depends(get_optional_user)
):
    """
    Actively probes specified mirror or all pool mirrors with a lightweight Overpass query.
    Updates circuit breaker state accordingly.
    """
    targets = [payload.url] if payload.url else list(_circuit_breaker.endpoints)
    results = []
    test_query = "[out:json][timeout:5]; node(1); out count;"

    for target_url in targets:
        t0 = time.time()
        try:
            resp = requests.post(
                target_url,
                data={"data": test_query},
                headers={"User-Agent": default_config.user_agent},
                timeout=(3, payload.timeout_sec or 5),
            )
            elapsed_ms = round((time.time() - t0) * 1000, 1)

            if resp.status_code == 200:
                _circuit_breaker.record_success(target_url)
                results.append({
                    "url": target_url,
                    "status_code": 200,
                    "latency_ms": elapsed_ms,
                    "is_healthy": True,
                    "error": None,
                })
            else:
                _circuit_breaker.record_failure(
                    target_url,
                    status_code=resp.status_code,
                    error_message=f"HTTP {resp.status_code}"
                )
                results.append({
                    "url": target_url,
                    "status_code": resp.status_code,
                    "latency_ms": elapsed_ms,
                    "is_healthy": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:100]}",
                })
        except Exception as exc:
            elapsed_ms = round((time.time() - t0) * 1000, 1)
            _circuit_breaker.record_failure(
                target_url,
                status_code=None,
                error_message=str(exc)
            )
            results.append({
                "url": target_url,
                "status_code": None,
                "latency_ms": elapsed_ms,
                "is_healthy": False,
                "error": str(exc),
            })

    return {
        "probed_count": len(results),
        "results": results,
    }


# ── Metadata Endpoints (States & Taxonomy) ────────────────────────────────────

@router.get("/states")
def get_states(user: Optional[UserPrincipal] = Depends(get_optional_user)):
    """Returns the 50 US states, geographical bounding boxes, estimated chunk counts, and completion status."""
    workspace = _ENGINE_DIR if _ENGINE_DIR.exists() else _BASE
    chk_mgr = EnterpriseCheckpointManager(str(workspace))
    summary = chk_mgr.get_summary()
    completed_states = set(summary.get("completed_states", []))

    states_out = []
    chunk_deg = default_config.chunk_size_deg

    for name, code in US_STATES:
        bbox = STATE_BOUNDING_BOXES.get(name, (0.0, 0.0, 0.0, 0.0))
        lat_span = abs(bbox[2] - bbox[0])
        lon_span = abs(bbox[3] - bbox[1])
        est_chunks = max(1, int(round((lat_span / chunk_deg) * (lon_span / chunk_deg))))

        is_done = name in completed_states
        states_out.append({
            "name": name,
            "code": code,
            "bbox": {
                "min_lat": bbox[0],
                "min_lon": bbox[1],
                "max_lat": bbox[2],
                "max_lon": bbox[3],
            },
            "estimated_chunks": est_chunks,
            "is_completed": is_done,
        })

    return {
        "total_states": len(states_out),
        "completed_states": len(completed_states),
        "states": states_out,
    }


@router.get("/fields")
def get_fields(user: Optional[UserPrincipal] = Depends(get_optional_user)):
    """Returns the 13 POI business category fields with category groups and query templates."""
    return {
        "total_fields": len(FIELDS_TAXONOMY),
        "fields": FIELDS_TAXONOMY,
    }


# ── Status & Progress Telemetry ───────────────────────────────────────────────

@router.get("/status")
def get_extraction_status(user: Optional[UserPrincipal] = Depends(get_optional_user)):
    """Returns detailed extraction progress across all states, chunks, and taxonomy fields."""
    workspace = _ENGINE_DIR if _ENGINE_DIR.exists() else _BASE
    chk_mgr = EnterpriseCheckpointManager(str(workspace))
    summary = chk_mgr.get_summary()

    # Check active jobs
    active_jobs = []
    with _lock:
        for tid, proc in list(_active_procs.items()):
            poll = proc.poll()
            meta = _task_metadata.get(tid, {})
            if poll is None:
                active_jobs.append({
                    "task_id": tid,
                    "state": meta.get("state"),
                    "field": meta.get("field"),
                    "started_at": meta.get("started_at"),
                    "status": "running",
                })
            else:
                _active_procs.pop(tid, None)
                if tid in _task_metadata:
                    _task_metadata[tid]["status"] = "completed" if poll == 0 else "failed"

    return {
        "status": "ok",
        "total_states": 50,
        "completed_states_count": len(summary.get("completed_states", [])),
        "completed_states": summary.get("completed_states", []),
        "total_records_collected": summary.get("total_records_collected", 0),
        "total_chunks_processed": summary.get("total_chunks_processed", 0),
        "active_jobs_count": len(active_jobs),
        "active_jobs": active_jobs,
        "sqlite_db_path": chk_mgr.db_path,
    }


# ── Background Extraction Worker Execution ────────────────────────────────────

def _run_extraction_subprocess(
    task_id: str,
    states: Optional[List[str]],
    fields: Optional[List[str]],
    resume: bool,
    retry_affected: bool,
    chunk_size: Optional[float],
    dry_run: bool
):
    """Executes OSM extraction as managed subprocess with full stdout/stderr capture."""
    script_path = _ENGINE_DIR / "src" / "osm_state_collector.py"
    if not script_path.exists():
        # Fallback if engine directory layout is nested
        script_path = _REPO_ROOT / "Open Map Extraction Engine" / "src" / "osm_state_collector.py"

    log_file = _LOGS_DIR / f"{task_id}.log"
    cmd = [sys.executable, str(script_path)]

    if states:
        cmd.extend(["--states", ",".join(states)])
    if fields:
        cmd.extend(["--fields", ",".join(fields)])
    if not resume:
        cmd.append("--no-resume")
    if retry_affected:
        cmd.append("--retry-affected")
    if chunk_size:
        cmd.extend(["--chunk-size", str(chunk_size)])

    logger.info("Starting Open Map Extraction task %s: %s", task_id, cmd)

    try:
        with open(log_file, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_ENGINE_DIR if _ENGINE_DIR.exists() else _BASE),
                stdout=lf,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
            )

        with _lock:
            _active_procs[task_id] = proc

        exit_code = proc.wait()

        with _lock:
            _active_procs.pop(task_id, None)
            if task_id in _task_metadata:
                _task_metadata[task_id]["status"] = "completed" if exit_code == 0 else "failed"
                _task_metadata[task_id]["completed_at"] = datetime.now(timezone.utc).isoformat()
                _task_metadata[task_id]["exit_code"] = exit_code

        logger.info("Extraction task %s finished with exit code %d", task_id, exit_code)

    except Exception as exc:
        logger.exception("Error running extraction task %s: %s", task_id, exc)
        with _lock:
            _active_procs.pop(task_id, None)
            if task_id in _task_metadata:
                _task_metadata[task_id]["status"] = "failed"
                _task_metadata[task_id]["error"] = str(exc)


@router.post("/start")
def start_extraction(
    payload: StartExtractionRequest,
    user: Optional[UserPrincipal] = Depends(get_optional_user)
):
    """
    Asynchronously starts the Open Map extraction process for requested states and taxonomy fields.
    Guarantees single active execution lock and redirects logs to disk.
    """
    with _lock:
        # Check if an existing task is already running
        running = [tid for tid, p in _active_procs.items() if p.poll() is None]
        if running:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An extraction process is already running (Task ID: {running[0]}). Terminate it first or wait for completion.",
            )

        task_id = f"osm_{uuid.uuid4().hex[:8]}"
        states = payload.states or ([payload.state] if payload.state else None)
        fields = payload.fields or ([payload.field] if payload.field else None)

        now_iso = datetime.now(timezone.utc).isoformat()
        _task_metadata[task_id] = {
            "task_id": task_id,
            "status": "running",
            "state": states[0] if states and len(states) == 1 else (", ".join(states) if states else "ALL"),
            "field": fields[0] if fields and len(fields) == 1 else (", ".join(fields) if fields else "ALL"),
            "started_at": now_iso,
            "log_file": str(_LOGS_DIR / f"{task_id}.log"),
        }

    # Launch background worker thread
    thread = threading.Thread(
        target=_run_extraction_subprocess,
        args=(
            task_id,
            states,
            fields,
            payload.resume,
            payload.retry_affected,
            payload.chunk_size_deg,
            payload.dry_run,
        ),
        daemon=True,
    )
    thread.start()

    return {
        "status": "started",
        "task_id": task_id,
        "states": states or "ALL",
        "fields": fields or "ALL",
        "started_at": now_iso,
        "log_path": str(_LOGS_DIR / f"{task_id}.log"),
    }


@router.post("/stop")
def stop_extraction(
    payload: StopExtractionRequest,
    user: Optional[UserPrincipal] = Depends(get_optional_user)
):
    """Gracefully terminates a running extraction subprocess."""
    with _lock:
        target_tid = payload.task_id
        if not target_tid:
            running = [tid for tid, p in _active_procs.items() if p.poll() is None]
            if not running:
                return {"status": "idle", "message": "No extraction task currently running."}
            target_tid = running[0]

        proc = _active_procs.get(target_tid)
        if not proc or proc.poll() is not None:
            _active_procs.pop(target_tid, None)
            return {"status": "stopped", "task_id": target_tid, "message": "Task is not running."}

        try:
            proc.terminate()
            # Give it a moment to terminate gracefully
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                proc.kill()
            _active_procs.pop(target_tid, None)
            if target_tid in _task_metadata:
                _task_metadata[target_tid]["status"] = "stopped"
                _task_metadata[target_tid]["stopped_at"] = datetime.now(timezone.utc).isoformat()

            logger.info("Terminated extraction task %s", target_tid)
            return {
                "status": "stopped",
                "task_id": target_tid,
                "message": f"Extraction task {target_tid} successfully terminated.",
            }
        except Exception as exc:
            logger.exception("Failed to terminate process %s: %s", target_tid, exc)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to terminate process: {exc}"
            )


# ── Ingestion & Deduplication Endpoint ────────────────────────────────────────

@router.post("/ingest")
def ingest_extracted_data(
    payload: IngestRequest,
    user: Optional[UserPrincipal] = Depends(get_optional_user)
):
    """
    Ingests exported OSM data into OneExtraction canonical companies/leads tables.
    Runs normalization, quality scoring, domain extraction, and deduplication.
    """
    connector = OpenMapConnector()

    try:
        if payload.file_path:
            records = connector.load_exported_file(payload.file_path)
        elif payload.state and payload.field:
            records = connector.load_state_field_export(payload.state, payload.field)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must specify either 'file_path' or both 'state' and 'field'.",
            )

        if not records:
            return {
                "status": "skipped",
                "message": "No records found in target export to ingest.",
                "stats": {"total_raw": 0, "inserted": 0, "updated": 0, "skipped": 0, "errors": 0},
            }

        stats = connector.ingest_records(
            records=records,
            dry_run=payload.dry_run
        )

        return {
            "status": "completed",
            "state": payload.state,
            "field": payload.field,
            "stats": stats,
        }

    except FileNotFoundError as fnf:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(fnf))
    except Exception as exc:
        logger.exception("Failed to ingest OSM records: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion failed: {exc}",
        )


# ── Export Streaming Endpoint ─────────────────────────────────────────────────

@router.get("/export/{state}/{field}")
def export_state_field_data(
    state: str,
    field: str,
    format: str = Query("json", pattern="^(json|csv)$"),
    user: Optional[UserPrincipal] = Depends(get_optional_user)
):
    """Streams exported JSON or CSV dataset for a given state and taxonomy field."""
    state_slug = slugify(state)
    field_clean = field.strip().lower()

    workspace = _ENGINE_DIR if _ENGINE_DIR.exists() else _BASE
    export_dir = workspace / "data" / "export" / state_slug
    target_file = export_dir / f"{field_clean}.{format}"

    if not target_file.exists():
        # Check alternative format
        alt_fmt = "csv" if format == "json" else "json"
        alt_file = export_dir / f"{field_clean}.{alt_fmt}"
        if not alt_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No exported {format.upper()} data found for state '{state}' field '{field}'. Run extraction first.",
            )
        target_file = alt_file
        format = alt_fmt

    media_type = "application/json" if format == "json" else "text/csv"
    return FileResponse(
        path=str(target_file),
        media_type=media_type,
        filename=f"osm_{state_slug}_{field_clean}.{format}",
    )


# ── Checkpoint & Disk Reconciliation Endpoint ─────────────────────────────────

@router.post("/reconcile")
def reconcile_checkpoints(
    payload: ReconcileRequest,
    user: Optional[UserPrincipal] = Depends(get_optional_user)
):
    """
    Reconciles SQLite checkpoint records against actual export files on disk.
    Repairs missing status tags and synchronizes legacy JSON checkpoints.
    """
    connector = OpenMapConnector()
    try:
        report = connector.reconcile_checkpoints(dry_run=payload.dry_run)
        return {
            "status": "reconciled",
            "report": report,
        }
    except Exception as exc:
        logger.exception("Reconciliation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reconciliation error: {exc}"
        )
