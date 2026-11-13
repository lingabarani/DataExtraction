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

FDIC_API    = "https://banks.data.fdic.gov/api"
NCUA_URL    = "https://www.ncua.gov/files/publications/analysis/call-report-data-2024-Q4.zip"
OUTPUT_DIR  = Path("output/us/bulk/fdic_ncua")
BATCH_COMMIT= 100


def _upsert(cur, record: dict):
    from packages.infrastructure.staging_writer import upsert_staging_record
    upsert_staging_record(cur, record, source="FDIC")


# ── FDIC ──────────────────────────────────────────────────────────────────────

def fetch_fdic(conn, cur, dry_run: bool, limit: int = 0, stats: dict | None = None) -> int:
    print("  [*] Fetching FDIC bank data...")
    inserted = 0
    errors   = 0
    offset   = 0
    page_size = min(1000, limit) if limit and limit > 0 else 1000
    client   = get_http_client()

    while True:
        if limit and inserted >= limit:
            break
        batch_req = min(page_size, limit - inserted) if limit else page_size
        r = client.get(f"{FDIC_API}/institutions", params={
            "fields": "NAME,STNAME,CITY,ZIP,STALP,PHONE,ACTIVE,CERT,"
                      "ASSET,NAMEHCR,CHRTAGNT,CEO",
            "filters": "ACTIVE:1",
            "limit":   batch_req,
            "offset":  offset,
            "sort_by": "ASSET",
            "sort_order": "DESC",
        }, timeout=20)

        if r.status_code != 200:
            if offset == 0:
                raise RuntimeError(f"FDIC API HTTP {r.status_code}: {r.text[:200]}")
            break

        data  = r.json()
        banks = data.get("data", [])
        if not banks:
            break

        for b in banks:
            if limit and inserted >= limit:
                break
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
                errors += 1
                if errors <= 5:
                    print(f"\n  [ERR FDIC] {name}: {e}")
                if conn:
                    conn.rollback()

        if not dry_run and inserted % BATCH_COMMIT == 0 and inserted > 0:
            conn.commit()
            print(f"\r  FDIC: {inserted:,} banks inserted", end="", flush=True)

        meta     = data.get("meta", {})
        total    = meta.get("total", 0)
        offset  += batch_req
        if offset >= total or (limit and inserted >= limit):
            break
        time.sleep(0.1)

    if not dry_run and conn:
        conn.commit()
    if stats is not None:
        stats["errors"] = stats.get("errors", 0) + errors
    print(f"\n  [+] FDIC: {inserted:,} banks (errors={errors})")
    return inserted


# ── NCUA ──────────────────────────────────────────────────────────────────────

def fetch_ncua(conn, cur, dry_run: bool, limit: int = 0, stats: dict | None = None) -> int:
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
    errors = 0
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
                    if limit and inserted >= limit:
                        break
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
                    except Exception as e:
                        errors += 1
                        if errors <= 5:
                            print(f"\n  [ERR NCUA] {name}: {e}")
                        if conn:
                            conn.rollback()

                    if not dry_run and inserted % BATCH_COMMIT == 0 and inserted > 0:
                        conn.commit()
                        print(f"\r  NCUA: {inserted:,} credit unions", end="", flush=True)

    except Exception as e:
        errors += 1
        print(f"  [!] NCUA error: {e}")

    if not dry_run and conn:
        conn.commit()
    if stats is not None:
        stats["errors"] = stats.get("errors", 0) + errors
    print(f"\n  [+] NCUA: {inserted:,} credit unions (errors={errors})")
    return inserted


def run(source: str = "both", limit: int = 0, dry_run: bool = False, mode: str = "incremental"):
    print(f"\n{'='*60}")
    print(f"  FDIC Banks + NCUA Credit Unions Scraper")
    print(f"{'='*60}")
    print(f"  DB      : {db_info()}")
    print(f"  Source  : {source}")
    print(f"  Mode    : {mode}")
    print(f"  Limit   : {limit or 'unlimited'}")
    print(f"  Dry run : {dry_run}")
    print(f"{'='*60}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection() if not dry_run else None
    cur  = conn.cursor() if conn else None

    total = 0
    db_count = 0
    stats = {"errors": 0}
    start = datetime.now(timezone.utc)

    try:
        if source in ("both", "fdic"):
            total += fetch_fdic(conn, cur, dry_run, limit=limit, stats=stats)
        if source in ("both", "ncua"):
            remaining = (limit - total) if limit and limit > 0 else 0
            if not limit or remaining > 0:
                total += fetch_ncua(conn, cur, dry_run, limit=remaining, stats=stats)

        errors = stats.get("errors", 0)
        total_attempted = total + errors
        threshold = float(config_manager.get_registry_config().get("error_threshold_pct", 25.0))
        if total_attempted >= 20 and (errors / total_attempted * 100.0) > threshold:
            raise RuntimeError(
                f"FDIC+NCUA error rate {(errors / total_attempted * 100.0):.1f}% exceeded threshold {threshold}%"
            )

        if not dry_run and conn:
            cur.execute(
                "SELECT COUNT(*) FROM staging_dataextraction.staging_companies WHERE source IN ('FDIC','FDIC_BANKS','NCUA')"
            )
            db_count = cur.fetchone()[0]
        else:
            db_count = total
    finally:
        if cur:
            cur.close()
        if conn:
            release_connection(conn)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n  {'─'*58}")
    print(f"  FDIC+NCUA complete in {elapsed:.0f}s")
    print(f"  Total inserted : {total:,}")
    print(f"  Errors         : {stats.get('errors', 0)}")
    print(f"  DB total       : {db_count:,} bank/CU records in staging_companies")
    print(f"  {'─'*58}\n")
    print(
        "ACTIVITY_RESULT_JSON:" + json.dumps({
            "status": "SUCCESS",
            "source": "FDIC",
            "inserted_count": total,
            "error_count": stats.get("errors", 0),
            "db_total": db_count,
            "dry_run": dry_run,
        }),
        flush=True,
    )
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source",  default="both", choices=["both", "fdic", "ncua"])
    parser.add_argument("--mode",    default="incremental", choices=["incremental", "full"])
    parser.add_argument("--limit",   type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(source=args.source, limit=args.limit, dry_run=args.dry_run, mode=args.mode)
