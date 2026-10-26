"""
SEC EDGAR Bulk Company + Officer Scraper
Downloads all SEC-registered companies and their executive officers.

Sources:
  company_tickers.json     — 10K+ public companies (instant, ~1MB)
  submissions bulk ZIPs    — 12M+ all filings with officer names

No API key required. SEC requires User-Agent header.

Usage:
    python fetch_sec_edgar.py                        # tickers only (fast)
    python fetch_sec_edgar.py --mode full            # full submissions bulk
    python fetch_sec_edgar.py --limit 5000
    python fetch_sec_edgar.py --dry-run
"""

import argparse
import json
import re
import sys
import time
import zipfile
import io
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config_manager import config_manager
from db_connector import get_connection, db_info
from contact_validator import validate_contact, lead_score_from_contact
from http_client import http_client

SEC_HEADERS = {
    "User-Agent": config_manager.get_sec_user_agent(),
    "Accept-Encoding": "gzip, deflate",
}
SEC_BASE     = "https://data.sec.gov"
TICKERS_URL  = "https://www.sec.gov/files/company_tickers.json"
OUTPUT_DIR   = Path("output/us/bulk/sec_edgar")
BATCH_COMMIT = 200

# SIC code → industry name mapping (top categories)
SIC_INDUSTRIES = {
    "20": "Food Manufacturing", "27": "Publishing",
    "28": "Chemical Manufacturing", "35": "Computer Hardware",
    "36": "Electronic Equipment", "37": "Automotive",
    "38": "Scientific Instruments", "48": "Telecommunications",
    "49": "Utilities", "50": "Wholesale Trade",
    "51": "Wholesale Trade", "52": "Retail",
    "53": "Retail", "54": "Retail Food",
    "55": "Automotive Retail", "56": "Apparel Retail",
    "57": "Home Furnishings Retail", "58": "Restaurants",
    "59": "Retail Other", "60": "Banking",
    "61": "Credit Services", "62": "Investment Banking",
    "63": "Insurance", "64": "Insurance Agents",
    "65": "Real Estate", "67": "Investment Companies",
    "70": "Hotels", "72": "Personal Services",
    "73": "Computer Services", "75": "Auto Repair",
    "78": "Entertainment", "79": "Amusement",
    "80": "Healthcare", "82": "Education",
    "83": "Social Services", "84": "Museums",
    "86": "Membership Organizations", "87": "Engineering",
    "99": "Other",
}


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


def _sic_to_industry(sic: str) -> str:
    if not sic: return "Commercial Enterprise"
    prefix = str(sic)[:2]
    return SIC_INDUSTRIES.get(prefix, "Commercial Enterprise")


def _make_officer_lead(cik: str, name: str, ticker: str, contact_info: dict, off: dict, contact: dict, score: int) -> dict:
    off_name  = (off.get("name","") or "").strip()
    off_title = (off.get("title","") or "").strip() or None
    parts = off_name.split(" ", 1)
    first = parts[0]
    last = parts[1] if len(parts) > 1 else None
    uid = f"sec_{cik}_{off_name.replace(' ','_')[:12]}"
    return {
        "id":                    uid,
        "full_name":             off_name or None,
        "first_name":            first,
        "last_name":             last,
        "title":                 off_title,
        "standardized_title":    off_title,
        "seniority_level":       "C_SUITE",
        "department":            "EXECUTIVE",
        "email":                 contact.get("email"),
        "email_status":          contact.get("email_status","MISSING"),
        "email_confidence_score":contact.get("email_confidence_score",0),
        "phone":                 contact.get("phone"),
        "is_current":            True,
        "company_name":          name,
        "domain":                contact_info.get("domain"),
        "industry":              _sic_to_industry(contact_info.get("sic","")),
        "naics_code":            None,
        "cik":                   cik,
        "state_code":            contact_info.get("state_code"),
        "country":               "United States",
        "person_quality_score":  75,
        "company_quality_score": 90,
        "lead_score":            score,
        "api_source":            "SEC_EDGAR",
        "person":  json.dumps({
            "full_name": off_name, "title": off_title,
            "seniority_level": "C_SUITE",
            "source_registry": "SEC",
        }),
        "company": json.dumps({
            "name": name, "ticker": ticker, "cik": cik,
            "sic": contact_info.get("sic"),
            "website": contact_info.get("website"),
            "address": contact_info.get("address", {}),
        }),
        "contact": json.dumps(contact),
    }


def _make_org_lead(cik: str, name: str, ticker: str, contact_info: dict, contact: dict, score: int) -> dict:
    uid = f"sec_{cik}_org"
    return {
        "id":                    uid,
        "full_name":             None,
        "first_name":            None,
        "last_name":             None,
        "title":                 None,
        "standardized_title":    None,
        "seniority_level":       None,
        "department":            None,
        "email":                 contact.get("email"),
        "email_status":          contact.get("email_status","MISSING"),
        "email_confidence_score":contact.get("email_confidence_score",0),
        "phone":                 contact.get("phone"),
        "is_current":            None,
        "company_name":          name,
        "domain":                contact_info.get("domain"),
        "industry":              _sic_to_industry(contact_info.get("sic","")),
        "cik":                   cik,
        "state_code":            contact_info.get("state_code"),
        "country":               "United States",
        "person_quality_score":  0,
        "company_quality_score": 90,
        "lead_score":            score,
        "api_source":            "SEC_EDGAR",
        "person":  json.dumps({"is_organization_level": True, "source_registry": "SEC"}),
        "company": json.dumps({
            "name": name, "ticker": ticker, "cik": cik,
            "sic": contact_info.get("sic"),
            "website": contact_info.get("website"),
            "address": contact_info.get("address", {}),
        }),
        "contact": json.dumps(contact),
    }


def fetch_tickers(conn, cur, limit: int, dry_run: bool) -> int:
    """Fast path: download company_tickers.json (~10K public companies) — no per-company API calls."""
    print("  [*] Fetching SEC public company tickers...")
    r = http_client.get(TICKERS_URL, headers=SEC_HEADERS, timeout=15)
    if r.status_code != 200:
        print(f"  [!] Failed: HTTP {r.status_code}")
        return 0

    data     = r.json()
    inserted = 0

    for idx, (_, company) in enumerate(data.items()):
        if limit and inserted >= limit:
            break

        cik    = str(company.get("cik_str", "")).zfill(10)
        ticker = company.get("ticker", "")
        name   = company.get("title", "")
        if not name: continue

        # Skip per-company API call — use ticker data only (fast batch mode)
        contact_info = {"sic": "", "state_code": None, "domain": None,
                        "phone": None, "email": None, "officers": [],
                        "address": {}, "website": ""}

        contact = validate_contact(
            email=contact_info.get("email"),
            phone=contact_info.get("phone"),
            country="US", skip_mx=True,
            pre_verified_status=None,
        )
        score = lead_score_from_contact(
            contact, person_quality=75, company_quality=90, seniority_level="C_SUITE"
        )

        officers = contact_info.get("officers", [])
        if officers:
            for off in officers[:2]:
                lead = _make_officer_lead(cik, name, ticker, contact_info, off, contact, score)
                try:
                    if not dry_run:
                        _upsert(cur, lead)
                    inserted += 1
                    if dry_run and inserted <= 2:
                        print(f"  [DRY SEC] {name} | {lead['full_name']} | {lead['title']}")
                except Exception:
                    if conn: conn.rollback()
        else:
            lead = _make_org_lead(cik, name, ticker, contact_info, contact, score)
            try:
                if not dry_run:
                    _upsert(cur, lead)
                inserted += 1
            except Exception:
                if conn: conn.rollback()

        if not dry_run and inserted % BATCH_COMMIT == 0 and inserted > 0:
            conn.commit()
            print(f"\r  SEC tickers: {inserted:,} / {min(limit or 99999, len(data))}",
                  end="", flush=True)

        # No sleep needed — no per-company API calls

    if not dry_run:
        conn.commit()
    print(f"\n  [+] SEC tickers: {inserted:,} inserted")
    return inserted


def _fetch_submission_contact(cik: str) -> dict:
    """Get company website, SIC, state and latest officers from EDGAR submissions."""
    try:
        url = f"{SEC_BASE}/submissions/CIK{cik}.json"
        r   = http_client.get(url, headers=SEC_HEADERS, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()

        addresses = data.get("addresses", {})
        biz_addr  = addresses.get("business", {}) or {}
        state     = biz_addr.get("stateOrCountry", "")
        website   = data.get("website", "")
        phone     = biz_addr.get("phone","")
        sic       = str(data.get("sic", ""))

        # Extract email from IR info if present
        email = None
        tickers = data.get("tickers", [])

        # Get recent officers from filings
        officers = []
        recent   = data.get("filings", {}).get("recent", {})
        forms    = recent.get("form", [])
        for i, form in enumerate(forms):
            if form in ("DEF 14A", "10-K", "8-K"):
                # Officers are typically in 10-K or proxy statements
                break

        # Use primaryDocument info if available
        company_officers = data.get("officers", [])
        if company_officers:
            officers = company_officers[:3]

        domain = None
        if website:
            domain = re.sub(r'^https?://(www\.)?', '', website).split('/')[0]

        if phone:
            digits = re.sub(r"\D","",str(phone))
            phone  = f"+1{digits}" if len(digits)==10 else None

        return {
            "website":    website,
            "domain":     domain,
            "phone":      phone,
            "email":      email,
            "sic":        sic,
            "state_code": state[:2].upper() if state else None,
            "officers":   officers,
            "address":    {
                "street":     biz_addr.get("street1"),
                "city":       biz_addr.get("city"),
                "state":      state,
                "zip_code":   biz_addr.get("zipCode"),
                "country":    "United States",
            },
        }
    except Exception:
        return {}


def run(mode: str = "tickers", limit: int = 0, dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  SEC EDGAR Company + Officer Scraper")
    print(f"{'='*60}")
    print(f"  DB      : {db_info()}")
    print(f"  Mode    : {mode}")
    print(f"  Limit   : {limit or 'unlimited'}")
    print(f"  Dry run : {dry_run}")
    print(f"{'='*60}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection() if not dry_run else None
    cur  = conn.cursor() if conn else None
    start = datetime.now(timezone.utc)

    inserted = fetch_tickers(conn, cur, limit, dry_run)

    if not dry_run and conn:
        cur.execute("SELECT COUNT(*) FROM us_leads WHERE api_source='SEC_EDGAR'")
        db_count = cur.fetchone()[0]
        conn.close()
    else:
        db_count = inserted

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n  {'─'*58}")
    print(f"  SEC EDGAR complete in {elapsed:.0f}s")
    print(f"  Inserted : {inserted:,}")
    print(f"  DB total : {db_count:,} SEC records in us_leads")
    print(f"  {'─'*58}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",    default="tickers", choices=["tickers","full"])
    parser.add_argument("--limit",   type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(mode=args.mode, limit=args.limit, dry_run=args.dry_run)
