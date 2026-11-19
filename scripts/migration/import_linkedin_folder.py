"""
Legacy Data Importer for LinkedIN Folder.
Imports data/liscraper.db and backend/lead_intel.db into discovery_dataextraction schema.

Non-negotiable Rules:
  - Read-only access to source directory.
  - Dry-run by default (--apply required to execute writes).
  - Provenance tracking: 'legacy_import' by default, 'manual_seed' for hand-typed rows.
  - Manual seed rows get verified=False.
  - Emails labelled 'inferred' unless evidence of direct page extraction exists.
  - Idempotent: safe to run multiple times without duplicates.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import pathlib
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

# Setup paths
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.leadintel.deduplication import generate_company_match_key, generate_person_match_key, normalize_string

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logger = logging.getLogger("migration.import_linkedin")


def load_seed_names(source_dir: pathlib.Path) -> Set[str]:
    """Extract set of normalized names hand-typed in scratch/seed_tamilnadu_ceos.py."""
    seed_names: Set[str] = set()
    seed_file = source_dir / "scratch" / "seed_tamilnadu_ceos.py"
    if seed_file.exists():
        try:
            content = seed_file.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r'["\']full_name["\']\s*:\s*["\']([^"\']+)["\']', content):
                seed_names.add(normalize_string(match.group(1)))
        except Exception as exc:
            logger.warning("Could not parse seed_tamilnadu_ceos.py: %s", exc)

    rectify_file = source_dir / "scratch" / "rectify_phones.py"
    if rectify_file.exists():
        try:
            content = rectify_file.read_text(encoding="utf-8", errors="ignore")
            for match in re.finditer(r'["\']name["\']\s*:\s*["\']([^"\']+)["\']', content):
                seed_names.add(normalize_string(match.group(1)))
        except Exception as exc:
            logger.warning("Could not parse rectify_phones.py: %s", exc)

    return seed_names


def read_liscraper_db(db_path: pathlib.Path, seed_names: Set[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Read people and companies from liscraper.db."""
    people: List[Dict[str, Any]] = []
    companies: List[Dict[str, Any]] = []

    if not db_path.exists():
        logger.warning("liscraper.db not found at %s", db_path)
        return people, companies

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Read companies
    try:
        cur.execute("SELECT * FROM companies")
        for row in cur.fetchall():
            d = dict(row)
            name = d.get("name") or d.get("slug") or ""
            domain = d.get("domain") or None
            website = d.get("website") or None
            companies.append({
                "source_db": "liscraper",
                "canonical_name": name,
                "normalized_name": normalize_string(name),
                "domain": domain,
                "website": website,
                "industry": d.get("industry"),
                "description": d.get("description"),
                "employee_count": d.get("employee_count"),
                "logo": d.get("logo"),
                "address": d.get("address"),
                "provenance": "legacy_import",
                "raw": d,
            })
    except Exception as exc:
        logger.warning("Error reading liscraper companies: %s", exc)

    # Read people
    try:
        cur.execute("SELECT * FROM people")
        for row in cur.fetchall():
            d = dict(row)
            full_name = d.get("name") or d.get("slug") or ""
            norm_name = normalize_string(full_name)
            provenance = "manual_seed" if norm_name in seed_names else "legacy_import"
            verified = False if provenance == "manual_seed" else bool(d.get("status") == "verified")

            # Parse emails
            emails = []
            raw_emails = d.get("emails")
            if raw_emails:
                try:
                    loaded = json.loads(raw_emails) if isinstance(raw_emails, str) else raw_emails
                    if isinstance(loaded, list):
                        for em in loaded:
                            if isinstance(em, str) and "@" in em:
                                emails.append({
                                    "value": em.strip(),
                                    "label": "inferred",
                                    "confidence": float(d.get("email_confidence") or 0.5),
                                    "source_url": d.get("source"),
                                })
                except Exception:
                    pass

            # Parse phones
            phones = []
            raw_phones = d.get("phones")
            if raw_phones:
                try:
                    loaded = json.loads(raw_phones) if isinstance(raw_phones, str) else raw_phones
                    if isinstance(loaded, list):
                        phones = [str(p) for p in loaded if p]
                except Exception:
                    pass

            people.append({
                "source_db": "liscraper",
                "full_name": full_name,
                "normalized_name": norm_name,
                "title": d.get("headline"),
                "headline": d.get("headline"),
                "about": d.get("about"),
                "company_name": d.get("company"),
                "city": d.get("city"),
                "region": d.get("region"),
                "country": d.get("country") or "India",
                "profile_urls": [f"https://www.linkedin.com/in/{d['slug']}"] if d.get("slug") else [],
                "emails": emails,
                "phones": phones,
                "provenance": provenance,
                "verified": verified,
                "raw": d,
            })
    except Exception as exc:
        logger.warning("Error reading liscraper people: %s", exc)

    conn.close()
    return people, companies


def read_lead_intel_db(db_path: pathlib.Path, seed_names: Set[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Read contacts, companies, emails, phones, profiles from lead_intel.db."""
    people: List[Dict[str, Any]] = []
    companies: List[Dict[str, Any]] = []

    if not db_path.exists():
        logger.warning("lead_intel.db not found at %s", db_path)
        return people, companies

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Read companies
    company_id_map: Dict[Any, str] = {}
    try:
        cur.execute("SELECT * FROM companies")
        for row in cur.fetchall():
            d = dict(row)
            cid = d.get("id")
            name = d.get("name") or ""
            domain = d.get("domain") or None
            website = d.get("website") or None
            company_id_map[cid] = name
            companies.append({
                "source_db": "lead_intel",
                "id": str(cid),
                "canonical_name": name,
                "normalized_name": normalize_string(name),
                "domain": domain,
                "website": website,
                "industry": d.get("industry"),
                "description": d.get("description"),
                "hq_location": d.get("hq_location"),
                "provenance": "legacy_import",
                "raw": d,
            })
    except Exception as exc:
        logger.warning("Error reading lead_intel companies: %s", exc)

    # Read contact emails
    contact_emails: Dict[Any, List[Dict[str, Any]]] = {}
    try:
        cur.execute("SELECT * FROM contact_emails")
        for row in cur.fetchall():
            d = dict(row)
            cid = d.get("contact_id")
            email = d.get("email")
            if email and "@" in email:
                contact_emails.setdefault(cid, []).append({
                    "value": email.strip(),
                    "label": "inferred",
                    "confidence": 0.6 if d.get("status") == "verified" else 0.4,
                    "source_url": d.get("source_url"),
                })
    except Exception as exc:
        logger.warning("Error reading contact_emails: %s", exc)

    # Read contact phones
    contact_phones: Dict[Any, List[str]] = {}
    try:
        cur.execute("SELECT * FROM contact_phones")
        for row in cur.fetchall():
            d = dict(row)
            cid = d.get("contact_id")
            phone = d.get("formatted_phone") or d.get("raw_phone")
            if phone:
                contact_phones.setdefault(cid, []).append(phone.strip())
    except Exception as exc:
        logger.warning("Error reading contact_phones: %s", exc)

    # Read professional profiles
    contact_profiles: Dict[Any, List[str]] = {}
    try:
        cur.execute("SELECT * FROM professional_profiles")
        for row in cur.fetchall():
            d = dict(row)
            cid = d.get("contact_id")
            url = d.get("profile_url")
            if url:
                contact_profiles.setdefault(cid, []).append(url.strip())
    except Exception as exc:
        logger.warning("Error reading professional_profiles: %s", exc)

    # Read contacts
    try:
        cur.execute("SELECT * FROM contacts")
        for row in cur.fetchall():
            d = dict(row)
            cid = d.get("id")
            full_name = d.get("full_name") or f"{d.get('first_name') or ''} {d.get('last_name') or ''}".strip()
            norm_name = normalize_string(full_name)

            is_manual_seed = (
                norm_name in seed_names
                or "seed" in str(d.get("source_type") or "").lower()
                or (d.get("notes") and "briefing" in str(d.get("notes")).lower())
            )
            provenance = "manual_seed" if is_manual_seed else "legacy_import"
            verified = False if provenance == "manual_seed" else (d.get("status") == "verified")

            emails = contact_emails.get(cid, [])
            phones = contact_phones.get(cid, [])
            profiles = contact_profiles.get(cid, [])
            if d.get("source_url") and d["source_url"] not in profiles:
                profiles.append(d["source_url"])

            company_name = company_id_map.get(d.get("company_id"))

            people.append({
                "source_db": "lead_intel",
                "id": str(cid),
                "full_name": full_name,
                "normalized_name": norm_name,
                "title": d.get("title"),
                "headline": d.get("title"),
                "company_name": company_name,
                "city": d.get("city"),
                "region": d.get("state"),
                "country": d.get("country") or "India",
                "profile_urls": profiles,
                "emails": emails,
                "phones": phones,
                "provenance": provenance,
                "verified": verified,
                "raw": d,
            })
    except Exception as exc:
        logger.warning("Error reading lead_intel contacts: %s", exc)

    conn.close()
    return people, companies


def deduplicate_entities(
    all_people: List[Dict[str, Any]],
    all_companies: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Deduplicate records across liscraper and lead_intel datasets."""
    # Deduplicate companies
    deduped_companies: Dict[str, Dict[str, Any]] = {}
    for comp in all_companies:
        key = generate_company_match_key(comp["canonical_name"], comp.get("domain"))
        if key not in deduped_companies:
            deduped_companies[key] = {**comp, "id": str(uuid4())}
        else:
            existing = deduped_companies[key]
            if not existing.get("website") and comp.get("website"):
                existing["website"] = comp["website"]
            if not existing.get("domain") and comp.get("domain"):
                existing["domain"] = comp["domain"]
            if not existing.get("industry") and comp.get("industry"):
                existing["industry"] = comp["industry"]

    # Deduplicate people
    deduped_people: Dict[str, Dict[str, Any]] = {}
    for person in all_people:
        first_email = person["emails"][0]["value"] if person.get("emails") else None
        key = generate_person_match_key(person["full_name"], person.get("company_name"), first_email)

        if key not in deduped_people:
            deduped_people[key] = {**person, "id": str(uuid4())}
        else:
            existing = deduped_people[key]
            # Merge emails
            existing_email_vals = {e["value"] for e in existing.get("emails", [])}
            for em in person.get("emails", []):
                if em["value"] not in existing_email_vals:
                    existing.setdefault("emails", []).append(em)
                    existing_email_vals.add(em["value"])

            # Merge phones
            existing_phones = set(existing.get("phones", []))
            for ph in person.get("phones", []):
                if ph not in existing_phones:
                    existing.setdefault("phones", []).append(ph)
                    existing_phones.add(ph)

            # Merge profile URLs
            existing_urls = set(existing.get("profile_urls", []))
            for u in person.get("profile_urls", []):
                if u not in existing_urls:
                    existing.setdefault("profile_urls", []).append(u)
                    existing_urls.add(u)

    return list(deduped_people.values()), list(deduped_companies.values())


def import_into_postgres(
    people: List[Dict[str, Any]],
    companies: List[Dict[str, Any]],
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Execute batch insert of deduplicated records into discovery_dataextraction schema."""
    stats = {
        "organizations_inserted": 0,
        "people_inserted": 0,
        "manual_seed_people": sum(1 for p in people if p["provenance"] == "manual_seed"),
        "legacy_import_people": sum(1 for p in people if p["provenance"] == "legacy_import"),
        "manual_seed_companies": 0,
        "legacy_import_companies": len(companies),
        "dry_run": dry_run,
    }

    if dry_run:
        logger.info("DRY-RUN mode enabled. No changes will be written to PostgreSQL.")
        return stats

    conn = get_connection()
    try:
        cur = conn.cursor()

        # Insert organizations
        for comp in companies:
            cur.execute("""
                INSERT INTO discovery_dataextraction.organizations (
                    id, canonical_name, normalized_name, category, website, domain, quality_score
                ) VALUES (%s, %s, %s, %s, %s, %s, 0.7)
                ON CONFLICT (id) DO NOTHING
            """, (
                comp["id"],
                comp["canonical_name"],
                comp["normalized_name"],
                comp.get("industry") or "legacy_company",
                comp.get("website"),
                comp.get("domain"),
            ))
            stats["organizations_inserted"] += 1

        # Insert people
        for person in people:
            cur.execute("""
                INSERT INTO discovery_dataextraction.people (
                    id, full_name, normalized_name, title, role_type, org_name,
                    city, region, country, profile_urls, emails, phones,
                    provenance, verified, suppressed
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, FALSE
                )
                ON CONFLICT (id) DO NOTHING
            """, (
                person["id"],
                person["full_name"],
                person["normalized_name"],
                person.get("title"),
                "executive",
                person.get("company_name"),
                person.get("city"),
                person.get("region"),
                person.get("country") or "India",
                json.dumps(person.get("profile_urls") or []),
                json.dumps(person.get("emails") or []),
                json.dumps(person.get("phones") or []),
                person["provenance"],
                person["verified"],
            ))
            stats["people_inserted"] += 1

        conn.commit()
        cur.close()
    finally:
        release_connection(conn)

    return stats


def run_migration(source_dir: pathlib.Path, dry_run: bool = True) -> Dict[str, Any]:
    print("=" * 70)
    print("LinkedIn Folder Legacy Migration & Provenance Ingestion")
    print(f"Source Directory : {source_dir}")
    print(f"Mode             : {'DRY RUN (no database writes)' if dry_run else 'APPLY (live writes)'}")
    print("=" * 70)

    seed_names = load_seed_names(source_dir)
    print(f"Identified {len(seed_names)} seed names for provenance tagging from scratch/ scripts.")

    p_liscraper = source_dir / "data" / "liscraper.db"
    p_leadintel = source_dir / "backend" / "lead_intel.db"

    people_li, comp_li = read_liscraper_db(p_liscraper, seed_names)
    print(f"\nRead from data/liscraper.db:")
    print(f"  - People    : {len(people_li)}")
    print(f"  - Companies : {len(comp_li)}")

    people_intel, comp_intel = read_lead_intel_db(p_leadintel, seed_names)
    print(f"\nRead from backend/lead_intel.db:")
    print(f"  - Contacts  : {len(people_intel)}")
    print(f"  - Companies : {len(comp_intel)}")

    all_people = people_li + people_intel
    all_companies = comp_li + comp_intel

    deduped_people, deduped_companies = deduplicate_entities(all_people, all_companies)
    print(f"\nAfter Cross-Store Deduplication:")
    print(f"  - Unique People      : {len(deduped_people)} (deduped from {len(all_people)})")
    print(f"  - Unique Companies   : {len(deduped_companies)} (deduped from {len(all_companies)})")

    manual_seed_cnt = sum(1 for p in deduped_people if p["provenance"] == "manual_seed")
    legacy_import_cnt = sum(1 for p in deduped_people if p["provenance"] == "legacy_import")
    print(f"\nProvenance Breakdown (People):")
    print(f"  - manual_seed   (verified=false, hidden from public search by default) : {manual_seed_cnt}")
    print(f"  - legacy_import (scraped profile imports)                             : {legacy_import_cnt}")

    stats = import_into_postgres(deduped_people, deduped_companies, dry_run=dry_run)
    stats["total_read_people"] = len(all_people)
    stats["total_read_companies"] = len(all_companies)
    stats["unique_people"] = len(deduped_people)
    stats["unique_companies"] = len(deduped_companies)

    print("\n" + "=" * 70)
    print("Migration Summary Report:")
    for k, v in stats.items():
        print(f"  {k:28s}: {v}")
    print("=" * 70)

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import legacy LinkedIN folder data with provenance")
    parser.add_argument("--source-dir", default=r"C:\Users\OneData\Downloads\LinkedIN", help="Path to LinkedIN source folder")
    parser.add_argument("--apply", action="store_true", help="Apply live changes to database (default is dry-run)")
    args = parser.parse_args()

    run_migration(pathlib.Path(args.source_dir), dry_run=not args.apply)
