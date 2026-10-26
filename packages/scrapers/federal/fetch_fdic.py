"""
FDIC BankFind + NCUA Credit Union Data Scraper
Both sources provide institution name, address, CEO/officer contacts, phone.

Sources:
  FDIC: https://banks.data.fdic.gov/api  (~4,700 banks)
  NCUA: https://www.ncua.gov/files/publications/analysis/call-report-data-2024-Q4.zip
        (~4,700 credit unions)

No API key required for either.

Usage:
    python fetch_fdic.py
    python fetch_fdic.py --dry-run
    python fetch_fdic.py --source fdic    # FDIC only
    python fetch_fdic.py --source ncua    # NCUA only
"""

import argparse
import csv
import io
import json
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from db_connector import get_connection, db_info
from contact_validator import validate_contact, lead_score_from_contact
from http_client import get_http_client
from geo_validator import format_postal_code

FDIC_API    = "https://banks.data.fdic.gov/api"
NCUA_URL    = "https://www.ncua.gov/files/publications/analysis/call-report-data-2024-Q4.zip"
OUTPUT_DIR  = Path("output/us/bulk/fdic_ncua")
BATCH_COMMIT= 100


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


# ── FDIC ──────────────────────────────────────────────────────────────────────

def fetch_fdic(conn, cur, dry_run: bool) -> int:
    print("  [*] Fetching FDIC bank data...")
    inserted = 0
    offset   = 0
    limit    = 1000
    client   = get_http_client()

    while True:
        r = client.get(f"{FDIC_API}/institutions", params={
            "fields": "NAME,STNAME,CITY,ZIP,STALP,PHONE,ACTIVE,CERT,"
                      "ASSET,NAMEHCR,CHRTAGNT,CEO",
            "filters": "ACTIVE:1",
            "limit":   limit,
            "offset":  offset,
            "sort_by": "ASSET",
            "sort_order": "DESC",
        }, timeout=20)

        if r.status_code != 200:
            break

        data  = r.json()
        banks = data.get("data", [])
        if not banks:
            break

        for b in banks:
            d    = b.get("data", b)
            name = d.get("NAME") or d.get("name")
            if not name:
                continue

            phone   = str(d.get("PHONE") or "").strip()
            if phone and not phone.startswith("+"):
                import re
                digits = re.sub(r"\D","",phone)
                phone  = f"+1{digits}" if len(digits)==10 else None
            else:
                phone = None

            ceo   = (d.get("CEO") or "").strip()
            state = d.get("STALP") or d.get("stname","")[:2]
            cert  = str(d.get("CERT",""))
            raw_zip = str(d.get("ZIP","")).strip()
            zip_c = format_postal_code(raw_zip, "US") if raw_zip else None

            contact = validate_contact(
                email=None, phone=phone, country="US", skip_mx=True
            )
            score = lead_score_from_contact(
                contact, person_quality=80 if ceo else 40, company_quality=90,
                seniority_level="C_SUITE" if ceo else None
            )

            first = last = None
            if ceo:
                parts = ceo.split(" ", 1)
                first = parts[0]
                last = parts[1] if len(parts) > 1 else None
                title = "Chief Executive Officer"
                std_title = "CEO"
                seniority = "C_SUITE"
                dept = "EXECUTIVE"
                person_data = {
                    "full_name": ceo, "title": "CEO",
                    "seniority_level": "C_SUITE",
                }
            else:
                title = None
                std_title = None
                seniority = None
                dept = None
                person_data = {"is_organization_level": True}

            lead = {
                "id":                    f"fdic_{cert}",
                "full_name":             ceo or None,
                "first_name":            first,
                "last_name":             last,
                "title":                 title,
                "standardized_title":    std_title,
                "seniority_level":       seniority,
                "department":            dept,
                "email":                 None,
                "email_status":          "MISSING",
                "email_confidence_score":0,
                "phone":                 contact.get("phone"),
                "is_current":            True if ceo else None,
                "company_name":          name,
                "industry":              "Banking and Finance",
                "city":                  d.get("CITY","").title(),
                "state":                 state,
                "state_code":            state[:2].upper() if state else None,
                "zip_code":              zip_c,
                "country":               "United States",
                "person_quality_score":  80 if ceo else 40,
                "company_quality_score": 90,
                "lead_score":            score,
                "api_source":            "FDIC",
                "person":  json.dumps(person_data),
                "company": json.dumps({
                    "name": name, "industry": "Banking",
                    "cert_number": cert,
                    "assets": d.get("ASSET"),
                    "address": {"city": d.get("CITY"), "state": state,
                                "zip_code": zip_c,
                                "country": "United States"},
                }),
                "contact": json.dumps(contact),
            }

            try:
                if not dry_run:
                    _upsert(cur, lead)
                inserted += 1
                if dry_run and inserted <= 2:
                    print(f"  [DRY FDIC] {name} | CEO={ceo} | phone={phone}")
            except Exception as e:
                if conn: conn.rollback()

        if not dry_run and inserted % BATCH_COMMIT == 0:
            conn.commit()
            print(f"\r  FDIC: {inserted:,} banks inserted", end="", flush=True)

        meta     = data.get("meta", {})
        total    = meta.get("total", 0)
        offset  += limit
        if offset >= total:
            break
        time.sleep(0.1)

    if not dry_run:
        conn.commit()
    print(f"\n  [+] FDIC: {inserted:,} banks")
    return inserted


# ── NCUA ──────────────────────────────────────────────────────────────────────

def fetch_ncua(conn, cur, dry_run: bool) -> int:
    print("\n  [*] Fetching NCUA credit union data...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUTPUT_DIR / "ncua_call_report.zip"

    if not (zip_path.exists() and zip_path.stat().st_size > 100_000):
        print(f"  [*] Downloading NCUA ZIP from {NCUA_URL}...")
        try:
            client = get_http_client()
            if not client.download_file(NCUA_URL, zip_path, timeout=60):
                print(f"  [!] NCUA download failed")
                return 0
            print(f"  [+] Downloaded: {zip_path.stat().st_size/1e6:.1f} MB")
        except Exception as e:
            print(f"  [!] NCUA download error: {e}")
            return 0

    inserted = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            csv_files = [n for n in zf.namelist()
                         if n.lower().endswith(".csv") and "fs220" in n.lower()]
            if not csv_files:
                csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_files:
                print("  [!] No CSV in NCUA ZIP")
                return 0

            fname = csv_files[0]
            print(f"  [+] Reading: {fname}")
            with zf.open(fname) as raw:
                stream = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                reader = csv.DictReader(stream)
                for row in reader:
                    name  = row.get("CU_NAME") or row.get("CREDIT_UNION_NAME")
                    if not name: continue
                    cu_id = row.get("CU_NUMBER") or row.get("CHARTER_NUMBER", "")
                    phone = row.get("PHONE","") or row.get("TELEPHONE","")
                    city  = row.get("CITY","")
                    state = row.get("STATE","") or row.get("STATE_CODE","")
                    raw_zip = row.get("ZIP_CODE","")
                    zip_c = format_postal_code(str(raw_zip).strip(), "US") if raw_zip else None
                    ceo   = (row.get("CEO_NAME","") or row.get("MANAGER_NAME","")).strip()

                    import re
                    if phone:
                        d = re.sub(r"\D","",str(phone))
                        phone = f"+1{d}" if len(d)==10 else None

                    contact = validate_contact(email=None, phone=phone,
                                               country="US", skip_mx=True)
                    score   = lead_score_from_contact(
                        contact, person_quality=75 if ceo else 40, company_quality=80,
                        seniority_level="C_SUITE" if ceo else None
                    )

                    first = last = None
                    if ceo:
                        parts = ceo.split(" ", 1)
                        first = parts[0]
                        last = parts[1] if len(parts) > 1 else None
                        title = "CEO / Manager"
                        std_title = "CEO"
                        seniority = "C_SUITE"
                        dept = "EXECUTIVE"
                        person_data = {"full_name": ceo, "title": "CEO", "seniority_level": "C_SUITE"}
                    else:
                        title = None
                        std_title = None
                        seniority = None
                        dept = None
                        person_data = {"is_organization_level": True}

                    lead = {
                        "id":                    f"ncua_{cu_id}",
                        "full_name":             ceo or None,
                        "first_name":            first, "last_name": last,
                        "title":                 title,
                        "standardized_title":    std_title,
                        "seniority_level":       seniority,
                        "department":            dept,
                        "email":                 None,
                        "email_status":          "MISSING",
                        "email_confidence_score":0,
                        "phone":                 contact.get("phone"),
                        "is_current":            True if ceo else None,
                        "company_name":          name,
                        "industry":              "Banking and Finance",
                        "city":                  city.title() if city else None,
                        "state":                 state,
                        "state_code":            state[:2].upper() if state else None,
                        "zip_code":              zip_c,
                        "country":               "United States",
                        "person_quality_score":  75 if ceo else 40,
                        "company_quality_score": 80,
                        "lead_score":            score,
                        "api_source":            "NCUA",
                        "person":  json.dumps(person_data),
                        "company": json.dumps({"name":name,"industry":"Credit Union",
                                               "charter_number": cu_id,
                                               "address":{"city":city,"state":state,
                                                          "zip_code": zip_c,
                                                          "country":"United States"}}),
                        "contact": json.dumps(contact),
                    }
                    try:
                        if not dry_run:
                            _upsert(cur, lead)
                        inserted += 1
                        if dry_run and inserted <= 2:
                            print(f"  [DRY NCUA] {name} | CEO={ceo} | phone={phone}")
                    except Exception:
                        if conn: conn.rollback()

                    if not dry_run and inserted % BATCH_COMMIT == 0:
                        conn.commit()
                        print(f"\r  NCUA: {inserted:,} credit unions", end="", flush=True)

    except Exception as e:
        print(f"  [!] NCUA error: {e}")

    if not dry_run and conn:
        conn.commit()
    print(f"\n  [+] NCUA: {inserted:,} credit unions")
    return inserted


def run(source: str = "both", dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  FDIC Banks + NCUA Credit Unions Scraper")
    print(f"{'='*60}")
    print(f"  DB      : {db_info()}")
    print(f"  Source  : {source}")
    print(f"  Dry run : {dry_run}")
    print(f"{'='*60}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection() if not dry_run else None
    cur  = conn.cursor() if conn else None

    total = 0
    start = datetime.now(timezone.utc)

    if source in ("both", "fdic"):
        total += fetch_fdic(conn, cur, dry_run)
    if source in ("both", "ncua"):
        total += fetch_ncua(conn, cur, dry_run)

    if not dry_run and conn:
        cur.execute("SELECT COUNT(*) FROM us_leads WHERE api_source IN ('FDIC','NCUA')")
        db_count = cur.fetchone()[0]
        conn.close()
    else:
        db_count = total

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n  {'─'*58}")
    print(f"  FDIC+NCUA complete in {elapsed:.0f}s")
    print(f"  Total inserted : {total:,}")
    print(f"  DB total       : {db_count:,} bank/CU records in us_leads")
    print(f"  {'─'*58}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source",  default="both", choices=["both","fdic","ncua"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(source=args.source, dry_run=args.dry_run)
