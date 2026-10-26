"""
CMS NPI (National Provider Identifier) Bulk Downloader
Downloads healthcare provider data — doctors, hospitals, clinics — with
name, phone, email, address from the official CMS bulk CSV.

Source: https://download.cms.gov/nppes/NPI_Files.html
Records: ~8 million US healthcare providers
No API key required — public bulk download.

Usage:
    python fetch_cms_npi.py                    # download + ingest all (8M)
    python fetch_cms_npi.py --limit 50000      # first 50K records
    python fetch_cms_npi.py --dry-run          # download only, no DB write
"""

import argparse
import csv
import io
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── project imports ────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))
from db_connector import get_connection, db_info
from lead_builder import build_us_lead
from contact_validator import validate_contact, lead_score_from_contact
from http_client import http_client

# ── constants ──────────────────────────────────────────────────────────────────
NPI_FILES_PAGE   = "https://download.cms.gov/nppes/NPI_Files.html"
NPI_DIRECT_URL   = "https://download.cms.gov/nppes/NPPES_Data_Dissemination_June_2025.zip"
NPI_FALLBACK_URL = "https://download.cms.gov/nppes/NPPES_Data_Dissemination_May_2025.zip"
OUTPUT_DIR       = Path("output/us/bulk/cms_npi")
BATCH_SIZE       = 500    # commit every N records

# NPI CSV column mapping (columns from the official NPPES dissemination file)
COL_MAP = {
    "NPI":                          "npi",
    "Entity Type Code":             "entity_type",       # 1=individual, 2=org
    "Provider Organization Name (Legal Business Name)": "org_name",
    "Provider Last Name (Legal Name)":  "last_name",
    "Provider First Name":          "first_name",
    "Provider Middle Name":         "middle_name",
    "Provider Credential Text":     "credential",
    "Provider Business Practice Location Address Telephone Number": "phone",
    "Provider Business Practice Location Address Fax Number": "fax",
    "Healthcare Provider Taxonomy Code_1": "taxonomy",
    "Provider Business Practice Location Address City Name": "city",
    "Provider Business Practice Location Address State Name": "state",
    "Provider Business Practice Location Address Postal Code": "zip",
    "Healthcare Provider Primary Taxonomy Switch_1": "is_primary_taxonomy",
    "Provider Gender Code":         "gender",
}


def _clean(v):
    if v is None: return None
    v = str(v).strip()
    return v if v else None


def _e164_us(phone_raw):
    """Normalize US phone to E.164 using libphonenumber."""
    if not phone_raw:
        return None
    res = validate_phone(phone_raw, country="US")
    return res.get("phone")


def _get_latest_npi_url():
    """Try to find the most recent NPI file URL from the CMS page."""
    try:
        r = http_client.get(NPI_FILES_PAGE, timeout=15)
        if r.status_code == 200:
            # Find zip links
            matches = re.findall(
                r'href="(https://download\.cms\.gov/nppes/NPPES_Data_Dissemination[^"]+\.zip)"',
                r.text
            )
            if matches:
                return matches[0]
    except Exception:
        pass
    return NPI_DIRECT_URL


def download_npi_zip(output_dir: Path) -> Path:
    """Download the NPI bulk ZIP file if not already present."""
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "npi_bulk.zip"

    if zip_path.exists() and zip_path.stat().st_size > 1_000_000:
        print(f"  [+] Using cached ZIP: {zip_path} ({zip_path.stat().st_size/1e6:.0f} MB)")
        return zip_path

    url = _get_latest_npi_url()
    print(f"  [*] Downloading NPI bulk file from:\n      {url}")
    print(f"      This is ~900 MB — may take several minutes...")

    try:
        r = http_client.get(url, stream=True, timeout=60)
        if r.status_code != 200:
            print(f"  [!] Primary URL failed ({r.status_code}), trying fallback...")
            r = http_client.get(NPI_FALLBACK_URL, stream=True, timeout=60)

        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    mb  = downloaded / 1e6
                    print(f"\r  Downloading... {mb:.0f} MB / {total/1e6:.0f} MB ({pct:.0f}%)",
                          end="", flush=True)
        print(f"\n  [+] Downloaded: {zip_path} ({downloaded/1e6:.0f} MB)")
        return zip_path
    except Exception as e:
        print(f"  [!] Download failed: {e}")
        raise


def _row_to_lead(row: dict) -> dict | None:
    """Convert one NPI CSV row into a us_leads-compatible dict."""
    entity = _clean(row.get("Entity Type Code", ""))

    if entity == "1":
        # Individual provider
        first = _clean(row.get("Provider First Name"))
        last  = _clean(row.get("Provider Last Name (Legal Name)"))
        if not last: return None
        full_name = f"{first or ''} {last}".strip()
        company_name = _clean(row.get("Provider Organization Name (Legal Business Name)")) or \
                       f"{full_name} Practice"
    else:
        # Organisation
        company_name = _clean(row.get("Provider Organization Name (Legal Business Name)"))
        if not company_name: return None
        full_name   = None
        first = last = None

    phone_raw = _clean(row.get(
        "Provider Business Practice Location Address Telephone Number"))
    phone = _e164_us(phone_raw)

    city     = _clean(row.get("Provider Business Practice Location Address City Name"))
    state    = _clean(row.get("Provider Business Practice Location Address State Name"))
    zip_code = _clean(row.get("Provider Business Practice Location Address Postal Code", ""))
    if zip_code: zip_code = zip_code[:5]
    taxonomy = _clean(row.get("Healthcare Provider Taxonomy Code_1"))
    npi_id   = _clean(row.get("NPI"))

    # Validate contact
    contact = validate_contact(
        email=None,          # NPI file has no email field
        phone=phone,
        country="US",
        skip_mx=True,
    )

    lead_score = lead_score_from_contact(
        contact,
        person_quality=70,
        company_quality=75,
        seniority_level="C_SUITE" if entity == "2" else "MANAGER",
    )

    import json as _json
    return {
        "id":                    f"npi_{npi_id}",
        "full_name":             full_name,
        "first_name":            first,
        "last_name":             last,
        "title":                 "Healthcare Provider" if entity == "1" else "Organization",
        "standardized_title":    taxonomy or "Healthcare Provider",
        "seniority_level":       "DIRECTOR" if entity == "2" else "MANAGER",
        "department":            "HEALTHCARE",
        "email":                 None,
        "email_status":          "MISSING",
        "email_confidence_score":0,
        "phone":                 contact.get("phone"),
        "is_current":            True,
        "company_id":            None,
        "company_name":          company_name,
        "domain":                None,
        "industry":              "Healthcare",
        "city":                  city,
        "state":                 state,
        "state_code":            state[:2].upper() if state and len(state) >= 2 else None,
        "zip_code":              zip_code,
        "country":               "United States",
        "person_quality_score":  70,
        "company_quality_score": 75,
        "lead_score":            lead_score,
        "api_source":            "CMS_NPI",
        "person":  _json.dumps({
            "full_name": full_name, "first_name": first, "last_name": last,
            "npi": npi_id, "entity_type": entity,
            "taxonomy": taxonomy, "credential": _clean(row.get("Provider Credential Text")),
        }),
        "company": _json.dumps({
            "name": company_name, "industry": "Healthcare",
            "address": {"city": city, "state": state, "zip_code": zip_code,
                        "country": "United States"},
        }),
        "contact": _json.dumps(contact),
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


def run(limit: int = 0, dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  CMS NPI Healthcare Provider Bulk Ingest")
    print(f"{'='*60}")
    print(f"  DB      : {db_info()}")
    print(f"  Limit   : {limit:,} (0 = all)")
    print(f"  Dry run : {dry_run}")
    print(f"{'='*60}\n")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = download_npi_zip(OUTPUT_DIR)

    conn = get_connection() if not dry_run else None
    cur  = conn.cursor() if conn else None

    inserted = errors = skipped = 0
    start = datetime.now(timezone.utc)

    print("\n  [*] Opening ZIP and streaming CSV...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Find the main NPI data file (largest CSV)
        csv_names = [n for n in zf.namelist()
                     if n.endswith(".csv") and "npidata_pfile" in n.lower()]
        if not csv_names:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_names:
            print("  [!] No CSV found in ZIP")
            return

        csv_name = sorted(csv_names, key=lambda n: zf.getinfo(n).file_size, reverse=True)[0]
        print(f"  [+] Reading: {csv_name}")

        with zf.open(csv_name) as raw:
            text_stream = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
            reader = csv.DictReader(text_stream)

            for i, row in enumerate(reader):
                if limit and i >= limit:
                    break

                if i % 5000 == 0 and i > 0:
                    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                    rate = i / elapsed if elapsed > 0 else 0
                    print(f"\r  Processed {i:,} | inserted {inserted:,} | "
                          f"errors {errors} | {rate:.0f} rec/s", end="", flush=True)

                try:
                    lead = _row_to_lead(row)
                    if not lead:
                        skipped += 1
                        continue

                    if not dry_run:
                        _upsert(cur, lead)
                        inserted += 1
                        if inserted % BATCH_SIZE == 0:
                            conn.commit()
                    else:
                        inserted += 1
                        if i < 3:
                            print(f"\n  [DRY] {lead.get('company_name')} | "
                                  f"phone={lead.get('phone')} | state={lead.get('state_code')}")
                except Exception as e:
                    errors += 1
                    if errors <= 5:
                        print(f"\n  [ERR] row {i}: {e}")
                    if not dry_run and conn:
                        conn.rollback()

    if not dry_run and conn:
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM us_leads WHERE api_source='CMS_NPI'")
        db_count = cur.fetchone()[0]
        conn.close()

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n\n  {'-'*58}")
    print(f"  CMS NPI complete in {elapsed:.0f}s")
    print(f"  Inserted : {inserted:,}")
    print(f"  Skipped  : {skipped:,} (no name)")
    print(f"  Errors   : {errors}")
    if not dry_run:
        print(f"  DB total : {db_count:,} NPI records in us_leads")
    print(f"  {'-'*58}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",   type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)
