"""
OneExtraction — Enterprise Master Pipeline Orchestrator

Coordinates multi-source data ingestion with support for:
  - Modes: 'full', 'incremental', 'sample', 'dry-run'.
  - Per-source error isolation with Dead-Letter Queue (DLQ) capture.
  - Non-destructive execution and connection pool safety.
  - Telemetry recording in data_sources and structured logging.
"""

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_BOTA_DIR = Path(__file__).resolve().parent
if str(_BOTA_DIR) not in sys.path:
    sys.path.insert(0, str(_BOTA_DIR))

from config_manager import config_manager
from db_connector import get_connection, release_connection, log_data_source, db_info
from dead_letter_queue import enqueue_dead_letter
from structured_logger import get_structured_logger

logger = get_structured_logger("oneextraction.orchestrator")


@dataclass
class SourceResult:
    source_name: str
    status: str                            # 'DONE' | 'FAILED' | 'SKIPPED'
    records_fetched: int = 0
    records_merged: int = 0
    records_skipped: int = 0
    dead_letters: int = 0
    duration_s: float = 0.0
    error_message: Optional[str] = None


@dataclass
class PipelineReport:
    run_id: str
    mode: str
    started_at: str
    completed_at: Optional[str] = None
    duration_s: float = 0.0
    sources_executed: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    total_fetched: int = 0
    total_merged: int = 0
    total_skipped: int = 0
    total_dead_letters: int = 0
    results: Dict[str, SourceResult] = field(default_factory=dict)


def _load_source_module(source_name: str):
    """Dynamically imports and returns the fetcher module for a given source."""
    module_map = {
        "fdic": "fetch_fdic",
        "sec": "fetch_sec_edgar",
        "usaspending": "fetch_usaspending",
        "propublica": "fetch_propublica",
        "sam": "fetch_sam_gov",
        "cms": "fetch_cms_npi",
    }
    mod_name = module_map.get(source_name.lower())
    if not mod_name:
        raise ValueError(f"Unknown data source: {source_name}")
    import importlib
    return importlib.import_module(mod_name)


class PipelineOrchestrator:
    """Enterprise Master Orchestrator for all ingestion sources."""

    SUPPORTED_SOURCES = ["fdic", "sec", "usaspending", "propublica", "sam", "cms"]
    VALID_MODES = {"full", "incremental", "sample", "dry-run"}

    def __init__(self, run_id: Optional[str] = None, mode: str = "full"):
        if mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of: {self.VALID_MODES}")

        self.run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        self.mode = mode
        self.logger = logger.bind(run_id=self.run_id, mode=self.mode)

    def execute_source(
        self,
        source_name: str,
        limit: int = 0,
        dry_run: bool = False,
    ) -> SourceResult:
        """Executes a single source ingestion with error isolation and telemetry capture."""
        source_key = source_name.lower()
        start_time = datetime.now(timezone.utc)
        self.logger.info(f"Starting ingestion for source={source_key} (mode={self.mode})")

        # Determine effective limits based on mode
        effective_limit = limit
        if self.mode == "sample" and (limit <= 0 or limit > 200):
            effective_limit = 100
        is_dry_run = dry_run or (self.mode == "dry-run")

        result = SourceResult(source_name=source_key, status="PENDING")
        conn = None

        try:
            mod = _load_source_module(source_key)

            # Route to module execution function
            if source_key == "fdic":
                out = mod.run(source="both", dry_run=is_dry_run)
            elif source_key == "sec":
                out = mod.run(mode="tickers", limit=effective_limit, dry_run=is_dry_run)
            elif source_key == "propublica":
                out = mod.run(limit=effective_limit or 5000, dry_run=is_dry_run)
            else:
                out = mod.run(limit=effective_limit, dry_run=is_dry_run)

            # Parse module return metrics if returned
            if isinstance(out, dict):
                result.records_fetched = out.get("fetched", out.get("records_fetched", 0))
                result.records_merged = out.get("merged", out.get("records_merged", 0))
                result.records_skipped = out.get("skipped", out.get("records_skipped", 0))

            result.status = "DONE"
            self.logger.info(f"Source={source_key} completed successfully")

        except Exception as e:
            result.status = "FAILED"
            result.error_message = str(e)
            self.logger.exception(f"Source={source_key} failed: {e}")

            # Enqueue failure to Dead-Letter Queue
            try:
                conn = get_connection()
                dlq_id = enqueue_dead_letter(
                    conn=conn,
                    source_name=source_key,
                    entity_type="lead",
                    raw_payload={"error_context": str(e), "mode": self.mode},
                    error_reason=f"Pipeline source failure: {e}",
                    run_id=self.run_id,
                )
                if dlq_id:
                    result.dead_letters = 1
            except Exception as dlq_err:
                self.logger.warning(f"Could not record DLQ failure for {source_key}: {dlq_err}")
            finally:
                if conn:
                    release_connection(conn)

        finally:
            end_time = datetime.now(timezone.utc)
            result.duration_s = (end_time - start_time).total_seconds()

            # Record in data_sources telemetry table if not dry-run
            if not is_dry_run:
                try:
                    conn = get_connection()
                    log_data_source(
                        conn=conn,
                        run_id=f"{self.run_id}_{source_key}",
                        source_name=source_key.upper(),
                        source_type="API" if source_key not in ("cms",) else "BULK_FILE",
                        fetched=result.records_fetched,
                        merged=result.records_merged,
                        skipped=result.records_skipped,
                        status=result.status,
                        notes=result.error_message,
                    )
                except Exception as log_err:
                    self.logger.warning(f"Telemetry logging error for {source_key}: {log_err}")
                finally:
                    if conn:
                        release_connection(conn)

        return result

    def run(
        self,
        sources: Optional[List[str]] = None,
        limit: int = 0,
        dry_run: bool = False,
    ) -> PipelineReport:
        """Executes the pipeline across specified or all supported sources."""
        selected_sources = [s.lower() for s in sources] if sources else self.SUPPORTED_SOURCES
        start_time = datetime.now(timezone.utc)

        report = PipelineReport(
            run_id=self.run_id,
            mode=self.mode,
            started_at=start_time.isoformat(),
        )

        self.logger.info(f"Initiating pipeline run={self.run_id} across {len(selected_sources)} sources: {selected_sources}")

        for src in selected_sources:
            if src not in self.SUPPORTED_SOURCES:
                self.logger.warning(f"Skipping unsupported source: {src}")
                continue

            res = self.execute_source(src, limit=limit, dry_run=dry_run)
            report.results[src] = res
            report.sources_executed += 1
            if res.status == "DONE":
                report.sources_succeeded += 1
            else:
                report.sources_failed += 1

            report.total_fetched += res.records_fetched
            report.total_merged += res.records_merged
            report.total_skipped += res.records_skipped
            report.total_dead_letters += res.dead_letters

        end_time = datetime.now(timezone.utc)
        report.completed_at = end_time.isoformat()
        report.duration_s = (end_time - start_time).total_seconds()

        self.logger.info(
            f"Pipeline run={self.run_id} finished in {report.duration_s:.1f}s: "
            f"{report.sources_succeeded}/{report.sources_executed} succeeded, "
            f"{report.total_merged} records merged, {report.total_dead_letters} DLQ items."
        )

        return report


def main():
    parser = argparse.ArgumentParser(description="OneExtraction Master Pipeline Orchestrator")
    parser.add_argument("--sources", nargs="+", default=None, choices=PipelineOrchestrator.SUPPORTED_SOURCES,
                        help="Specific sources to run (default: all)")
    parser.add_argument("--mode", default="full", choices=list(PipelineOrchestrator.VALID_MODES),
                        help="Execution mode (full, incremental, sample, dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="Per-source record limit")
    parser.add_argument("--dry-run", action="store_true", help="Preview without database writes")
    args = parser.parse_args()

    orchestrator = PipelineOrchestrator(mode=args.mode)
    report = orchestrator.run(sources=args.sources, limit=args.limit, dry_run=args.dry_run)

    print("\n" + "="*60)
    print("  ONEEXTRACTION — PIPELINE EXECUTION SUMMARY")
    print(f"  Run ID    : {report.run_id}")
    print(f"  Mode      : {report.mode.upper()}")
    print(f"  Duration  : {report.duration_s:.1f}s")
    print(f"  Sources   : {report.sources_succeeded}/{report.sources_executed} succeeded")
    print("="*60)
    for src, res in report.results.items():
        status_icon = "[OK]" if res.status == "DONE" else "[FAIL]"
        print(f"  {status_icon} {src:<15} status={res.status:<8} duration={res.duration_s:.1f}s")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
