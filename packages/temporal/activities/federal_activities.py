"""
DataExtraction — Federal Scraper Activities
==========================================
Thin subprocess wrappers around all 6 federal registry scrapers.

CRITICAL: Scraper files (fetch_*.py) are NEVER imported or modified here.
          They run as managed subprocesses in their original directory.
          This guarantees zero regression in scraper behavior (ADR-003).
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

try:
    from temporalio import activity
except ImportError:
    class _MockAct:
        defn = lambda *a, **k: (lambda f: f)
    activity = _MockAct()  # type: ignore

PACKAGES_DIR = Path(__file__).resolve().parents[2]
SCRAPERS_DIR = PACKAGES_DIR / "scrapers" / "federal"
PYTHON = sys.executable
logger = logging.getLogger("dataextraction.activities.federal")

# Ensure packages and infrastructure are on sys.path and PYTHONPATH
if str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))
if str(PACKAGES_DIR / "infrastructure") not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR / "infrastructure"))

# ── Default timeout values (seconds) — can override per env ──────────────────
SCRAPER_TIMEOUT = int(os.getenv("FEDERAL_SCRAPER_TIMEOUT_SECONDS", "7200"))  # 2h


def _run_scraper(script_name: str, cli_args: list[str], timeout: int = SCRAPER_TIMEOUT) -> dict:
    """Execute a federal scraper as a managed subprocess."""
    script_path = SCRAPERS_DIR / script_name
    cmd = [PYTHON, str(script_path)] + cli_args

    activity.logger.info("Starting %s (args=%s)", script_name, cli_args)

    # Heartbeat so Temporal knows the activity is alive during long runs
    activity.heartbeat(f"Starting {script_name}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(SCRAPERS_DIR),
        timeout=timeout,
        env={**os.environ, "PYTHONPATH": str(SCRAPERS_DIR.parent.parent.parent)},
    )

    activity.heartbeat(f"Completed {script_name} exit_code={result.returncode}")

    if result.returncode != 0:
        error_tail = result.stderr[-1000:] if result.stderr else "(no stderr)"
        activity.logger.error(
            "%s failed: exit_code=%d stderr=%s", script_name, result.returncode, error_tail
        )
        raise RuntimeError(
            f"{script_name} exited with code {result.returncode}: {error_tail}"
        )

    return {
        "source": script_name.replace("fetch_", "").replace(".py", "").upper(),
        "exit_code": result.returncode,
        "stdout_tail": result.stdout[-3000:] if result.stdout else "",
        "script": script_name,
    }


# ── Activity Definitions ──────────────────────────────────────────────────────

@activity.defn(name="run_cms_npi")
async def run_cms_npi_activity(args: dict) -> dict:
    cli_args = [
        "--limit", str(args.get("limit", 50000)),
        "--mode", args.get("mode", "incremental"),
    ]
    return await asyncio.to_thread(_run_scraper, "fetch_cms_npi.py", cli_args)


@activity.defn(name="run_sec_edgar")
async def run_sec_edgar_activity(args: dict) -> dict:
    form_types = ",".join(args.get("form_types", ["10-K", "10-Q"]))
    cli_args = [
        "--form-types", form_types,
        "--mode", args.get("mode", "incremental"),
    ]
    return await asyncio.to_thread(_run_scraper, "fetch_sec_edgar.py", cli_args)


@activity.defn(name="run_fdic")
async def run_fdic_activity(args: dict) -> dict:
    cli_args = ["--mode", args.get("mode", "incremental")]
    if "limit" in args:
        cli_args += ["--limit", str(args["limit"])]
    return await asyncio.to_thread(_run_scraper, "fetch_fdic.py", cli_args)


@activity.defn(name="run_usaspending")
async def run_usaspending_activity(args: dict) -> dict:
    import datetime
    current_fy = args.get("fiscal_year", datetime.date.today().year)
    cli_args = [
        "--fiscal-year", str(current_fy),
        "--mode", args.get("mode", "incremental"),
    ]
    return await asyncio.to_thread(_run_scraper, "fetch_usaspending.py", cli_args)


@activity.defn(name="run_propublica")
async def run_propublica_activity(args: dict) -> dict:
    cli_args = ["--mode", args.get("mode", "incremental")]
    if "limit" in args:
        cli_args += ["--limit", str(args["limit"])]
    return await asyncio.to_thread(_run_scraper, "fetch_propublica.py", cli_args)


@activity.defn(name="run_sam_gov")
async def run_sam_gov_activity(args: dict) -> dict:
    cli_args = ["--mode", args.get("mode", "incremental")]
    if "limit" in args:
        cli_args += ["--limit", str(args["limit"])]
    return await asyncio.to_thread(_run_scraper, "fetch_sam_gov.py", cli_args)


@activity.defn(name="enrich_gleif_lei")
async def enrich_gleif_lei_activity(payload: dict) -> dict:
    """
    Enriches organization records with Global Legal Entity Identifier (LEI) data from GLEIF.
    Enforces Three-Tier Decision Policy:
      - Confidence >= 0.95 -> AUTO_ENRICH
      - 0.70 <= Confidence < 0.95 -> QUARANTINE_REVIEW (stored in isolation queue)
      - Confidence < 0.70 -> NO_MATCH

    Args:
        payload: {
            "name": str or "company_name": str,
            "lei": Optional[str],
            "country": Optional[str],
            "postal_code": Optional[str],
            "entity_id": Optional[str],
        }

    Returns:
        {
            "status": "SUCCESS" | "FAILED",
            "decision": str,
            "lei": Optional[str],
            "confidence": float,
            "enrichment": Optional[dict],
            "review_id": Optional[str],
        }
    """
    import json
    from packages.scrapers.us_enrichment.connectors.gleif_client import gleif_client
    from packages.infrastructure.db_connector import get_connection, release_connection

    company_name = payload.get("company_name") or payload.get("name") or ""
    exact_lei = payload.get("lei")
    country = payload.get("country", "US")
    postal_code = payload.get("postal_code")
    entity_id = payload.get("entity_id") or payload.get("id")

    logger.info("GLEIF enrichment request: name='%s', lei=%s, country=%s", company_name, exact_lei, country)

    decision = "NO_MATCH"
    confidence = 0.0
    matched_record = None
    review_id = None

    try:
        if exact_lei:
            # Deterministic exact LEI lookup
            res = gleif_client.lookup_by_lei(exact_lei)
            if res:
                matched_record = res
                confidence = 1.0
                decision = "AUTO_ENRICH"
        elif company_name:
            candidates = gleif_client.search_by_name(
                company_name=company_name,
                country=country,
                postal_code=postal_code,
                limit=5,
            )
            if candidates:
                top = candidates[0]
                confidence = float(top.get("match_confidence", 0.0))
                matched_record = top

                if confidence >= 0.95:
                    decision = "AUTO_ENRICH"
                elif confidence >= 0.70:
                    decision = "QUARANTINE_REVIEW"
                else:
                    decision = "NO_MATCH"

        # Database integration
        conn = None
        try:
            conn = get_connection()
            if conn:
                cur = conn.cursor()
                if decision == "AUTO_ENRICH" and entity_id and matched_record:
                    found_lei = matched_record.get("lei")
                    try:
                        cur.execute(
                            "UPDATE companies SET lei = %s, updated_at = NOW() WHERE id = %s",
                            (found_lei, entity_id),
                        )
                        conn.commit()
                    except Exception as upd_err:
                        logger.warning("DB update notice during LEI enrichment: %s", upd_err)
                        conn.rollback()

                elif decision == "QUARANTINE_REVIEW":
                    try:
                        cur.execute(
                            """
                            INSERT INTO kg_resolution.isolation_review_queue
                            (entity_type, incoming_record_id, incoming_source, incoming_payload,
                             candidate_canonical_id, match_score, match_rule, match_evidence)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING review_id
                            """,
                            (
                                "organization",
                                str(entity_id or "GLEIF_QUERY"),
                                "GLEIF_LEI",
                                json.dumps(payload),
                                entity_id if entity_id else None,
                                confidence,
                                "gleif_three_tier_name_postal",
                                json.dumps({"candidate_gleif": matched_record, "query": payload}),
                            ),
                        )
                        row = cur.fetchone()
                        if row:
                            review_id = str(row[0])
                        conn.commit()
                    except Exception as ins_err:
                        logger.warning("Isolation queue insert notice: %s", ins_err)
                        conn.rollback()

                cur.close()
        except Exception as db_e:
            logger.warning("Database unavailable during GLEIF enrichment activity: %s", db_e)
        finally:
            if conn:
                release_connection(conn)

        return {
            "status": "SUCCESS",
            "decision": decision,
            "lei": matched_record.get("lei") if matched_record else None,
            "confidence": confidence,
            "enrichment": matched_record,
            "review_id": review_id,
            "entity_id": entity_id,
        }

    except Exception as exc:
        logger.error("GLEIF enrichment activity error: %s", exc)
        return {
            "status": "FAILED",
            "error": str(exc),
            "entity_id": entity_id,
        }

