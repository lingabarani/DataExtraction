"""
SAM.gov Federal Entity / Contractor Scraper
Fetches registered federal contractors with POC email, phone, name, address.

Source: https://api.sam.gov/entity-information/v3/entities
Records: 700K+ active federal contractors
Requires SAM.gov API key (saved in .env as SAM_GOV_API_KEY).

Usage:
    python fetch_sam_gov.py
    python fetch_sam_gov.py --limit 50000
    python fetch_sam_gov.py --dry-run
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from db_connector import get_connection, db_info
from contact_validator import validate_contact, lead_score_from_contact
from config_manager import get_secret
from http_client import get_http_client
from geo_validator import format_postal_code

SAM_API_KEY  = get_secret("SAM_GOV_API_KEY", "")
SAM_BASE     = "https://api.sam.gov/entity-information/v3/entities"
PAGE_SIZE    = 100
BATCH_COMMIT = 200

# NAICS codes to iterate over (major sectors)
NAICS_TARGETS = [
    "541511","541512","541519",   # IT
    "541330","541380","541690",   # Engineering
    "236220","238210","238220",   # Construction
    "336411","336412","336413",   # Aerospace
    "621111","621112","621498",   # Healthcare
    "611310","611430","611519",   # Education
    "518210","519130","519190",   # Data
    "423430","423690","424110",   # Wholesale
    "332710","332720","332810",   # Manufacturing
    "488510","488991","492110",   # Logistics
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


def _fetch_entities(naics: str, page_token: str = None) -> dict:
    params = {
        "api_key":             SAM_API_KEY,
        "samRegistered":       "Yes",
        "primaryNaics":        naics,
        "registrationStatus":  "A",
        "purposeOfRegistrationCode": "Z2",
        "limit":               PAGE_SIZE,
    }
    if page_token:
        params["page"] = page_token

    try:
        client = get_http_client()
        r = client.get(SAM_BASE, params=params,
                       headers={"Accept": "application/json"},
                       timeout=30)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 401:
            print(f"\n  [!] SAM.gov 401 UNAUTHORIZED — key not active yet")
        elif r.status_code == 429:
            print(f"\n  [!] SAM.gov rate limited — backing off...")
        else:
            print(f"\n  [!] SAM.gov HTTP {r.status_code}: {r.text[:100]}")
    except requests.exceptions.Timeout:
        print(f"\n  [!] SAM.gov timeout — server slow...")
    except Exception as e:
        print(f"\n  [!] SAM.gov error: {e}")
    return {}


def _extract_poc(entity: dict) -> dict:
    """Extract Point of Contact info from entity record."""
    reg = entity.get("registration", {}) or {}
    poc_fields = [
        "governmentBusinessPOC",
        "electronicBusinessPOC",
        "governmentBusinessAlternatePOC",
    ]
    for field in poc_fields:
        poc = reg.get(field, {}) or {}
        if poc.get("email") or poc.get("usPhone"):
            return poc
    return {}


def _make_lead(entity: dict) -> dict | None:
    reg  = entity.get("registration", {}) or {}
    name = reg.get("legalBusinessName") or reg.get("dbaName")
    if not name: return None

    uei   = reg.get("ueiSAM","") or reg.get("ueiDUNS","")
    naics = reg.get("primaryNaics","")
    cage  = reg.get("cageCode","")
    addr  = reg.get("mailingAddress", {}) or reg.get("physicalAddress", {}) or {}
    city  = addr.get("city","")
    state = addr.get("stateOrProvinceCode","")
    raw_zip = addr.get("zipCode","")
    zip_c = format_postal_code(str(raw_zip).strip(), "US") if raw_zip else None
    country = addr.get("countryCode","USA")

    poc   = _extract_poc(entity)
    email = poc.get("email") or poc.get("usEmail")
    phone = poc.get("usPhone") or poc.get("nonUSPhone")
    poc_first = (poc.get("firstName","") or "").strip()
    poc_last  = (poc.get("lastName","") or "").strip()
    poc_name  = f"{poc_first} {poc_last}".strip() or None
    poc_title = (poc.get("title","") or "").strip() or None

    if phone:
        import re
        digits = re.sub(r"\D","",str(phone))
        phone  = f"+1{digits}" if len(digits)==10 else phone

    contact = validate_contact(
        email=email, phone=phone, country="US", skip_mx=True,
        pre_verified_status="VERIFIED" if email else None,
    )

    if poc_name:
        title = poc_title or "Point of Contact"
        std_title = poc_title or "POC"
        seniority = "DIRECTOR"
        dept = "EXECUTIVE"
        person_data = {
            "full_name": poc_name, "title": poc_title,
            "first_name": poc_first, "last_name": poc_last,
            "seniority_level": "DIRECTOR",
        }
        score = lead_score_from_contact(
            contact, person_quality=85, company_quality=90, seniority_level="DIRECTOR"
        )
    else:
        title = None
        std_title = None
        seniority = None
        dept = None
        person_data = {"is_organization_level": True}
        score = lead_score_from_contact(
            contact, person_quality=40, company_quality=90, seniority_level=None
        )

    uid = f"sam_{uei[:20]}" if uei else f"sam_{name.replace(' ','_')[:20]}"

    return {
        "id":                    uid,
        "full_name":             poc_name,
        "first_name":            poc_first or None,
        "last_name":             poc_last or None,
        "title":                 title,
        "standardized_title":    std_title,
        "seniority_level":       seniority,
        "department":            dept,
        "email":                 contact.get("email"),
        "email_status":          contact.get("email_status","MISSING"),
        "email_confidence_score":contact.get("email_confidence_score",0),
        "phone":                 contact.get("phone"),
        "is_current":            True if poc_name else None,
        "company_name":          name,
        "industry":              "Federal Contractor",
        "naics_code":            naics,
        "city":                  city.title() if city else None,
        "state":                 state,
        "state_code":            state[:2].upper() if state else None,
        "zip_code":              zip_c,
        "country":               "United States",
        "person_quality_score":  85 if poc_name else 40,
        "company_quality_score": 90,
        "lead_score":            score,
        "api_source":            "SAM_GOV",
        "person":  json.dumps(person_data),
        "company": json.dumps({
            "name": name, "uei": uei, "cage_code": cage,
            "naics_code": naics, "industry": "Federal Contractor",
            "address": {"city": city, "state": state,
                        "zip_code": zip_c, "country": country},
        }),
        "contact": json.dumps(contact),
    }


def run(limit: int = 0, dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  SAM.gov Federal Contractor Scraper")
    print(f"{'='*60}")
    print(f"  DB      : {db_info()}")
    print(f"  Key     : {SAM_API_KEY[:20]}..." if SAM_API_KEY else "  Key     : NOT SET")
    print(f"  Limit   : {limit or 'unlimited'}")
    print(f"  Dry run : {dry_run}")
    print(f"{'='*60}\n")

    if not SAM_API_KEY:
        print("  [!] SAM_GOV_API_KEY not set in .env — skipping")
        return 0

    conn = get_connection() if not dry_run else None
    cur  = conn.cursor() if conn else None

    inserted = errors = 0
    seen     = set()
    start    = datetime.now(timezone.utc)

    for naics in NAICS_TARGETS:
        if limit and inserted >= limit:
            break

        page_token = None
        page_num   = 0

        while True:
            if limit and inserted >= limit:
                break

            data     = _fetch_entities(naics, page_token)
            entities = data.get("entityData", [])
            if not entities:
                break

            for entity in entities:
                if limit and inserted >= limit:
                    break
                reg = entity.get("registration", {}) or {}
                uei = reg.get("ueiSAM","")
                if uei in seen: continue
                seen.add(uei)

                lead = _make_lead(entity)
                if not lead: continue

                try:
                    if not dry_run:
                        _upsert(cur, lead)
                    inserted += 1
                    if dry_run and inserted <= 3:
                        print(f"  [DRY SAM] {lead['company_name']} | "
                              f"email={lead.get('email')} | phone={lead.get('phone')}")
                except Exception as e:
                    errors += 1
                    if conn: conn.rollback()

            if not dry_run and inserted % BATCH_COMMIT == 0:
                conn.commit()
                elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                rate = inserted / elapsed if elapsed else 0
                print(f"\r  SAM naics={naics} | inserted={inserted:,} | "
                      f"{rate:.0f}/s", end="", flush=True)

            # Pagination
            links = data.get("links", {})
            next_url = links.get("nextPage")
            if not next_url or page_num >= 50:
                break
            page_num  += 1
            page_token = page_num
            time.sleep(0.3)

    if not dry_run and conn:
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM us_leads WHERE api_source='SAM_GOV'")
        db_count = cur.fetchone()[0]
        conn.close()
    else:
        db_count = inserted

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n\n  {'─'*58}")
    print(f"  SAM.gov complete in {elapsed:.0f}s")
    print(f"  Inserted : {inserted:,}")
    print(f"  Errors   : {errors}")
    print(f"  DB total : {db_count:,} SAM.gov records in us_leads")
    print(f"  {'─'*58}\n")
    return inserted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",   type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)
