#!/usr/bin/env python3
"""
DataExtraction — Unified Single-Command Application Launcher
============================================================
Runs the entire enterprise stack with a single command:
  1. Validates PostgreSQL Database connection (localhost:5432)
  2. Ensures Temporal Dev Server is running (localhost:7233 & UI localhost:8233)
  3. Launches 7-Agent Temporal Worker Supervisor (scripts/ops/start_all_workers.py)
  4. Launches Backend FastAPI Gateway (http://localhost:8000)
     Override port with:  API_PORT=3001 python start.py
  5. Launches Frontend Next.js Dashboard (http://localhost:3000)

Usage:
  python start.py
  API_PORT=3001 python start.py
"""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# Force UTF-8 encoding on Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
VENV_PYTHON = sys.executable

# Prefer the repo-local .venv if it exists; otherwise fall back to current interpreter
_local_venv = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
if _local_venv.exists():
    VENV_PYTHON = str(_local_venv)

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Backend port: read from API_PORT env var (default 8000)
BACKEND_PORT = int(os.getenv("API_PORT", "8000"))


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Helper to check if a TCP port is currently open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_database() -> bool:
    """Verifies that PostgreSQL is running and accessible."""
    print("  [1/5] Checking PostgreSQL Database...")
    try:
        from packages.infrastructure.db_connector import get_connection, release_connection
        conn = get_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_user, version();")
                db_name, db_user, _ = cur.fetchone()
                cur.execute("SELECT count(*) FROM master_dataextraction.organizations;")
                org_count = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM master_dataextraction.persons;")
                person_count = cur.fetchone()[0]
            release_connection(conn)
            print(f"        -> SUCCESS: Connected to '{db_name}' as user '{db_user}'")
            print(f"        -> Master Organizations: {org_count:,} | Decision Makers: {person_count:,}")
            return True
        else:
            print("        -> WARNING: Database connection pool returned None.")
            return False
    except Exception as exc:
        print(f"        -> ERROR: Failed to connect to PostgreSQL: {exc}")
        print("           Please ensure PostgreSQL service is running on port 5432.")
        return False


def start_temporal():
    """Starts or verifies the local Temporal Server on port 7233 (UI 8233)."""
    print("  [2/5] Checking Temporal Orchestration Server...")
    if _is_port_open("127.0.0.1", 7233):
        print("        -> SUCCESS: Temporal Server already active on 127.0.0.1:7233 (UI: http://localhost:8233)")
        return None

    temporal_bin = PROJECT_ROOT / "bin" / ("temporal.exe" if sys.platform.startswith("win") else "temporal")
    if not temporal_bin.exists():
        temporal_bin = Path("temporal")  # fallback to PATH

    # Ensure data directory exists for persistent sqlite storage
    data_dir = PROJECT_ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    sqlite_db = data_dir / "temporal.sqlite"

    print("        -> Spawning local Temporal dev server daemon...")
    cmd = [
        str(temporal_bin), "server", "start-dev",
        "--namespace", "dataextraction",
        "--ip", "127.0.0.1",
        "--port", "7233",
        "--ui-port", "8233",
        "--db-filename", str(sqlite_db),
    ]

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        print(f"        -> ERROR launching temporal: {exc}")
        return None

    # Wait up to 15s for port 7233 to open
    for _ in range(30):
        if _is_port_open("127.0.0.1", 7233):
            print("        -> SUCCESS: Temporal Server ready on 127.0.0.1:7233 (UI: http://localhost:8233)")
            return proc
        time.sleep(0.5)

    print("        -> WARNING: Temporal server did not open port 7233 within timeout.")
    return proc


def start_workers():
    """Starts the 7-Agent Temporal Worker Supervisor."""
    print("  [3/5] Starting 7-Agent Worker Supervisor...")
    supervisor_script = PROJECT_ROOT / "scripts" / "ops" / "start_all_workers.py"
    if not supervisor_script.exists():
        print(f"        -> WARNING: Supervisor script not found at {supervisor_script}")
        return None

    cmd = [VENV_PYTHON, str(supervisor_script)]
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT),
    }

    try:
        proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print("        -> SUCCESS: 7-Agent Worker Supervisor active and polling queues.")
        return proc
    except Exception as exc:
        print(f"        -> ERROR starting worker supervisor: {exc}")
        return None


def start_backend():
    """Starts the FastAPI backend gateway."""
    print(f"  [4/5] Starting Backend API Gateway on port {BACKEND_PORT}...")
    env = {
        **os.environ,
        "PYTHONPATH": str(PROJECT_ROOT),
        "API_PORT": str(BACKEND_PORT),
    }
    cmd = [
        VENV_PYTHON, "-m", "uvicorn",
        "packages.api.main:app",
        "--host", "0.0.0.0",
        "--port", str(BACKEND_PORT),
        "--reload",
    ]
    return subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env,
                            stdout=sys.stdout, stderr=sys.stderr)


def start_frontend():
    """Starts the Next.js frontend application."""
    print("  [5/5] Starting Frontend Dashboard on port 3000...")
    is_windows = sys.platform.startswith("win")
    npm_cmd = "npm.cmd" if is_windows else "npm"
    cmd = [npm_cmd, "run", "dev"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(FRONTEND_DIR),
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    return proc


def print_banner():
    print("\n" + "=" * 70)
    print("   DATAEXTRACTION — ENTERPRISE B2B LEAD INTELLIGENCE PLATFORM")
    print("=" * 70)
    print(f"   * Database    : PostgreSQL on localhost:5432/dataextraction")
    print( "   * Temporal UI : http://localhost:8233 (gRPC: localhost:7233)")
    print(f"   * Backend API : http://localhost:{BACKEND_PORT}  (Docs: http://localhost:{BACKEND_PORT}/api/docs)")
    print( "   * Frontend UI : http://localhost:3000")
    print( "   * Agents (7)  : Supervised & Polling Dedicated Task Queues")
    print( "   * Press Ctrl+C at any time to stop all services.")
    print("=" * 70 + "\n")


def main():
    print_banner()

    # Step 1: Database Check
    db_ok = check_database()
    if not db_ok:
        print("\n[!] Proceeding with startup, but database queries may fail if PostgreSQL is offline.\n")

    # Step 2: Temporal Dev Server
    temporal_proc = start_temporal()
    time.sleep(1.0)

    # Step 3: Worker Supervisor
    workers_proc = start_workers()
    time.sleep(1.0)

    # Step 4: Backend Process
    backend_proc = start_backend()
    time.sleep(1.5)

    # Step 5: Frontend Process
    frontend_proc = start_frontend()

    print("\n[OK] All services running! Open your browser to http://localhost:3000\n")

    def signal_handler(sig, frame):
        print("\n\nShutting down all services cleanly...")
        for name, proc in [
            ("Frontend", frontend_proc),
            ("Backend", backend_proc),
            ("Workers", workers_proc),
            ("Temporal", temporal_proc),
        ]:
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
        for name, proc in [
            ("Frontend", frontend_proc),
            ("Backend", backend_proc),
            ("Workers", workers_proc),
            ("Temporal", temporal_proc),
        ]:
            if proc:
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
        print("All processes stopped. Goodbye!")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    try:
        while True:
            time.sleep(1)
            b_ret = backend_proc.poll() if backend_proc else None
            f_ret = frontend_proc.poll() if frontend_proc else None
            if b_ret is not None:
                print(f"[!] Backend process exited with code {b_ret}")
                signal_handler(None, None)
            if f_ret is not None:
                print(f"[!] Frontend process exited with code {f_ret}")
                signal_handler(None, None)
    except KeyboardInterrupt:
        signal_handler(None, None)


if __name__ == "__main__":
    main()


