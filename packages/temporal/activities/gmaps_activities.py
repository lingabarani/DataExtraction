"""
DataExtraction — GMaps Scraper Activities
==========================================
Thin module-import wrappers around the gmaps-scraper package.

CRITICAL: gmaps_scraper source files are NEVER modified.
          sys.path injection bridges the monorepo layout gap (ADR-003).
"""

import logging
import sys
from pathlib import Path

from temporalio import activity

# Inject gmaps-scraper package path — no source modification needed
GMAPS_SRC = Path(__file__).resolve().parents[3] / "scrapers" / "google_maps" / "src"
if str(GMAPS_SRC) not in sys.path:
    sys.path.insert(0, str(GMAPS_SRC))

logger = logging.getLogger("dataextraction.activities.gmaps")


@activity.defn(name="run_gmaps_collection")
async def run_gmaps_collection_activity(region: str, category: str, tile_config: dict) -> dict:
    """
    Runs the gmaps-scraper collection phase for one region/category combination.
    Invokes orchestrator.collect_region() from the unmodified gmaps_scraper package.

    Args:
        region: Geographic region code (e.g., "US-CA", "US-TX")
        category: Business category (e.g., "restaurant", "hotel")
        tile_config: Quadrant tiling configuration dict

    Returns:
        {"region": str, "category": str, "collected": int, "status": str}
    """
    activity.logger.info("GMaps collection: region=%s category=%s", region, category)
    activity.heartbeat(f"Starting collection: {region}/{category}")

    from gmaps_scraper import orchestrator  # Unmodified original module

    result = orchestrator.collect_region(
        region=region,
        category=category,
        tile_config=tile_config or {},
    )
    activity.heartbeat(f"Collected {result.count} records: {region}/{category}")
    return {
        "region": region,
        "category": category,
        "collected": result.count,
        "status": "SUCCESS",
    }


@activity.defn(name="run_gmaps_website_verification")
async def run_gmaps_website_verification_activity(batch_id: str, limit: int = 10000) -> dict:
    """
    Runs the website URL verification phase on collected gmaps leads.
    Checks which discovered URLs are reachable/valid.

    Args:
        batch_id: Workflow run identifier for batch isolation
        limit: Max number of leads to verify in this run

    Returns:
        {"batch_id": str, "verified": int, "failed": int, "status": str}
    """
    activity.logger.info("GMaps website verification: batch=%s limit=%d", batch_id, limit)
    activity.heartbeat(f"Starting website verification: batch={batch_id}")

    from gmaps_scraper import website_verifier  # type: ignore

    result = website_verifier.verify_batch(batch_id=batch_id, limit=limit)
    return {
        "batch_id": batch_id,
        "verified": result.verified_count,
        "failed": result.failed_count,
        "status": "SUCCESS",
    }


@activity.defn(name="run_gmaps_website_crawl")
async def run_gmaps_website_crawl_activity(batch_id: str) -> dict:
    """
    Runs the website crawl phase — extracts emails/phones from verified websites.

    Args:
        batch_id: Workflow run identifier for batch isolation

    Returns:
        {"batch_id": str, "crawled": int, "contacts_found": int, "status": str}
    """
    activity.logger.info("GMaps website crawl: batch=%s", batch_id)
    activity.heartbeat(f"Starting website crawl: batch={batch_id}")

    from gmaps_scraper import website_crawler  # type: ignore

    result = website_crawler.crawl_batch(batch_id=batch_id)
    return {
        "batch_id": batch_id,
        "crawled": result.crawled_count,
        "contacts_found": result.contacts_found,
        "status": "SUCCESS",
    }


@activity.defn(name="run_gmaps_export")
async def run_gmaps_export_activity(job_id: str, export_format: str = "csv") -> dict:
    """
    Exports collected and enriched gmaps data to specified format.

    Args:
        job_id: Export job identifier
        export_format: "csv" | "json" | "postgres"

    Returns:
        {"job_id": str, "format": str, "records": int, "output_path": str}
    """
    activity.logger.info("GMaps export: job=%s format=%s", job_id, export_format)

    from gmaps_scraper import export  # type: ignore

    result = export.run_export(job_id=job_id, format=export_format)
    return {
        "job_id": job_id,
        "format": export_format,
        "records": result.record_count,
        "output_path": str(result.output_path),
        "status": "SUCCESS",
    }
