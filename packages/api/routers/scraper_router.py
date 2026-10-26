"""
OneExtraction — Scraper Router
Endpoints:
  GET  /api/scraper/status  — Current status and record counts for each source
  POST /api/scraper/run     — Trigger background scraper execution with log capture
  POST /api/scraper/stop    — Graceful termination of running scraper subprocess
"""

import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps import UserPrincipal, get_current_user
from db_connector import get_connection, release_connection

logger = logging.getLogger("oneextraction.scraper")

router = APIRouter(tags=["scraper"])

_BASE = Path(__file__).resolve().parent.parent  # botasaurus/
_LOGS_DIR = _BASE / "output" / "logs" / "scrapers"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = {
    "cms": {
        "label": "CMS NPI",
        "script": "fetch_cms_npi.py",
        "args": ["--limit", "50000"],
    },
    "sec": {
        "label": "SEC EDGAR",
        "script": "fetch_sec_edgar.py",
        "args": [],
    },
    "fdic": {
        "label": "FDIC + NCUA",
        "script": "fetch_fdic.py",
        "args": [],
    },
    "usaspending": {
        "label": "USASpending",
        "script": "fetch_usaspending.py",
        "args": ["--limit", "50000"],
    },
    "propublica": {
        "label": "ProPublica 990",
        "script": "fetch_propublica.py",
        "args": ["--limit", "10000"],
    },
    "sam": {
        "label": "SAM.gov",
        "script": "fetch_sam_gov.py",
        "args": ["--limit", "50000"],
    },
}

_state: dict[str, dict] = {
    key: {
        "status": "idle",
        "records": 0,
        "last_run": None,
        "progress": 0,
        "message": "Ready",
    }
    for key in SOURCES
}

_procs: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()


# ── Request Models ─────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    source: str


class StopRequest(BaseModel):
    source: str


# ── DB Count Helper ────────────────────────────────────────────────────────────

_counts_cache: dict[str, int] = {}
_counts_cache_expiry: float = 0.0
_counts_lock = threading.Lock()
_COUNTS_CACHE_TTL: float = 30.0  # 30-second cache prevents repeated 1.87M row sequential scans on polling


def _get_all_db_counts(force_refresh: bool = False) -> dict:
    """Retrieves live record counts per source with a 30s TTL cache to prevent heavy scans on 1.8M rows."""
    global _counts_cache, _counts_cache_expiry
    now = time.monotonic()
    with _counts_lock:
        if not force_refresh and _counts_cache and now < _counts_cache_expiry:
            return _counts_cache.copy()

    src_map = {
        "cms": "CMS_NPI",
        "sec": "SEC_EDGAR",
        "fdic": "FDIC",
        "usaspending": "USASPENDING",
        "propublica": "PROPUBLICA_990",
        "sam": "SAM_GOV",
    }
    conn = get_connection()
    try:
        cur = conn.cursor()
        filter_parts = ", ".join(
            f'COUNT(1) FILTER (WHERE "api_source" = \'{v}\') AS "{k}"'
            for k, v in src_map.items()
        )
        cur.execute(f'SELECT {filter_parts} FROM "us_leads"')
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        cur.close()
        res = dict(zip(cols, row)) if row else {k: 0 for k in src_map}
        with _counts_lock:
            _counts_cache = res
            _counts_cache_expiry = time.monotonic() + _COUNTS_CACHE_TTL
        return res
    except Exception as e:
        logger.warning("Error fetching scraper DB counts: %s", e)
        return _counts_cache.copy() if _counts_cache else {k: 0 for k in src_map}
    finally:
        release_connection(conn)


# ── Worker Thread ──────────────────────────────────────────────────────────────

def _run_scraper_worker(key: str):
    """Executes scraper script as a managed subprocess, capturing stdout/stderr to disk."""
    src = SOURCES[key]
    script = _BASE / src["script"]
    args = src["args"]
    log_file = _LOGS_DIR / f"{key}.log"

    python_executable = sys.executable
    cmd = [python_executable, str(script)] + args

    with _lock:
        _state[key]["status"] = "running"
        _state[key]["message"] = f"Running {src['label']}..."
        _state[key]["progress"] = 10

    logger.info("Launching scraper process: %s -> %s", key, cmd)

    try:
        with open(log_file, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_BASE),
                stdout=lf,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
            )

        with _lock:
            _procs[key] = proc

        # Wait for completion
        exit_code = proc.wait()

        with _lock:
            _procs.pop(key, None)
            now_iso = datetime.now(timezone.utc).isoformat()
            if exit_code == 0:
                _state[key]["status"] = "completed"
                _state[key]["progress"] = 100
                _state[key]["last_run"] = now_iso
                _state[key]["message"] = "Execution finished successfully"
                logger.info("Scraper %s completed successfully", key)
                _get_all_db_counts(force_refresh=True)
            else:
                _state[key]["status"] = "failed"
                _state[key]["progress"] = 0
                _state[key]["last_run"] = now_iso
                _state[key]["message"] = f"Failed with exit code {exit_code}. Check {log_file.name}"
                logger.error("Scraper %s failed with code %d", key, exit_code)

    except Exception as e:
        logger.exception("Unexpected error in scraper worker for %s: %s", key, e)
        with _lock:
            _procs.pop(key, None)
            _state[key]["status"] = "failed"
            _state[key]["message"] = f"Execution error: {e}"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/scraper/status")
def get_scraper_status(user: UserPrincipal = Depends(get_current_user)):
    """Returns the current execution state and database record count for all scrapers."""
    counts = _get_all_db_counts()
    items = []

    with _lock:
        for key, src in SOURCES.items():
            # Check if process is still alive
            proc = _procs.get(key)
            if proc:
                poll = proc.poll()
                if poll is not None:
                    _procs.pop(key, None)
                    _state[key]["status"] = "completed" if poll == 0 else "failed"

            st = _state[key]
            items.append({
                "id": key,
                "label": src["label"],
                "status": st["status"],
                "records": counts.get(key, 0),
                "last_run": st["last_run"],
                "progress": st["progress"],
                "message": st["message"],
            })

    return items


@router.post("/scraper/run")
def run_scraper(
    body: RunRequest,
    user: UserPrincipal = Depends(get_current_user),
):
    """Triggers background execution of an extraction pipeline."""
    key = body.source.lower().strip()
    if key not in SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source: '{key}'. Valid sources: {list(SOURCES.keys())}",
        )

    with _lock:
        existing_proc = _procs.get(key)
        if existing_proc and existing_proc.poll() is None:
            raise HTTPException(
                status_code=409,
                detail=f"Scraper for '{key}' is already actively running.",
            )

    worker = threading.Thread(target=_run_scraper_worker, args=(key,), daemon=True)
    worker.start()

    logger.info("Scraper %s started by user=%s", key, user.email)
    return {
        "status": "started",
        "source": key,
        "label": SOURCES[key]["label"],
        "message": f"Scraper {SOURCES[key]['label']} has been launched in the background.",
    }


@router.post("/scraper/stop")
def stop_scraper(
    body: StopRequest,
    user: UserPrincipal = Depends(get_current_user),
):
    """Signals graceful termination of a running scraper subprocess."""
    key = body.source.lower().strip()
    with _lock:
        proc = _procs.get(key)
        if not proc or proc.poll() is not None:
            return {"status": "not_running", "source": key}

        try:
            proc.terminate()
            _state[key]["status"] = "stopped"
            _state[key]["message"] = "Terminated by operator"
            logger.info("Scraper %s terminated by user=%s", key, user.email)
        except Exception as e:
            logger.error("Error stopping scraper %s: %s", key, e)
            proc.kill()

        _procs.pop(key, None)

    return {"status": "stopped", "source": key}
