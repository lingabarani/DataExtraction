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

sys.path.insert(0, str(Path(__file__).parent))
from db_connector import get_connection, db_info
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
    data = {k: v for k, v in record.items() if v is not None and v != ""}
    cols = list(data.keys())
    ph   = ", ".join(["%s"] * len(cols))
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("id","created_at"))
    cur.execute(
        f"INSERT INTO us_leads ({', '.join(cols)}) VALUES ({ph}) "
        f"ON CONFLICT (id) DO UPDATE SET {sets}, updated_at = NOW()",
        [data[c] for c in cols]
    )


def _fetch_recipients(naics_prefix: str, page: int = 1) -> dict:
    """Fetch award recipients for a NAICS prefix."""
    payload = {
        "filters": {
            "award_type_codes": AWARD_TYPES,
            "naics_codes": {"require": [naics_prefix]},
            "time_period": [{"start_date": "2023-01-01", "end_date": "2025-12-31"}],
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
    except Exception as e:
        print(f"\n  [ERR] {e}")
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


def run(limit: int = 0, dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  USASpending.gov Federal Contractors Scraper")
    print(f"{'='*60}")
    print(f"  DB      : {db_info()}")
    print(f"  Limit   : {limit or 'unlimited'}")
    print(f"  Dry run : {dry_run}")
    print(f"{'='*60}\n")

    conn = get_connection() if not dry_run else None
    cur  = conn.cursor() if conn else None

    inserted = errors = 0
    seen     = set()
    start    = datetime.now(timezone.utc)

    for naics in NAICS_SECTORS:
        if limit and inserted >= limit:
            break
        page = 1
        while True:
            if limit and inserted >= limit:
                break

            data   = _fetch_recipients(naics, page)
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
                    if conn: conn.rollback()

            if not dry_run and inserted % BATCH_COMMIT == 0:
                conn.commit()
                elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                rate = inserted / elapsed if elapsed > 0 else 0
                print(f"\r  NAICS {naics} | page {page} | "
                      f"inserted={inserted:,} | {rate:.0f}/s", end="", flush=True)

            meta       = data.get("page_metadata", {})
            total_pages = meta.get("page", {})
            has_next   = meta.get("hasNext", False)
            if not has_next or page >= 20:   # cap at 20 pages per NAICS
                break
            page += 1
            time.sleep(0.2)

    if not dry_run and conn:
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM us_leads WHERE api_source='USASPENDING'")
        db_count = cur.fetchone()[0]
        conn.close()
    else:
        db_count = inserted

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n\n  {'─'*58}")
    print(f"  USASpending complete in {elapsed:.0f}s")
    print(f"  Inserted : {inserted:,}")
    print(f"  Errors   : {errors}")
    print(f"  DB total : {db_count:,} USASpending records in us_leads")
    print(f"  {'─'*58}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",   type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)
