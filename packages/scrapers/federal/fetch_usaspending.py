"""
USASpending.gov Federal Contractors Scraper
Fetches federal contract recipients with company name, address, and contact info.

Source: https://api.usaspending.gov
Records: 500K+ federal contractors
No API key required.

Usage:
    python fetch_usaspending.py
    python fetch_usaspending.py --limit 50000
    python fetch_usaspending.py --dry-run
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))
try:
    from packages.infrastructure.config_manager import config_manager
    from packages.infrastructure.db_connector import get_connection, release_connection, db_info
    from packages.domain.contact_validator import validate_contact, lead_score_from_contact
    from packages.infrastructure.http_client import get_http_client
    from packages.domain.geo_validator import format_postal_code
except ImportError:
    from config_manager import config_manager
    from db_connector import get_connection, release_connection, db_info
    from contact_validator import validate_contact, lead_score_from_contact
    from http_client import get_http_client
    from geo_validator import format_postal_code

API_BASE     = "https://api.usaspending.gov/api/v2"
BATCH_COMMIT = 200
PAGE_SIZE    = 100

# Award types: A=contracts, B=purchase orders, C=delivery orders, D=definitive contracts
AWARD_TYPES  = ["A", "B", "C", "D"]

# NAICS codes covering major B2B industries
NAICS_SECTORS = [
    "23",   # Construction
    "31",   # Manufacturing
    "32",   # Manufacturing
    "33",   # Manufacturing
    "42",   # Wholesale Trade
    "48",   # Transportation
    "49",   # Warehousing
    "51",   # Information Technology
    "52",   # Finance
    "54",   # Professional Services
    "56",   # Administrative Services
    "61",   # Education
    "62",   # Healthcare
    "72",   # Accommodation/Food
    "81",   # Other Services
]


def _upsert(cur, record: dict):
    from packages.infrastructure.staging_writer import upsert_staging_record
    upsert_staging_record(cur, record, source="USASPENDING")


def _fetch_recipients(naics_prefix: str, page: int = 1, fiscal_year: int | None = None) -> dict:
    """Fetch award recipients for a NAICS prefix."""
    today = datetime.now(timezone.utc).date()
    if fiscal_year:
        fy = int(fiscal_year)
        start_date = f"{fy - 1}-10-01"
        end_date = min(today, datetime(fy, 9, 30, tzinfo=timezone.utc).date()).strftime("%Y-%m-%d")
        if start_date > end_date:
            start_date = f"{today.year - 2}-01-01"
    else:
        start_date = f"{today.year - 2}-01-01"
        end_date = today.strftime("%Y-%m-%d")

    payload = {
        "filters": {
            "award_type_codes": AWARD_TYPES,
            "naics_codes": {"require": [naics_prefix]},
            "time_period": [{"start_date": start_date, "end_date": end_date}],
        },
        "fields": [
            "Recipient Name", "recipient_id",
            "Place of Performance City Name",
            "Place of Performance State Code",
            "Place of Performance Zip5",
            "Awarding Agency Name",
            "NAICS Code", "NAICS Description",
            "Award Amount", "Award ID",
        ],
        "sort":    "Award Amount",
        "order":   "desc",
        "limit":   PAGE_SIZE,
        "page":    page,
    }
    try:
        client = get_http_client()
        r = client.post(
            f"{API_BASE}/search/spending_by_award/",
            json=payload, timeout=30
        )
        if r.status_code == 200:
            return r.json()
        print(f"\n  [!] USASpending HTTP {r.status_code} (naics={naics_prefix}, page={page}): {r.text[:150]}")
    except Exception as e:
        print(f"\n  [ERR] USASpending request failed: {e}")
    return {}


def _fetch_recipient_detail(recipient_id: str) -> dict:
    """Get detailed contact info for a specific recipient."""
    try:
        client = get_http_client()
        r = client.get(
            f"{API_BASE}/recipient/{recipient_id}/",
            timeout=15
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _make_lead(award: dict) -> dict | None:
    name = award.get("Recipient Name") or award.get("recipient_name")
    if not name or name.strip().upper() in ("REDACTED", "UNKNOWN", ""):
        return None

    naics      = str(award.get("NAICS Code", "") or "")
    naics_desc = award.get("NAICS Description", "") or ""
    city       = award.get("Place of Performance City Name", "") or ""
    state      = award.get("Place of Performance State Code", "") or ""
    raw_zip    = award.get("Place of Performance Zip5", "") or ""
    zip_code   = format_postal_code(str(raw_zip).strip(), "US") if raw_zip else None
    rid        = award.get("recipient_id") or award.get("Recipient ID") or ""
    amount     = award.get("Award Amount", 0) or 0

    uid = f"usa_{rid[:20]}_{naics[:4]}" if rid else \
          f"usa_{name.replace(' ','_')[:20]}_{naics[:4]}"

    contact = validate_contact(email=None, phone=None, country="US", skip_mx=True)
    score   = lead_score_from_contact(
        contact, person_quality=40, company_quality=80, seniority_level=None
    )

    # Boost score for large contractors
    if amount and float(amount) > 1_000_000:
        score = min(100, score + 10)

    return {
        "id":                    uid,
        "full_name":             None,
        "first_name":            None,
        "last_name":             None,
        "title":                 None,
        "standardized_title":    None,
        "seniority_level":       None,
        "department":            None,
        "email":                 None,
        "email_status":          "MISSING",
        "email_confidence_score":0,
        "phone":                 None,
        "is_current":            None,
        "company_name":          name.title(),
        "industry":              naics_desc or "Federal Contractor",
        "naics_code":            naics,
        "city":                  city.title() if city else None,
        "state":                 state,
        "state_code":            state[:2].upper() if state else None,
        "zip_code":              zip_code,
        "country":               "United States",
        "person_quality_score":  40,
        "company_quality_score": 80,
        "lead_score":            score,
        "api_source":            "USASPENDING",
        "person":  json.dumps({"is_organization_level": True}),
        "company": json.dumps({
            "name": name, "naics_code": naics,
            "industry": naics_desc, "award_amount": amount,
            "address": {"city": city, "state": state, "zip_code": zip_code,
                        "country": "United States"},
        }),
        "contact": json.dumps(contact),
    }


def run(limit: int = 0, dry_run: bool = False, mode: str = "incremental", fiscal_year: int | None = None):
    print(f"\n{'='*60}")
    print(f"  USASpending.gov Federal Contractors Scraper")
    print(f"{'='*60}")
    print(f"  DB      : {db_info()}")
    print(f"  Mode    : {mode}")
    if fiscal_year:
        print(f"  FY      : {fiscal_year}")
    print(f"  Limit   : {limit or 'unlimited'}")
    print(f"  Dry run : {dry_run}")
    print(f"{'='*60}\n")

    conn = get_connection() if not dry_run else None
    cur  = conn.cursor() if conn else None

    inserted = errors = 0
    seen     = set()
    start    = datetime.now(timezone.utc)
    db_count = 0

    try:
        for naics in NAICS_SECTORS:
            if limit and inserted >= limit:
                break
            page = 1
            while True:
                if limit and inserted >= limit:
                    break

                data   = _fetch_recipients(naics, page, fiscal_year=fiscal_year)
                awards = data.get("results", [])
                if not awards:
                    break

                for award in awards:
                    if limit and inserted >= limit:
                        break
                    uid_key = (award.get("Recipient Name", "") + naics)
                    if uid_key in seen:
                        continue
                    seen.add(uid_key)

                    lead = _make_lead(award)
                    if not lead:
                        continue
                    try:
                        if not dry_run:
                            _upsert(cur, lead)
                        inserted += 1
                        if dry_run and inserted <= 3:
                            print(f"  [DRY] {lead['company_name']} | "
                                  f"naics={lead['naics_code']} | state={lead['state_code']}")
                    except Exception as e:
                        errors += 1
                        if errors <= 5:
                            print(f"\n  [ERR USASPENDING] {lead.get('company_name')}: {e}")
                        if conn:
                            conn.rollback()

                if not dry_run and inserted % BATCH_COMMIT == 0 and inserted > 0:
                    conn.commit()
                    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                    rate = inserted / elapsed if elapsed > 0 else 0
                    print(f"\r  NAICS {naics} | page {page} | "
                          f"inserted={inserted:,} | {rate:.0f}/s", end="", flush=True)

                meta     = data.get("page_metadata", {})
                has_next = meta.get("hasNext", False)
                if not has_next or page >= 20:   # cap at 20 pages per NAICS
                    break
                page += 1
                time.sleep(0.2)

        total_attempted = inserted + errors
        threshold = float(config_manager.get_registry_config().get("error_threshold_pct", 25.0))
        if total_attempted >= 20 and (errors / total_attempted * 100.0) > threshold:
            raise RuntimeError(
                f"USASpending error rate {(errors / total_attempted * 100.0):.1f}% exceeded threshold {threshold}%"
            )

        if not dry_run and conn:
            conn.commit()
            cur.execute("SELECT COUNT(*) FROM staging_dataextraction.staging_companies WHERE source='USASPENDING'")
            db_count = cur.fetchone()[0]
        else:
            db_count = inserted
    finally:
        if cur:
            cur.close()
        if conn:
            release_connection(conn)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n\n  {'─'*58}")
    print(f"  USASpending complete in {elapsed:.0f}s")
    print(f"  Inserted : {inserted:,}")
    print(f"  Errors   : {errors}")
    print(f"  DB total : {db_count:,} USASpending records in staging_companies")
    print(f"  {'─'*58}\n")
    print(
        "ACTIVITY_RESULT_JSON:" + json.dumps({
            "status": "SUCCESS",
            "source": "USASPENDING",
            "inserted_count": inserted,
            "error_count": errors,
            "db_total": db_count,
            "dry_run": dry_run,
        }),
        flush=True,
    )
    return inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fiscal-year", type=int, default=None)
    parser.add_argument("--mode",        default="incremental", choices=["incremental", "full"])
    parser.add_argument("--limit",       type=int, default=0)
    parser.add_argument("--dry-run",     action="store_true")
    args = parser.parse_args()
    run(limit=args.limit, dry_run=args.dry_run, mode=args.mode, fiscal_year=args.fiscal_year)
