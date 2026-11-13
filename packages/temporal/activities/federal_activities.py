"""
DataExtraction — Federal Scraper Activities
==========================================
Managed subprocess wrappers around all 6 federal registry scrapers.

CRITICAL: Scrapers run as isolated managed subprocesses in their original directory
with periodic Temporal heartbeats and structured telemetry parsing.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from temporalio import activity
except ImportError:
    class _MockAct:
        defn = staticmethod(lambda *a, **k: (lambda f: f))
        heartbeat = staticmethod(lambda *a, **k: None)
        logger = logging.getLogger("dataextraction.activities.federal.mock")
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

from packages.infrastructure.config_manager import config_manager

ACTIVITY_RESULT_PREFIX = "ACTIVITY_RESULT_JSON:"


def _safe_heartbeat(message: str) -> None:
    try:
        activity.heartbeat(message)
    except Exception:
        pass


def _parse_scraper_output(script_name: str, stdout_text: str) -> Dict[str, Any]:
    """Extract structured ACTIVITY_RESULT_JSON marker, falling back to regex summary parsing."""
    if stdout_text:
        for line in reversed(stdout_text.splitlines()):
            stripped = line.strip()
            if stripped.startswith(ACTIVITY_RESULT_PREFIX):
                raw_json = stripped[len(ACTIVITY_RESULT_PREFIX):].strip()
                try:
                    payload = json.loads(raw_json)
                    if isinstance(payload, dict):
                        return payload
                except Exception as exc:
                    logger.warning("Malformed %s JSON in %s: %s", ACTIVITY_RESULT_PREFIX, script_name, exc)

        match = re.search(r"Inserted\s*:\s*([\d,]+)", stdout_text, re.IGNORECASE)
        if match:
            return {"inserted_count": int(match.group(1).replace(",", ""))}
        match2 = re.search(r"([\d,]+)\s+inserted", stdout_text, re.IGNORECASE)
        if match2:
            return {"inserted_count": int(match2.group(1).replace(",", ""))}
    return {"inserted_count": 0}


def _drain_stream(stream, sink: List[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            sink.append(line)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _run_scraper(
    script_name: str,
    cli_args: list[str],
    timeout: Optional[int] = None,
    heartbeat_interval: Optional[float] = None,
) -> dict:
    """Execute a federal scraper as a managed subprocess with periodic heartbeats."""
    reg_cfg = config_manager.get_registry_config()
    eff_timeout = int(timeout if timeout is not None else reg_cfg.get("scraper_timeout_seconds", 7200))
    eff_hb = float(heartbeat_interval if heartbeat_interval is not None else reg_cfg.get("heartbeat_interval_seconds", 10.0))
    eff_hb = max(eff_hb, 0.5)

    script_path = SCRAPERS_DIR / script_name
    cmd = [PYTHON, "-u", str(script_path)] + cli_args

    logger.info("Starting %s (args=%s, timeout=%ss)", script_name, cli_args, eff_timeout)
    _safe_heartbeat(f"Starting {script_name}")

    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": str(SCRAPERS_DIR.parent.parent.parent),
    }

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(SCRAPERS_DIR),
        env=env,
    )

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []
    t_out = threading.Thread(target=_drain_stream, args=(proc.stdout, stdout_lines), daemon=True)
    t_err = threading.Thread(target=_drain_stream, args=(proc.stderr, stderr_lines), daemon=True)
    t_out.start()
    t_err.start()

    start_ts = time.monotonic()
    last_hb = start_ts

    while proc.poll() is None:
        now = time.monotonic()
        elapsed = now - start_ts
        if elapsed > eff_timeout:
            proc.kill()
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            raise TimeoutError(f"{script_name} timed out after {eff_timeout}s")
        if now - last_hb >= eff_hb:
            _safe_heartbeat(f"Running {script_name} ({int(elapsed)}s)")
            last_hb = now
        time.sleep(min(0.5, eff_hb))

    t_out.join(timeout=5)
    t_err.join(timeout=5)

    stdout_text = "".join(stdout_lines)
    stderr_text = "".join(stderr_lines)
    _safe_heartbeat(f"Completed {script_name} exit_code={proc.returncode}")

    if proc.returncode != 0:
        error_tail = stderr_text[-1000:] if stderr_text else stdout_text[-1000:] or "(no stderr)"
        logger.error("%s failed: exit_code=%d stderr=%s", script_name, proc.returncode, error_tail)
        raise RuntimeError(f"{script_name} exited with code {proc.returncode}: {error_tail}")

    parsed = _parse_scraper_output(script_name, stdout_text)
    default_source = script_name.replace("fetch_", "").replace(".py", "").upper()

    return {
        "status": str(parsed.get("status", "SUCCESS")).upper(),
        "source": parsed.get("source", default_source),
        "exit_code": proc.returncode,
        "inserted_count": int(parsed.get("inserted_count", 0) or 0),
        "error_count": int(parsed.get("error_count", 0) or 0),
        "skipped_count": int(parsed.get("skipped_count", 0) or 0),
        "reason": parsed.get("reason"),
        "stdout_tail": stdout_text[-3000:] if stdout_text else "",
        "script": script_name,
    }


# ── Activity Definitions ──────────────────────────────────────────────────────

@activity.defn(name="run_cms_npi")
async def run_cms_npi_activity(args: dict) -> dict:
    args = args or {}
    cli_args = [
        "--limit", str(args.get("limit", 50000)),
        "--mode", str(args.get("mode", "incremental")),
    ]
    return await asyncio.to_thread(_run_scraper, "fetch_cms_npi.py", cli_args)


@activity.defn(name="run_sec_edgar")
async def run_sec_edgar_activity(args: dict) -> dict:
    args = args or {}
    reg_cfg = config_manager.get_registry_config()
    raw_mode = str(args.get("mode", reg_cfg.get("sec_default_mode", "tickers"))).lower()
    mode = "full" if raw_mode == "full" else "tickers"
    form_types = ",".join(args.get("form_types", ["10-K", "10-Q"]))
    cli_args = [
        "--form-types", form_types,
        "--mode", mode,
    ]
    if "limit" in args and args["limit"] is not None:
        cli_args += ["--limit", str(args["limit"])]
    return await asyncio.to_thread(_run_scraper, "fetch_sec_edgar.py", cli_args)


@activity.defn(name="run_fdic")
async def run_fdic_activity(args: dict) -> dict:
    args = args or {}
    reg_cfg = config_manager.get_registry_config()
    cli_args = [
        "--source", str(args.get("source", reg_cfg.get("fdic_default_source", "both"))),
        "--mode", str(args.get("mode", "incremental")),
    ]
    if "limit" in args and args["limit"] is not None:
        cli_args += ["--limit", str(args["limit"])]
    return await asyncio.to_thread(_run_scraper, "fetch_fdic.py", cli_args)


@activity.defn(name="run_usaspending")
async def run_usaspending_activity(args: dict) -> dict:
    args = args or {}
    import datetime
    current_fy = args.get("fiscal_year", datetime.date.today().year)
    cli_args = [
        "--fiscal-year", str(current_fy),
        "--mode", str(args.get("mode", "incremental")),
    ]
    if "limit" in args and args["limit"] is not None:
        cli_args += ["--limit", str(args["limit"])]
    return await asyncio.to_thread(_run_scraper, "fetch_usaspending.py", cli_args)


@activity.defn(name="run_propublica")
async def run_propublica_activity(args: dict) -> dict:
    args = args or {}
    cli_args = ["--mode", str(args.get("mode", "incremental"))]
    if args.get("state"):
        cli_args += ["--state", str(args["state"])]
    if "limit" in args and args["limit"] is not None:
        cli_args += ["--limit", str(args["limit"])]
    return await asyncio.to_thread(_run_scraper, "fetch_propublica.py", cli_args)


@activity.defn(name="run_sam_gov")
async def run_sam_gov_activity(args: dict) -> dict:
    args = args or {}
    cli_args = ["--mode", str(args.get("mode", "incremental"))]
    if "limit" in args and args["limit"] is not None:
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

