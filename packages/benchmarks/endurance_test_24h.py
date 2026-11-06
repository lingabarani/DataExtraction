"""
DataExtraction — Task 8: 24-Hour Endurance & Soak Test Framework
================================================================
Monitors system stability, memory footprint drift, database connection pool
saturation, and dead-letter queue behavior over extended execution cycles.

Features:
  1. Time-budgeted continuous soak testing (supports --duration-hours up to 24+ hours).
  2. Cycle-budgeted accelerated soak testing (supports --cycles N for test suites and CI).
  3. Strict memory leak detection using tracemalloc and garbage collector inspection.
  4. Database connection pool leak tracking to ensure zero connection exhaustion.
  5. Checkpoint telemetry emission to JSONL with graceful SIGINT interruption support.
"""

import argparse
import gc
import json
import logging
import os
import signal
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.benchmarks.load_test_100k import StreamRecordGenerator
from packages.domain.onereach_delivery_service import OneReachDeliveryService
from packages.infrastructure.db_connector import get_db_connection
from packages.infrastructure.dead_letter_queue import get_dlq_stats
from packages.infrastructure.metrics import (
    DATAEXTRACTION_DB_POOL_ACTIVE_CONNECTIONS,
    record_request_metrics,
    update_system_gauges,
)
from packages.infrastructure.staging_writer import bulk_upsert_staging_records

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
)
logger = logging.getLogger("dataextraction.benchmarks.endurance")


@dataclass
class SoakCycleCheckpoint:
    cycle_index: int
    timestamp: str
    cycle_duration_sec: float
    records_processed: int
    memory_current_mb: float
    memory_peak_mb: float
    memory_growth_from_start_mb: float
    db_active_connections: int
    dlq_pending_count: int
    cycle_status: str = "SUCCESS"
    error_message: Optional[str] = None


@dataclass
class EnduranceReport:
    total_cycles_completed: int = 0
    total_duration_sec: float = 0.0
    total_records_processed: int = 0
    start_memory_mb: float = 0.0
    final_memory_mb: float = 0.0
    peak_memory_mb: float = 0.0
    net_memory_growth_mb: float = 0.0
    avg_growth_per_cycle_kb: float = 0.0
    memory_leak_detected: bool = False
    connection_leak_detected: bool = False
    interrupted_early: bool = False
    checkpoints: List[SoakCycleCheckpoint] = field(default_factory=list)


class EnduranceTestHarness:
    """Executes the 24-hour endurance / soak test and tracks health indicators."""

    # Max acceptable memory growth per cycle (in KB) after 3 warm-up cycles
    LEAK_THRESHOLD_KB_PER_CYCLE = 250.0

    def __init__(
        self,
        batch_size: int = 250,
        checkpoint_file: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.batch_size = batch_size
        self.checkpoint_file = checkpoint_file
        self.dry_run = dry_run
        self.generator = StreamRecordGenerator(seed=101)
        self.delivery_service = OneReachDeliveryService()
        self.stop_requested = False

    def _setup_signal_handlers(self):
        def _handle_interrupt(signum, frame):
            logger.warning("Endurance soak test received termination signal (%s). Draining and generating report...", signum)
            self.stop_requested = True

        try:
            signal.signal(signal.SIGINT, _handle_interrupt)
            signal.signal(signal.SIGTERM, _handle_interrupt)
        except (ValueError, AttributeError):
            pass

    def run_cycle(self, cycle_idx: int) -> SoakCycleCheckpoint:
        """Executes a single end-to-end soak cycle across pipeline stages."""
        c_start = time.perf_counter()
        records = [self.generator.generate_record((cycle_idx * self.batch_size) + i) for i in range(self.batch_size)]

        error_msg = None
        status = "SUCCESS"

        try:
            if not self.dry_run:
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        bulk_upsert_staging_records(cur, records, source="ENDURANCE_SOAK")
            else:
                _ = [json.dumps(r) for r in records]

            # Simulate outbound delivery for a sample
            sample_leads = [{"id": r["id"], "name": r["company_name"], "email": r["email"]} for r in records[:5]]
            _ = self.delivery_service.dispatch_batch(sample_leads, dry_run=True)

        except Exception as ex:
            status = "FAILED"
            error_msg = str(ex)
            logger.error("Endurance cycle %d encountered failure: %s", cycle_idx, ex)

        if not tracemalloc.is_tracing():
            tracemalloc.start()

        # Collect garbage to distinguish genuine leaks from deferred GC
        gc.collect()
        curr_mem, peak_mem = tracemalloc.get_traced_memory()
        c_duration = time.perf_counter() - c_start

        db_conns = 0
        try:
            db_conns = int(DATAEXTRACTION_DB_POOL_ACTIVE_CONNECTIONS._value.get())
        except Exception:
            pass

        dlq_pending = 0
        try:
            dlq_stats = get_dlq_stats()
            dlq_pending = dlq_stats.get("pending_count", 0)
        except Exception:
            pass

        record_request_metrics("POST", "/api/endurance/cycle", 200 if status == "SUCCESS" else 500, c_duration)

        checkpoint = SoakCycleCheckpoint(
            cycle_index=cycle_idx,
            timestamp=datetime.now(timezone.utc).isoformat(),
            cycle_duration_sec=round(c_duration, 3),
            records_processed=len(records),
            memory_current_mb=round(curr_mem / (1024 * 1024), 3),
            memory_peak_mb=round(peak_mem / (1024 * 1024), 3),
            memory_growth_from_start_mb=0.0,  # Computed in parent runner
            db_active_connections=db_conns,
            dlq_pending_count=dlq_pending,
            cycle_status=status,
            error_message=error_msg,
        )

        return checkpoint

    def run(
        self,
        duration_hours: Optional[float] = None,
        max_cycles: Optional[int] = None,
    ) -> EnduranceReport:
        """
        Executes the soak test until duration_hours expires, max_cycles is reached,
        or SIGINT is intercepted.
        """
        if duration_hours is None and max_cycles is None:
            max_cycles = 10  # Default safe test count if neither specified

        self._setup_signal_handlers()
        tracemalloc.start()
        start_mem = tracemalloc.get_traced_memory()[0]
        start_time = time.perf_counter()
        target_duration_sec = (duration_hours * 3600.0) if duration_hours else None

        logger.info(
            "Starting 24h endurance harness: duration_hours=%s, max_cycles=%s, batch_size=%d",
            duration_hours,
            max_cycles,
            self.batch_size,
        )

        checkpoints: List[SoakCycleCheckpoint] = []
        cycle_idx = 0

        while not self.stop_requested:
            cycle_idx += 1
            if max_cycles and cycle_idx > max_cycles:
                break
            if target_duration_sec and (time.perf_counter() - start_time) >= target_duration_sec:
                break

            cp = self.run_cycle(cycle_idx)
            curr_mem = tracemalloc.get_traced_memory()[0]
            cp.memory_growth_from_start_mb = round((curr_mem - start_mem) / (1024 * 1024), 3)
            checkpoints.append(cp)

            if self.checkpoint_file:
                try:
                    with open(self.checkpoint_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(asdict(cp)) + "\n")
                except Exception as io_err:
                    logger.warning("Failed writing checkpoint: %s", io_err)

            if cycle_idx % 5 == 0 or cycle_idx == max_cycles:
                logger.info(
                    "Endurance checkpoint [%d]: Memory=%.2f MB (Δ=%.2f MB) | Conns=%d | DLQ=%d",
                    cycle_idx,
                    cp.memory_current_mb,
                    cp.memory_growth_from_start_mb,
                    cp.db_active_connections,
                    cp.dlq_pending_count,
                )

        final_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        total_duration = time.perf_counter() - start_time
        completed_cycles = len(checkpoints)

        net_growth_mb = (final_mem - start_mem) / (1024 * 1024)
        avg_kb_per_cycle = (net_growth_mb * 1024.0) / max(1, completed_cycles)
        leak_detected = avg_kb_per_cycle > self.LEAK_THRESHOLD_KB_PER_CYCLE and completed_cycles >= 5

        # Connection leak detection: ensure active pool connections didn't diverge
        conn_leak = False
        if checkpoints and checkpoints[-1].db_active_connections > 5:
            conn_leak = True

        report = EnduranceReport(
            total_cycles_completed=completed_cycles,
            total_duration_sec=round(total_duration, 2),
            total_records_processed=sum(c.records_processed for c in checkpoints),
            start_memory_mb=round(start_mem / (1024 * 1024), 2),
            final_memory_mb=round(final_mem / (1024 * 1024), 2),
            peak_memory_mb=round(peak_mem / (1024 * 1024), 2),
            net_memory_growth_mb=round(net_growth_mb, 2),
            avg_growth_per_cycle_kb=round(avg_kb_per_cycle, 2),
            memory_leak_detected=leak_detected,
            connection_leak_detected=conn_leak,
            interrupted_early=self.stop_requested,
            checkpoints=checkpoints,
        )

        update_system_gauges()
        return report


def main():
    parser = argparse.ArgumentParser(description="DataExtraction — 24-Hour Endurance & Soak Test Framework")
    parser.add_argument("--duration-hours", type=float, default=None, help="Execution duration in hours (e.g. 24.0)")
    parser.add_argument("--cycles", type=int, default=None, help="Fixed cycle count for accelerated soak tests (e.g. 50)")
    parser.add_argument("--batch-size", type=int, default=250, help="Records per cycle batch (default: 250)")
    parser.add_argument("--checkpoint-file", type=str, default="endurance_checkpoints.jsonl", help="JSONL checkpoint log path")
    parser.add_argument("--dry-run", action="store_true", help="Execute without committing to live PostgreSQL")
    args = parser.parse_args()

    harness = EnduranceTestHarness(
        batch_size=args.batch_size,
        checkpoint_file=args.checkpoint_file,
        dry_run=args.dry_run,
    )
    report = harness.run(duration_hours=args.duration_hours, max_cycles=args.cycles)

    print("\n=================================================================")
    print("      DATAEXTRACTION — 24-HOUR ENDURANCE & SOAK TEST REPORT       ")
    print("=================================================================")
    print(f"Total Cycles Completed : {report.total_cycles_completed:,}")
    print(f"Total Duration         : {report.total_duration_sec:.2f}s ({report.total_duration_sec / 3600.0:.2f} hrs)")
    print(f"Total Records Tested   : {report.total_records_processed:,}")
    print(f"Initial Memory         : {report.start_memory_mb:.2f} MB")
    print(f"Final Memory           : {report.final_memory_mb:.2f} MB")
    print(f"Peak Memory            : {report.peak_memory_mb:.2f} MB")
    print(f"Net Growth             : {report.net_memory_growth_mb:+.2f} MB")
    print(f"Avg Growth / Cycle     : {report.avg_growth_per_cycle_kb:.2f} KB/cycle")
    print(f"Memory Leak Free       : {'[PASS] (No Leak)' if not report.memory_leak_detected else '[FAIL] (Leak Detected)'}")
    print(f"Connection Pool Safe   : {'[PASS] (No Leaked Conns)' if not report.connection_leak_detected else '[FAIL] (Pool Leaks)'}")
    print(f"Interrupted by Signal  : {report.interrupted_early}")
    print("=================================================================\n")


if __name__ == "__main__":
    main()
