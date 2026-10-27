"""
DataExtraction — Federal Scraper Activities
==========================================
Thin subprocess wrappers around all 6 federal registry scrapers.

CRITICAL: Scraper files (fetch_*.py) are NEVER imported or modified here.
          They run as managed subprocesses in their original directory.
          This guarantees zero regression in scraper behavior (ADR-003).
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

from temporalio import activity

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
    """
    Executes fetch_cms_npi.py (CMS National Provider Identifier registry).

    Args:
        args: {
            "limit": int (default 50000),
            "mode": "incremental" | "full"
        }
    Returns: {"source": "CMS_NPI", "exit_code": 0, "stdout_tail": "..."}
    """
    cli_args = [
        "--limit", str(args.get("limit", 50000)),
        "--mode", args.get("mode", "incremental"),
    ]
    return _run_scraper("fetch_cms_npi.py", cli_args)


@activity.defn(name="run_sec_edgar")
async def run_sec_edgar_activity(args: dict) -> dict:
    """
    Executes fetch_sec_edgar.py (SEC EDGAR financial filings).

    Args:
        args: {
            "form_types": list[str] (default ["10-K", "10-Q"]),
            "mode": "incremental" | "full"
        }
    """
    form_types = ",".join(args.get("form_types", ["10-K", "10-Q"]))
    cli_args = [
        "--form-types", form_types,
        "--mode", args.get("mode", "incremental"),
    ]
    return _run_scraper("fetch_sec_edgar.py", cli_args)


@activity.defn(name="run_fdic")
async def run_fdic_activity(args: dict) -> dict:
    """
    Executes fetch_fdic.py (FDIC bank registry).

    Args:
        args: {"mode": "incremental" | "full", "limit": int}
    """
    cli_args = ["--mode", args.get("mode", "incremental")]
    if "limit" in args:
        cli_args += ["--limit", str(args["limit"])]
    return _run_scraper("fetch_fdic.py", cli_args)


@activity.defn(name="run_usaspending")
async def run_usaspending_activity(args: dict) -> dict:
    """
    Executes fetch_usaspending.py (USASpending.gov federal contracts).

    Args:
        args: {"fiscal_year": int, "mode": "incremental" | "full"}
    """
    import datetime
    current_fy = args.get("fiscal_year", datetime.date.today().year)
    cli_args = [
        "--fiscal-year", str(current_fy),
        "--mode", args.get("mode", "incremental"),
    ]
    return _run_scraper("fetch_usaspending.py", cli_args)


@activity.defn(name="run_propublica")
async def run_propublica_activity(args: dict) -> dict:
    """
    Executes fetch_propublica.py (ProPublica nonprofit data).

    Args:
        args: {"mode": "incremental" | "full", "limit": int}
    """
    cli_args = ["--mode", args.get("mode", "incremental")]
    if "limit" in args:
        cli_args += ["--limit", str(args["limit"])]
    return _run_scraper("fetch_propublica.py", cli_args)


@activity.defn(name="run_sam_gov")
async def run_sam_gov_activity(args: dict) -> dict:
    """
    Executes fetch_sam_gov.py (SAM.gov government contractors).
    Note: SAM.gov API requires an API key (SAM_GOV_API_KEY env var).

    Args:
        args: {"mode": "incremental" | "full", "limit": int}
    """
    cli_args = ["--mode", args.get("mode", "incremental")]
    if "limit" in args:
        cli_args += ["--limit", str(args["limit"])]
    return _run_scraper("fetch_sam_gov.py", cli_args)
