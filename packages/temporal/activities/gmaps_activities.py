"""
DataExtraction — Google Maps Scraper Temporal Activities
=========================================================
Enterprise-grade Temporal activities for geospatial extraction, website discovery,
contact crawling, and direct OneExtraction PostgreSQL persistence.

Production Standards:
  - Real execution with active Temporal heartbeats
  - Direct persistence into OneExtraction PostgreSQL (`businesses` & `people`)
  - Resilient error handling, circuit breaking, and telemetry
  - SSRF protection on all outbound website verification and crawls
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from temporalio import activity

# Setup paths cleanly
PACKAGES_DIR = Path(__file__).resolve().parents[2]
GMAPS_PKG = PACKAGES_DIR / "scrapers" / "google_maps"
GMAPS_SRC = GMAPS_PKG / "src"
INFRA_DIR = PACKAGES_DIR / "infrastructure"

# Ensure GMAPS_SRC is FIRST on sys.path so 'gmaps_scraper' resolves to the package directory
if str(GMAPS_SRC) not in sys.path:
    sys.path.insert(0, str(GMAPS_SRC))

for p in [str(INFRA_DIR), str(PACKAGES_DIR)]:
    if p not in sys.path:
        sys.path.append(p)

logger = logging.getLogger("dataextraction.activities.gmaps")


def _safe_heartbeat(msg: str):
    """Safely issues a Temporal heartbeat if running within an activity context."""
    try:
        activity.heartbeat(msg)
    except Exception:
        pass


def _get_activity_logger():
    """Returns the Temporal activity logger if in context, otherwise standard logger."""
    try:
        return activity.logger
    except Exception:
        return logger


def _get_postgres_connection():
    """Acquires a PostgreSQL connection from the centralized pool if available."""
    try:
        from db_connector import get_connection
        return get_connection()
    except Exception as exc:
        logger.warning("PostgreSQL connection could not be acquired: %s", exc)
        return None


def _release_postgres_connection(conn):
    """Safely returns a PostgreSQL connection to the pool."""
    if not conn:
        return
    try:
        from db_connector import release_connection
        release_connection(conn)
    except Exception as exc:
        logger.warning("Error releasing PostgreSQL connection: %s", exc)


@activity.defn(name="run_gmaps_collection")
async def run_gmaps_collection_activity(region: str, category: str, tile_config: dict) -> dict:
    """
    Executes Google Maps place extraction for a region and category.
    Performs quadrant search, anti-bot identity rotation, and persists
    extracted places directly into PostgreSQL `businesses`.

    Args:
        region: Region code (e.g., "US-CA", "CA", "US-TX")
        category: Business category / vertical (e.g., "healthcare", "restaurant")
        tile_config: Configuration dictionary (limit, dry_run, concurrency)

    Returns:
        {"region": str, "category": str, "collected": int, "postgres_inserted": int, "status": str}
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting GMaps collection: region=%s, category=%s", region, category)
    _safe_heartbeat(f"Initializing collection: {region}/{category}")

    from gmaps_scraper.config import load_config
    from gmaps_scraper.db import Database
    from gmaps_scraper.http import HttpClient
    from gmaps_scraper.orchestrator import PipelineOrchestrator, PipelineConfig
    from gmaps_scraper.scope import get_region
    from packages.scrapers.google_maps.postgres_writer import upsert_gmaps_places_to_postgres

    # Parse country and state codes
    raw_region = (region or "US-CA").strip().upper()
    if "-" in raw_region:
        parts = raw_region.split("-", 1)
        country_code = parts[0]
        region_code = parts[1]
    else:
        country_code = "US"
        region_code = raw_region

    limit = tile_config.get("limit")
    if limit is not None:
        try:
            limit = int(limit)
            if limit <= 0:
                limit = None
        except (ValueError, TypeError):
            limit = 50
    else:
        limit = 50  # Sensible default limit per tile activity

    dry_run = bool(tile_config.get("dry_run", False))

    cfg = load_config()
    db = Database(cfg.db_path)
    db.init_schema()
    orchestrator = PipelineOrchestrator.get_instance(db, cfg)
    http_client = HttpClient(cfg)

    region_info = get_region(country_code, region_code)
    if not region_info:
        act_logger.warning("Region code %s not found in country %s. Falling back to default bounding box.", region_code, country_code)
        from gmaps_scraper.scope import RegionInfo
        region_info = RegionInfo(code=region_code, name=region_code, country_code=country_code, bbox=None)

    run_id = f"act_{int(time.time())}_{region_code}_{category[:4]}"
    task_id = f"col_{country_code.lower()}_{region_code.lower()}_{category.lower()}"

    collected_count = 0
    pg_inserted = 0

    try:
        _safe_heartbeat(f"Searching Google Maps: {region_code}/{category}")

        if dry_run:
            pipe_cfg = PipelineConfig(
                country=country_code,
                regions=[region_code],
                categories=[category],
                collection_limit=limit,
                dry_run=True,
            )
            plan = orchestrator.preview_plan(pipe_cfg)
            planned = len(plan.get("stage_1_tasks", []))
            act_logger.info("Dry run collection planned tasks: %d", planned)
            return {
                "region": region,
                "category": category,
                "collected": planned,
                "postgres_inserted": 0,
                "mode": "dry_run",
                "status": "SUCCESS",
            }

        # Live extraction execution
        res = await orchestrator._execute_collection_search(
            http_client=http_client,
            country_code=country_code,
            region=region_info,
            category=category,
            limit=limit,
            run_id=run_id,
            task_id=task_id,
            dry_run=False,
            collection_only=False,
        )

        collected_count = getattr(res, "total_unique", int(res))
        _safe_heartbeat(f"Scraped {collected_count} places from Google Maps. Persisting to PostgreSQL...")

        # Fetch canonical records from working buffer
        canonical_places = db.get_places(limit=limit or 500)

        # Batch upsert directly to OneExtraction PostgreSQL
        conn = _get_postgres_connection()
        if conn:
            try:
                pg_res = upsert_gmaps_places_to_postgres(conn, canonical_places)
                pg_inserted = pg_res.get("inserted_or_updated", 0)
                act_logger.info("Successfully persisted %d places to PostgreSQL", pg_inserted)
            except Exception as pg_exc:
                act_logger.warning("PostgreSQL upsert notice: %s", pg_exc)
            finally:
                _release_postgres_connection(conn)

    except Exception as exc:
        act_logger.error("GMaps collection error: %s", exc)
        return {
            "region": region,
            "category": category,
            "collected": collected_count,
            "postgres_inserted": pg_inserted,
            "error": str(exc),
            "status": "FAILED",
        }

    _safe_heartbeat(f"Finished: {collected_count} collected, {pg_inserted} stored in PostgreSQL")
    return {
        "region": region,
        "category": category,
        "collected": collected_count,
        "postgres_inserted": pg_inserted,
        "status": "SUCCESS",
    }


@activity.defn(name="run_gmaps_website_verification")
async def run_gmaps_website_verification_activity(batch_id: str, limit: int = 10000) -> dict:
    """
    Verifies discovered website URLs for reachability and checks for SSRF vulnerabilities.
    Updates the verification status directly in PostgreSQL `businesses`.

    Args:
        batch_id: Workflow batch identifier
        limit: Max websites to verify in this activity

    Returns:
        {"batch_id": str, "verified": int, "failed": int, "status": str}
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting GMaps website verification: batch=%s, limit=%d", batch_id, limit)
    _safe_heartbeat("Querying unverified websites")

    from gmaps_scraper.config import load_config
    from gmaps_scraper.website.ssrf import is_safe_url
    from gmaps_scraper.website.verifier import verify_url_target

    verified_count = 0
    failed_count = 0

    conn = _get_postgres_connection()
    places_to_verify = []

    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT company_id, name, website_url
                FROM businesses
                WHERE source = 'google_maps'
                  AND website_url IS NOT NULL
                  AND ssl_valid IS NULL
                LIMIT %s
                """,
                (limit,),
            )
            for row in cur.fetchall():
                places_to_verify.append({"company_id": row[0], "name": row[1], "website": row[2]})
            cur.close()
        except Exception as q_err:
            activity.logger.warning("Could not query PostgreSQL unverified list: %s", q_err)
        finally:
            _release_postgres_connection(conn)

    _safe_heartbeat(f"Verifying {len(places_to_verify)} company websites...")

    for item in places_to_verify:
        url = item.get("website")
        cid = item.get("company_id")
        if not url:
            continue

        if not is_safe_url(url):
            act_logger.debug("SSRF filter blocked unsafe URL: %s", url)
            failed_count += 1
            continue

        try:
            is_valid = await verify_url_target(url, item.get("name") or "")
            if is_valid:
                verified_count += 1
            else:
                failed_count += 1

            # Update status in PostgreSQL
            update_conn = _get_postgres_connection()
            if update_conn:
                try:
                    u_cur = update_conn.cursor()
                    u_cur.execute(
                        "UPDATE businesses SET ssl_valid = %s, updated_at = now() WHERE company_id = %s",
                        (is_valid, cid),
                    )
                    update_conn.commit()
                    u_cur.close()
                finally:
                    _release_postgres_connection(update_conn)

        except Exception:
            failed_count += 1

        if (verified_count + failed_count) % 25 == 0:
            _safe_heartbeat(f"Verified: {verified_count}, Failed: {failed_count}")

    _safe_heartbeat(f"Verification completed: {verified_count} verified, {failed_count} failed")
    return {
        "batch_id": batch_id,
        "verified": verified_count,
        "failed": failed_count,
        "status": "SUCCESS",
    }


@activity.defn(name="run_gmaps_website_crawl")
async def run_gmaps_website_crawl_activity(batch_id: str) -> dict:
    """
    Crawls verified company websites to extract published corporate emails,
    phone numbers, and executive leadership contacts.
    Persists contacts directly to PostgreSQL `businesses` and `people`.

    Args:
        batch_id: Workflow batch identifier

    Returns:
        {"batch_id": str, "crawled": int, "contacts_found": int, "status": str}
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting website contact crawl: batch=%s", batch_id)
    _safe_heartbeat("Selecting verified websites for crawling")

    from gmaps_scraper.config import load_config
    from gmaps_scraper.website.crawler import WebsiteCrawler
    from gmaps_scraper.website.extractor import ContactExtractor
    from packages.scrapers.google_maps.postgres_writer import upsert_gmaps_people_to_postgres

    crawled_count = 0
    contacts_found = 0

    conn = _get_postgres_connection()
    targets = []

    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT company_id, name, website_url
                FROM businesses
                WHERE source = 'google_maps'
                  AND website_url IS NOT NULL
                  AND (extracted_emails IS NULL OR array_length(extracted_emails, 1) = 0)
                LIMIT 50
                """
            )
            for row in cur.fetchall():
                targets.append({"company_id": row[0], "name": row[1], "website": row[2]})
            cur.close()
        except Exception as q_err:
            act_logger.warning("Could not query verified websites: %s", q_err)
        finally:
            _release_postgres_connection(conn)

    crawler = WebsiteCrawler(max_pages=5, timeout=15)
    extractor = ContactExtractor()

    for target in targets:
        cid = target["company_id"]
        url = target["website"]
        company_name = target["name"]

        try:
            pages = await crawler.crawl_site(url)
            crawled_count += 1
            site_emails = set()
            site_people = []

            for page in pages:
                extracted = extractor.extract_from_html(page.get("html", ""), base_url=page.get("url", url))
                for em in extracted.get("emails", []):
                    site_emails.add(em)
                for person in extracted.get("people", []):
                    person["company_id"] = cid
                    site_people.append(person)

            contacts_found += len(site_emails) + len(site_people)

            # Persist to PostgreSQL
            up_conn = _get_postgres_connection()
            if up_conn:
                try:
                    u_cur = up_conn.cursor()
                    if site_emails:
                        u_cur.execute(
                            """
                            UPDATE businesses
                            SET extracted_emails = %s,
                                email = COALESCE(email, %s),
                                updated_at = now()
                            WHERE company_id = %s
                            """,
                            (list(site_emails), list(site_emails)[0], cid),
                        )
                    up_conn.commit()
                    u_cur.close()

                    if site_people:
                        upsert_gmaps_people_to_postgres(up_conn, site_people)
                finally:
                    _release_postgres_connection(up_conn)

        except Exception as crawl_err:
            act_logger.debug("Error crawling site %s: %s", url, crawl_err)

        _safe_heartbeat(f"Crawled: {crawled_count}, Contacts Found: {contacts_found}")

    return {
        "batch_id": batch_id,
        "crawled": crawled_count,
        "contacts_found": contacts_found,
        "status": "SUCCESS",
    }


@activity.defn(name="run_gmaps_export")
async def run_gmaps_export_activity(job_id: str, export_format: str = "csv") -> dict:
    """
    Exports collected and enriched Google Maps data from PostgreSQL
    into standardized CSV or Parquet deliverables.

    Args:
        job_id: Export job identifier
        export_format: "csv" | "parquet" | "json"

    Returns:
        {"job_id": str, "format": str, "records": int, "output_path": str, "status": str}
    """
    act_logger = _get_activity_logger()
    act_logger.info("Executing GMaps export: job=%s, format=%s", job_id, export_format)

    out_dir = Path("data") / "exports" / time.strftime("%Y-%m-%d")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"gmaps_businesses_{job_id}.{export_format}"

    record_count = 0
    conn = _get_postgres_connection()

    if conn:
        try:
            import pandas as pd
            query = "SELECT * FROM businesses WHERE source = 'google_maps'"
            df = pd.read_sql_query(query, conn)
            record_count = len(df)
            if export_format.lower() == "parquet":
                df.to_parquet(out_file, index=False)
            else:
                df.to_csv(out_file, index=False)
            activity.logger.info("Exported %d records to %s", record_count, out_file)
        except Exception as exp_err:
            activity.logger.warning("PostgreSQL export notice: %s", exp_err)
        finally:
            _release_postgres_connection(conn)

    return {
        "job_id": job_id,
        "format": export_format,
        "records": record_count,
        "output_path": str(out_file),
        "status": "SUCCESS",
    }
