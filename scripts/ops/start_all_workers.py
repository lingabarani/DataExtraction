"""
DataExtraction — 7-Agent Temporal Worker Supervisor
===================================================
Supervises all 7 dedicated agent worker daemons across their respective
canonical task queues:
  - Agent 1: Registry Harvester           (registry-ingestion-queue)
  - Agent 2: Geospatial & Domain          (geospatial-domain-queue)
  - Agent 3: Identity Resolution & Splink (identity-clustering-queue)
  - Agent 7: Email Discovery & 5-Tier Val (email-enrichment-queue)
  - Agent 4: Executive & Career Contact   (executive-contact-queue)
  - Agent 5: Governance, Quality & Bayes  (governance-quality-queue)
  - Agent 6: Search, CDC & OneReach Sync  (search-persistence-queue)

Features:
  - Temporal connection pre-flight probe with exponential backoff
  - Subprocess supervision with crash restart and exponential backoff
  - Graceful coordinated shutdown on SIGINT/SIGTERM (no orphaned daemons)
"""

import logging
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("worker-supervisor")


@dataclass
class WorkerSpec:
    id: str
    name: str
    module: str
    queue: str
    restart_count: int = 0
    last_restart: float = 0.0
    process: Optional[subprocess.Popen] = None


WORKERS_SPEC = [
    WorkerSpec(
        id="worker-1-registry",
        name="Agent 1: Official Registry Harvester",
        module="packages.temporal.workers.worker_registry",
        queue="registry-ingestion-queue",
    ),
    WorkerSpec(
        id="worker-2-geospatial",
        name="Agent 2: Geospatial & Domain Harvester",
        module="packages.temporal.workers.worker_geospatial",
        queue="geospatial-domain-queue",
    ),
    WorkerSpec(
        id="worker-3-identity",
        name="Agent 3: Identity & Splink Clustering",
        module="packages.temporal.workers.worker_identity",
        queue="identity-clustering-queue",
    ),
    WorkerSpec(
        id="worker-7-email",
        name="Agent 7: Email Discovery & Verification",
        module="packages.temporal.workers.worker_email_enrichment",
        queue="email-enrichment-queue",
    ),
    WorkerSpec(
        id="worker-4-executive",
        name="Agent 4: Executive Contact Intelligence",
        module="packages.temporal.workers.worker_executive",
        queue="executive-contact-queue",
    ),
    WorkerSpec(
        id="worker-5-governance",
        name="Agent 5: Governance & Bayesian Quality",
        module="packages.temporal.workers.worker_governance",
        queue="governance-quality-queue",
    ),
    WorkerSpec(
        id="worker-6-search",
        name="Agent 6: Search, CDC & Outbound Sync",
        module="packages.temporal.workers.worker_search",
        queue="search-persistence-queue",
    ),
]


def is_temporal_ready(host_str: str, timeout: float = 1.0) -> bool:
    """Probes Temporal TCP port."""
    try:
        parts = host_str.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 7233
        if host in ("localhost", "0.0.0.0"):
            host = "127.0.0.1"
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def wait_for_temporal(host_str: str, max_wait_seconds: int = 30) -> bool:
    """Waits for Temporal server to be reachable before launching workers."""
    logger.info("Probing Temporal cluster availability at %s...", host_str)
    deadline = time.time() + max_wait_seconds
    delay = 1.0
    while time.time() < deadline:
        if is_temporal_ready(host_str):
            logger.info("Temporal cluster detected online at %s", host_str)
            return True
        logger.warning("Temporal port not reachable at %s. Retrying in %.1fs...", host_str, delay)
        time.sleep(delay)
        delay = min(delay * 1.5, 5.0)
    return False


def spawn_worker(spec: WorkerSpec, env: Dict[str, str]) -> subprocess.Popen:
    """Spawns a worker daemon as a Python subprocess."""
    cmd = [sys.executable, "-m", spec.module]
    logger.info("Spawning [%s] on queue '%s' (module: %s)", spec.name, spec.queue, spec.module)
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        stdout=None,
        stderr=None,
    )
    spec.process = proc
    logger.info("Spawned [%s] with PID %d", spec.name, proc.pid)
    return proc


def terminate_all_workers(specs: List[WorkerSpec]):
    """Gracefully terminates all child worker processes."""
    logger.info("Initiating graceful shutdown for all %d worker daemons...", len(specs))
    for spec in specs:
        if spec.process and spec.process.poll() is None:
            logger.info("Terminating PID %d (%s)...", spec.process.pid, spec.name)
            spec.process.terminate()

    # Wait up to 5 seconds for clean exit
    deadline = time.time() + 5.0
    for spec in specs:
        if spec.process and spec.process.poll() is None:
            remaining = max(0.1, deadline - time.time())
            try:
                spec.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                logger.warning("Worker PID %d (%s) did not exit. Forcing kill...", spec.process.pid, spec.name)
                spec.process.kill()


def main():
    host_str = os.getenv("TEMPORAL_HOST", "localhost:7233")
    if not wait_for_temporal(host_str, max_wait_seconds=15):
        logger.error(
            "Temporal cluster at %s is OFFLINE. Cannot start workers without Temporal Server.\n"
            "Hint: Start the server using 'python scripts/ops/start_temporal_server.py'",
            host_str,
        )
        sys.exit(1)

    worker_env = dict(os.environ)
    worker_env["PYTHONPATH"] = str(REPO_ROOT)
    worker_env.setdefault("TEMPORAL_HOST", host_str)
    worker_env.setdefault("TEMPORAL_NAMESPACE", os.getenv("TEMPORAL_NAMESPACE", "dataextraction"))

    # Spawn all 7 workers
    for spec in WORKERS_SPEC:
        spawn_worker(spec, worker_env)
        time.sleep(0.5)

    shutdown_flag = False

    def handle_signal(signum, frame):
        nonlocal shutdown_flag
        if not shutdown_flag:
            shutdown_flag = True
            logger.info("Signal %s received by supervisor. Shutting down...", signum)
            terminate_all_workers(WORKERS_SPEC)
            sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("All 7 Worker Daemons running and supervised. Press Ctrl+C to stop.")

    # Supervision loop: monitor health and restart on abnormal crash
    while not shutdown_flag:
        time.sleep(2.0)
        for spec in WORKERS_SPEC:
            if spec.process is None:
                continue
            retcode = spec.process.poll()
            if retcode is not None:
                logger.warning("Worker [%s] (PID %d) exited unexpectedly with code %d", spec.name, spec.process.pid, retcode)
                now = time.time()
                spec.restart_count += 1
                if now - spec.last_restart < 5.0 and spec.restart_count > 5:
                    logger.critical("Worker [%s] is crashing in a rapid loop (%d restarts). Pausing restart.", spec.name, spec.restart_count)
                    continue
                spec.last_restart = now
                logger.info("Restarting [%s] (attempt #%d)...", spec.name, spec.restart_count)
                spawn_worker(spec, worker_env)


if __name__ == "__main__":
    main()

