"""
DataExtraction — Google Maps Geospatial Scraper
================================================
High-throughput Google Places & quadrant tiling scraper.
Inherits from BaseScraper for budget protection, rate limiting, and circuit breaking.
Directly persists extracted places and personnel to PostgreSQL.
"""

import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.scrapers.base_scraper import BaseScraper, CircuitBreakerOpenException

# Ensure gmaps_scraper package is accessible on sys.path
_CURRENT_DIR = Path(__file__).resolve().parent
_SRC_DIR = _CURRENT_DIR / "src"
_INFRA_DIR = _CURRENT_DIR.parent.parent / "infrastructure"

for p in [str(_SRC_DIR), str(_INFRA_DIR), str(_CURRENT_DIR.parent.parent)]:
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("dataextraction.scrapers.gmaps")


class GMapsScraper(BaseScraper):
    """
    Google Maps Geospatial Scraper.
    Uses reverse-engineered Protobuf/RPC endpoints with quadrant tiling,
    anti-bot identity rotation, website discovery, and direct PostgreSQL persistence.
    """

    def __init__(
        self,
        rate_limit_per_second: float = 8.0,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_seconds: float = 45.0,
    ):
        super().__init__(
            name="GMAPS_GEOSPATIAL",
            rate_limit_per_second=rate_limit_per_second,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_cooldown_seconds=circuit_cooldown_seconds,
        )

    def scrape(
        self,
        region: Optional[str] = "US-CA",
        vertical: Optional[str] = "healthcare",
        limit: int = 50,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Executes Google Maps place collection, deduplication, and PostgreSQL persistence.

        Args:
            region: Geographic region / state code (e.g. 'US-CA', 'US-TX')
            vertical: Business category / vertical (e.g. 'healthcare', 'retail')
            limit: Maximum places to collect (0 or None for unlimited)
            dry_run: When True, simulates pipeline planning without live writes

        Returns:
            Dictionary containing extraction results, record counts, and telemetry.
        """
        self._check_circuit()
        start_time = time.time()
        logger.info(
            "[%s] Starting extraction: region=%s, vertical=%s, limit=%s, dry_run=%s",
            self.name, region, vertical, limit, dry_run
        )

        from gmaps_scraper.config import load_config
        from gmaps_scraper.db import Database
        from gmaps_scraper.orchestrator import PipelineOrchestrator, PipelineConfig
        from packages.scrapers.google_maps.postgres_writer import (
            upsert_gmaps_places_to_postgres,
            upsert_gmaps_people_to_postgres,
        )

        cfg = load_config()
        # Use working buffer for the engine during quadrant discovery
        db = Database(cfg.db_path)
        db.init_schema()
        orchestrator = PipelineOrchestrator.get_instance(db, cfg)

        pipe_cfg = PipelineConfig(
            country="US" if not region or "US" in region else ("MX" if "MX" in region else "both"),
            regions=[region] if region else None,
            categories=[vertical] if vertical else None,
            collection_limit=limit if limit and limit > 0 else None,
            dry_run=dry_run,
        )

        collected_places: List[Dict[str, Any]] = []
        pg_inserted = 0

        try:
            if dry_run:
                plan = orchestrator.preview_plan(pipe_cfg)
                self._record_success()
                return {
                    "status": "SUCCESS",
                    "mode": "dry_run",
                    "region": region,
                    "vertical": vertical,
                    "planned_tasks": plan.get("tasks_total", 0),
                    "duration_seconds": round(time.time() - start_time, 2),
                    "metrics": self.get_metrics(),
                }

            # Live execution
            orchestrator.run_pipeline(pipe_cfg)
            
            # Fetch deduplicated canonical places from engine buffer
            canonical_records = db.get_places(limit=limit or 1000)
            collected_places = canonical_records

            # Direct PostgreSQL Persistence (OneExtraction central warehouse)
            try:
                from db_connector import get_connection, release_connection
                conn = get_connection()
                if conn:
                    try:
                        res = upsert_gmaps_places_to_postgres(conn, collected_places)
                        pg_inserted = res.get("inserted_or_updated", 0)
                    finally:
                        release_connection(conn)
            except Exception as pg_err:
                logger.warning("[%s] PostgreSQL direct write notice (offline or unreachable): %s", self.name, pg_err)

            self._record_success()
            elapsed = round(time.time() - start_time, 2)
            logger.info(
                "[%s] Completed extraction: %d places collected, %d written to Postgres in %.2fs",
                self.name, len(collected_places), pg_inserted, elapsed
            )

            return {
                "status": "SUCCESS",
                "mode": "live",
                "region": region,
                "vertical": vertical,
                "collected": len(collected_places),
                "postgres_inserted": pg_inserted,
                "duration_seconds": elapsed,
                "metrics": self.get_metrics(),
            }

        except Exception as exc:
            self._record_failure(exc)
            logger.error("[%s] Scraping pipeline failed: %s", self.name, exc)
            return {
                "status": "FAILED",
                "region": region,
                "vertical": vertical,
                "error": str(exc),
                "duration_seconds": round(time.time() - start_time, 2),
                "metrics": self.get_metrics(),
            }


def run(
    region: Optional[str] = "US-CA",
    vertical: Optional[str] = "healthcare",
    limit: int = 50,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Convenience functional entry point."""
    scraper = GMapsScraper()
    return scraper.scrape(region=region, vertical=vertical, limit=limit, dry_run=dry_run)
