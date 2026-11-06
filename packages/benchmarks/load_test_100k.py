"""
DataExtraction — Task 7: 100k+ High-Throughput Load Test Harness
================================================================
Generates, streams, and ingests 100,000+ realistic B2B organizations and executive
leads through the canonical staging pipeline.

Capabilities:
  1. Low-memory streaming record generator with realistic data noise and duplicate clusters.
  2. High-throughput batch ingestion using PostgreSQL execute_values.
  3. Latency percentile tracking (p50, p90, p95, p99, min, max, avg).
  4. Memory footprint delta & DB connection pool monitoring.
  5. Deterministic dry-run and live database execution modes.
"""

import argparse
import json
import logging
import math
import os
import random
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.db_connector import get_db_connection
from packages.infrastructure.metrics import (
    record_request_metrics,
    update_system_gauges,
)
from packages.infrastructure.staging_writer import bulk_upsert_staging_records

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s [%(levelname)-7s] [%(name)s] %(message)s",
)
logger = logging.getLogger("dataextraction.benchmarks.load_test")

# Realistic synthetic generation fixtures
INDUSTRIES = [
    ("Software & Cloud Infrastructure", "511210"),
    ("Healthcare & Life Sciences", "621111"),
    ("Commercial Construction & Architecture", "236220"),
    ("Aerospace & Defense Contracting", "336411"),
    ("Financial Services & Asset Management", "523920"),
    ("Automotive & Electric Mobility", "336111"),
    ("Renewable Energy & Utilities", "221114"),
    ("Freight Logistics & Supply Chain", "484110"),
]

LOCATIONS = [
    ("Austin", "Texas", "TX", "78701"),
    ("San Francisco", "California", "CA", "94105"),
    ("New York", "New York", "NY", "10001"),
    ("Seattle", "Washington", "WA", "98101"),
    ("Boston", "Massachusetts", "MA", "02110"),
    ("Chicago", "Illinois", "IL", "60601"),
    ("Atlanta", "Georgia", "GA", "30303"),
    ("Denver", "Colorado", "CO", "80202"),
    ("Miami", "Florida", "FL", "33131"),
    ("Phoenix", "Arizona", "AZ", "85001"),
]

FIRST_NAMES = ["James", "Sarah", "Michael", "Elena", "David", "Priya", "Robert", "Jennifer", "William", "Jessica", "Marcus", "Emily"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Chen", "Patel", "Miller", "Davis", "Rodriguez", "Martinez", "Taylor", "Anderson", "Thomas"]
TITLES = [
    ("Chief Executive Officer", "EXECUTIVE", "EXECUTIVE"),
    ("Chief Technology Officer", "EXECUTIVE", "ENGINEERING"),
    ("Chief Operating Officer", "EXECUTIVE", "OPERATIONS"),
    ("VP of Engineering", "VP", "ENGINEERING"),
    ("VP of Sales", "VP", "SALES"),
    ("Director of Product Management", "DIRECTOR", "PRODUCT"),
    ("Head of People & Talent", "DIRECTOR", "HUMAN_RESOURCES"),
    ("General Counsel", "EXECUTIVE", "LEGAL"),
]

CORP_SUFFIXES = ["Inc.", "LLC", "Corp.", "Technologies Inc.", "Group LLC", "Holdings", "Global Corp."]


@dataclass
class LoadTestMetrics:
    total_records: int = 0
    batch_size: int = 0
    total_batches: int = 0
    total_duration_sec: float = 0.0
    throughput_rps: float = 0.0
    latency_p50_ms: float = 0.0
    latency_p90_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    latency_avg_ms: float = 0.0
    latency_min_ms: float = 0.0
    latency_max_ms: float = 0.0
    peak_memory_mb: float = 0.0
    memory_growth_mb: float = 0.0
    errors_encountered: int = 0
    dry_run: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class StreamRecordGenerator:
    """Streams realistic B2B organizations and executives in deterministic batches."""

    def __init__(self, seed: int = 42, duplicate_ratio: float = 0.15):
        self.rng = random.Random(seed)
        self.duplicate_ratio = duplicate_ratio

    def generate_record(self, record_index: int) -> Dict[str, Any]:
        """Generates a single realistic company and executive dictionary."""
        # Calculate cluster base for intentional deduplication testing
        is_duplicate = self.rng.random() < self.duplicate_ratio and record_index > 100
        cluster_id = record_index - self.rng.randint(1, 50) if is_duplicate else record_index

        industry, naics = self.rng.choice(INDUSTRIES)
        city, state, state_code, zip_code = self.rng.choice(LOCATIONS)
        suffix = self.rng.choice(CORP_SUFFIXES)

        base_name = f"Enterprise Apex {cluster_id}"
        company_name = f"{base_name} {suffix}" if not is_duplicate else f"{base_name} {suffix.lower()}"
        clean_slug = f"apex-{cluster_id}"
        domain = f"{clean_slug}.io"

        first_name = self.rng.choice(FIRST_NAMES)
        last_name = self.rng.choice(LAST_NAMES)
        title, seniority, dept = self.rng.choice(TITLES)
        email = f"{first_name.lower()}.{last_name.lower()}@{domain}"

        ein_prefix = 10 + (cluster_id % 89)
        ein_suffix = 1000000 + (cluster_id % 8999999)
        ein = f"{ein_prefix}-{ein_suffix}"

        return {
            "id": f"load_test_comp_{record_index}",
            "company_id": f"load_test_comp_{record_index}",
            "company_name": company_name,
            "name": company_name,
            "legal_name": company_name,
            "domain": domain,
            "website": f"https://www.{domain}",
            "phone": f"+1-555-{self.rng.randint(100, 999):03d}-{self.rng.randint(1000, 9999):04d}",
            "city": city,
            "state": state,
            "state_code": state_code,
            "zip_code": zip_code,
            "country": "United States",
            "industry": industry,
            "naics_code": naics,
            "ein": ein,
            "cik": f"000{1000000 + (cluster_id % 900000)}",
            "company_quality_score": self.rng.randint(75, 99),
            "first_name": first_name,
            "last_name": last_name,
            "full_name": f"{first_name} {last_name}",
            "title": title,
            "standardized_title": title,
            "seniority_level": seniority,
            "department": dept,
            "email": email,
            "email_status": "VERIFIED" if self.rng.random() > 0.1 else "UNKNOWN",
            "email_confidence_score": self.rng.randint(80, 99),
            "load_test_index": record_index,
        }

    def generate_batches(
        self,
        total_records: int,
        batch_size: int,
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """Yields chunks of generated records without hoarding memory."""
        current = 0
        while current < total_records:
            current_batch_size = min(batch_size, total_records - current)
            batch = [self.generate_record(current + i + 1) for i in range(current_batch_size)]
            yield batch
            current += current_batch_size


class LoadTestRunner:
    """Executes the 100k+ record high-throughput staging load test."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.generator = StreamRecordGenerator()

    def run(
        self,
        total_records: int = 100000,
        batch_size: int = 2500,
    ) -> LoadTestMetrics:
        """
        Executes the load test, tracking execution metrics, latencies, and resource consumption.
        """
        logger.info(
            "Starting 100k+ load test benchmark: records=%d, batch_size=%d, dry_run=%s",
            total_records,
            batch_size,
            self.dry_run,
        )

        tracemalloc.start()
        start_mem = tracemalloc.get_traced_memory()[0]

        latencies_ms: List[float] = []
        errors = 0
        total_batches = math.ceil(total_records / batch_size)
        start_time = time.perf_counter()

        try:
            batch_idx = 0
            for batch in self.generator.generate_batches(total_records, batch_size):
                batch_idx += 1
                b_start = time.perf_counter()

                try:
                    if not self.dry_run:
                        with get_db_connection() as conn:
                            with conn.cursor() as cur:
                                bulk_upsert_staging_records(cur, batch, source="100K_LOAD_BENCHMARK")
                    else:
                        # Simulated parse & validation execution in dry-run
                        _ = [json.dumps(r) for r in batch]
                except Exception as ex:
                    errors += len(batch)
                    logger.error("Error processing batch %d: %s", batch_idx, ex)

                b_duration_ms = (time.perf_counter() - b_start) * 1000.0
                latencies_ms.append(b_duration_ms)

                # Record Prometheus request telemetry
                record_request_metrics(
                    "POST",
                    "/api/staging/bulk-upsert",
                    200 if errors == 0 else 500,
                    b_duration_ms / 1000.0,
                )

                if batch_idx % max(1, total_batches // 10) == 0 or batch_idx == total_batches:
                    elapsed_so_far = time.perf_counter() - start_time
                    current_rps = (batch_idx * batch_size) / max(0.001, elapsed_so_far)
                    logger.info(
                        "Progress: batch %d/%d (%d records) — %.1f rec/s — batch latency: %.1f ms",
                        batch_idx,
                        total_batches,
                        min(batch_idx * batch_size, total_records),
                        current_rps,
                        b_duration_ms,
                    )

        finally:
            pass

        total_duration = time.perf_counter() - start_time
        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        throughput = total_records / max(0.001, total_duration)

        # Calculate percentiles
        sorted_latencies = sorted(latencies_ms)
        n = len(sorted_latencies)

        def pct(p: float) -> float:
            if not sorted_latencies:
                return 0.0
            idx = min(n - 1, max(0, int(math.ceil(p * n)) - 1))
            return sorted_latencies[idx]

        metrics = LoadTestMetrics(
            total_records=total_records,
            batch_size=batch_size,
            total_batches=total_batches,
            total_duration_sec=round(total_duration, 3),
            throughput_rps=round(throughput, 1),
            latency_p50_ms=round(pct(0.50), 2),
            latency_p90_ms=round(pct(0.90), 2),
            latency_p95_ms=round(pct(0.95), 2),
            latency_p99_ms=round(pct(0.99), 2),
            latency_avg_ms=round(sum(latencies_ms) / max(1, len(latencies_ms)), 2),
            latency_min_ms=round(min(latencies_ms) if latencies_ms else 0.0, 2),
            latency_max_ms=round(max(latencies_ms) if latencies_ms else 0.0, 2),
            peak_memory_mb=round(peak_mem / (1024 * 1024), 2),
            memory_growth_mb=round((current_mem - start_mem) / (1024 * 1024), 2),
            errors_encountered=errors,
            dry_run=self.dry_run,
        )

        update_system_gauges()
        return metrics


def main():
    parser = argparse.ArgumentParser(description="DataExtraction — 100k+ Record Load Test Harness")
    parser.add_argument("--records", type=int, default=100000, help="Number of records to generate and ingest (default: 100000)")
    parser.add_argument("--batch-size", type=int, default=2500, help="Batch size for database upserts (default: 2500)")
    parser.add_argument("--dry-run", action="store_true", help="Execute synthetic stream and parse without committing to DB")
    parser.add_argument("--output", type=str, default=None, help="Optional output JSON path for benchmark metrics")
    args = parser.parse_args()

    runner = LoadTestRunner(dry_run=args.dry_run)
    result = runner.run(total_records=args.records, batch_size=args.batch_size)

    print("\n=================================================================")
    print("        DATAEXTRACTION — 100k+ LOAD TEST BENCHMARK REPORT         ")
    print("=================================================================")
    print(f"Total Records Ingested : {result.total_records:,}")
    print(f"Batch Size             : {result.batch_size:,} ({result.total_batches} batches)")
    print(f"Execution Mode         : {'DRY RUN' if result.dry_run else 'LIVE POSTGRESQL'}")
    print(f"Total Duration         : {result.total_duration_sec:.2f} seconds")
    print(f"Throughput             : {result.throughput_rps:,.1f} records/sec")
    print(f"Latency p50            : {result.latency_p50_ms:.2f} ms")
    print(f"Latency p90            : {result.latency_p90_ms:.2f} ms")
    print(f"Latency p95            : {result.latency_p95_ms:.2f} ms")
    print(f"Latency p99            : {result.latency_p99_ms:.2f} ms")
    print(f"Latency (Min / Max)    : {result.latency_min_ms:.2f} ms / {result.latency_max_ms:.2f} ms")
    print(f"Peak Traced Memory     : {result.peak_memory_mb:.2f} MB")
    print(f"Errors Encountered     : {result.errors_encountered}")
    print("=================================================================\n")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, indent=2)
        print(f"Report saved to {out_path.resolve()}")


if __name__ == "__main__":
    main()
