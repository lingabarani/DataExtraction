"""
DataExtraction — Enterprise Temporal Server Runner
=================================================
Launches and monitors the local Temporal Durable Orchestration Server
on port 7233 with namespace 'dataextraction' and Web UI on port 8233.

Usage:
  python scripts/ops/start_temporal_server.py [--port 7233] [--namespace dataextraction] [--persist]
"""

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BIN_TEMPORAL = REPO_ROOT / "bin" / "temporal.exe"
DATA_DIR = REPO_ROOT / "data"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("temporal-runner")


def find_temporal_binary() -> str:
    """Finds available temporal executable."""
    if BIN_TEMPORAL.exists():
        return str(BIN_TEMPORAL)
    which_bin = shutil.which("temporal")
    if which_bin:
        return which_bin
    # Check Temp directory from Python SDK download
    temp_dir = Path(os.getenv("TEMP", "C:/Users/Lingabarini M/AppData/Local/Temp"))
    candidates = list(temp_dir.glob("temporal-sdk-python-*.exe"))
    if candidates:
        return str(candidates[0])
    raise FileNotFoundError(
        "Temporal executable not found. Run 'python scripts/ops/start_temporal_server.py' after building bin/temporal.exe"
    )


def main():
    parser = argparse.ArgumentParser(description="Start Temporal Local Server")
    parser.add_argument("--port", type=int, default=int(os.getenv("TEMPORAL_PORT", "7233")), help="gRPC port (default: 7233)")
    parser.add_argument("--ui-port", type=int, default=8233, help="Web UI port (default: 8233)")
    parser.add_argument("--namespace", type=str, default=os.getenv("TEMPORAL_NAMESPACE", "dataextraction"), help="Namespace to create (default: dataextraction)")
    parser.add_argument("--persist", action="store_true", help="Persist workflow state to SQLite in data/temporal.sqlite")
    parser.add_argument("--ip", type=str, default="127.0.0.1", help="Binding IP (default: 127.0.0.1)")
    args = parser.parse_args()

    bin_path = find_temporal_binary()
    logger.info("Using Temporal binary at: %s", bin_path)

    cmd = [
        bin_path,
        "server",
        "start-dev",
        "--ip", args.ip,
        "--port", str(args.port),
        "--ui-port", str(args.ui_port),
        "--namespace", args.namespace,
    ]

    if args.persist:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        db_file = DATA_DIR / "temporal.sqlite"
        cmd.extend(["--db-filename", str(db_file)])

    logger.info("Executing: %s", " ".join(cmd))
    logger.info("Temporal Web UI will be accessible at: http://localhost:%d", args.ui_port)
    logger.info("Temporal gRPC endpoint: %s:%d (Namespace: %s)", args.ip, args.port, args.namespace)

    proc = subprocess.Popen(cmd)

    def _shutdown(signum, frame):
        logger.info("Received termination signal %s. Shutting down Temporal Server...", signum)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        proc.wait()
    except KeyboardInterrupt:
        _shutdown(signal.SIGINT, None)


if __name__ == "__main__":
    main()

