#!/usr/bin/env python3
"""
DataExtraction — Unified Single-Command Application Launcher
============================================================
Runs the entire stack with a single command:
  1. Validates and connects to PostgreSQL Database (localhost:5432)
  2. Launches Backend FastAPI Gateway (http://localhost:3001)
  3. Launches Frontend Next.js Dashboard (http://localhost:3000)

Usage:
  python start.py
"""

import os
import signal
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

potential_venvs = [
    PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
    Path(r"D:\Data Scraping Project POC\OneExtraction\.venv\Scripts\python.exe"),
]
for p in potential_venvs:
    if p.exists():
        VENV_PYTHON = str(p)
        break

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def check_database() -> bool:
    """Verifies that PostgreSQL is running and accessible."""
    print("  [1/3] Checking PostgreSQL Database...")
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


def start_backend():
    """Starts the FastAPI backend gateway."""
    print("  [2/3] Starting Backend API Gateway on port 3001...")
    cmd = [
        VENV_PYTHON,
        "-m",
        "uvicorn",
        "packages.api.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "3001",
        "--reload",
    ]
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    return proc


def start_frontend():
    """Starts the Next.js frontend application."""
    print("  [3/3] Starting Frontend Dashboard on port 3000...")
    # Use npx / npm run dev
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
    print("   * Database  : PostgreSQL on localhost:5432/dataextraction")
    print("   * Backend   : http://localhost:3001  (Docs: http://localhost:3001/docs)")
    print("   * Frontend  : http://localhost:3000")
    print("   * Press Ctrl+C at any time to stop all services.")
    print("=" * 70 + "\n")


def main():
    print_banner()

    # Step 1: Database Check
    db_ok = check_database()
    if not db_ok:
        print("\n[!] Proceeding with startup, but database queries may fail if PostgreSQL is offline.\n")

    # Step 2: Backend Process
    backend_proc = start_backend()
    time.sleep(1.5)

    # Step 3: Frontend Process
    frontend_proc = start_frontend()

    print("\n[OK] All services running! Open your browser to http://localhost:3000\n")

    def signal_handler(sig, frame):
        print("\n\nShutting down all services cleanly...")
        try:
            backend_proc.terminate()
        except Exception:
            pass
        try:
            frontend_proc.terminate()
        except Exception:
            pass
        try:
            backend_proc.wait(timeout=3)
            frontend_proc.wait(timeout=3)
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
            # Check if any process exited unexpectedly
            b_ret = backend_proc.poll()
            f_ret = frontend_proc.poll()
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

