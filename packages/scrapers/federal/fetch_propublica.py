"""
ProPublica Nonprofit Explorer API Scraper
Fetches 990 nonprofit tax filings — officers/directors with names, titles,
compensation, and organisation address/phone.

Source: https://projects.propublica.org/nonprofits/api/v2
Records: ~300K nonprofits, ~1M+ officers
No API key required.

Usage:
    python fetch_propublica.py                     # all states
    python fetch_propublica.py --state CA          # one state
    python fetch_propublica.py --limit 10000       # cap records
    python fetch_propublica.py --dry-run
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
from tax_validator import validate_ein

API_BASE  = "https://projects.propublica.org/nonprofits/api/v2"
BATCH_COMMIT = 200

US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY","DC"
]

SEARCH_TERMS = [
    "foundation","association","institute","society","council",
    "center","fund","trust","coalition","alliance","network",
    "hospital","health","school","education","community",
    "services","care","support","development","national",
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


def _search_orgs(term: str, state: str = None, page: int = 0) -> dict:
    params = {"q": term, "page": page}
    if state:
        params["state[id]"] = state
    try:
        client = get_http_client()
        r = client.get(f"{API_BASE}/search.json", params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _get_org_detail(ein: str) -> dict:
    try:
        client = get_http_client()
        r = client.get(f"{API_BASE}/organizations/{ein}.json", timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _make_lead(org: dict, officer: dict = None) -> dict | None:
    name = org.get("name") or org.get("strein")
    if not name:
        return None

    raw_ein = str(org.get("ein", "")).strip()
    ein_res = validate_ein(raw_ein)
    ein = ein_res["formatted"] if ein_res.get("is_valid") else raw_ein
    city  = org.get("city") or ""
    state = org.get("state") or ""
    ntee  = org.get("ntee_code") or ""
    phone = org.get("phone") or ""
    sub   = org.get("subsection_code") or ""

    # Officer details - strictly real values only, no synthetic persona
    o_name  = (officer.get("name", "") if officer else "").strip()
    o_title = (officer.get("title", "") if officer else "").strip() or None
    o_comp  = officer.get("compensation", 0) if officer else 0

    first = last = None
    if o_name:
        parts = o_name.split(" ", 1)
        first = parts[0]
        last  = parts[1] if len(parts) > 1 else None
        seniority = "DIRECTOR" if (o_title and any(w in o_title.upper() for w in ["DIRECTOR", "TRUSTEE", "OFFICER", "PRESIDENT", "CHAIR"])) else "EXECUTIVE"
        dept = "EXECUTIVE"
        person_data = {
            "full_name": o_name, "title": o_title,
            "compensation": o_comp, "seniority_level": seniority,
        }
        uid = f"pp_{raw_ein}_{o_name.replace(' ','_')[:12]}"
    else:
        o_title = None
        seniority = None
        dept = None
        person_data = {"is_organization_level": True}
        uid = f"pp_{raw_ein}_org"

    contact = validate_contact(
        email=None, phone=phone or None, country="US", skip_mx=True
    )
    score = lead_score_from_contact(
        contact, person_quality=65 if o_name else 40, company_quality=70,
        seniority_level=seniority
    )

    return {
        "id":                    uid,
        "full_name":             o_name or None,
        "first_name":            first,
        "last_name":             last,
        "title":                 o_title,
        "standardized_title":    o_title,
        "seniority_level":       seniority,
        "department":            dept,
        "email":                 None,
        "email_status":          "MISSING",
        "email_confidence_score":0,
        "phone":                 contact.get("phone"),
        "is_current":            True if o_name else None,
        "company_name":          name,
        "industry":              "Nonprofits and Associations",
        "ein":                   ein,
        "city":                  city,
        "state":                 state,
        "state_code":            state[:2].upper() if state else None,
        "country":               "United States",
        "person_quality_score":  65 if o_name else 40,
        "company_quality_score": 70,
        "lead_score":            score,
        "api_source":            "PROPUBLICA_990",
        "person":  json.dumps(person_data),
        "company": json.dumps({
            "name": name, "ein": ein, "ntee_code": ntee,
            "subsection": sub, "phone": phone,
            "address": {"city": city, "state": state, "country": "United States"},
        }),
        "contact": json.dumps(contact),
    }


def run(states: list = None, limit: int = 0, dry_run: bool = False):
    print(f"\n{'='*60}")
    print(f"  ProPublica 990 Nonprofit Scraper")
    print(f"{'='*60}")
    print(f"  DB       : {db_info()}")
    print(f"  States   : {states or 'ALL'}")
    print(f"  Limit    : {limit or 'unlimited'}")
    print(f"  Dry run  : {dry_run}")
    print(f"{'='*60}\n")

    conn = get_connection() if not dry_run else None
    cur  = conn.cursor() if conn else None

    inserted = errors = seen_eins = 0
    seen = set()
    start = datetime.now(timezone.utc)

    target_states = states or US_STATES

    for state in target_states:
        for term in SEARCH_TERMS:
            if limit and inserted >= limit:
                break
            page = 0
            while True:
                if limit and inserted >= limit:
                    break
                data = _search_orgs(term, state, page)
                orgs = data.get("organizations", [])
                if not orgs:
                    break

                for org in orgs:
                    if limit and inserted >= limit:
                        break
                    ein = str(org.get("ein", ""))
                    if ein in seen:
                        continue
                    seen.add(ein)

                    # Get org detail for officers
                    detail   = _get_org_detail(ein)
                    org_info = detail.get("organization", org)
                    filings  = detail.get("filings_with_data", [])
                    officers = []
                    if filings:
                        latest = filings[0]
                        officers = latest.get("officers", [])

                    if officers:
                        for officer in officers[:3]:  # top 3 officers
                            lead = _make_lead(org_info, officer)
                            if lead:
                                try:
                                    if not dry_run:
                                        _upsert(cur, lead)
                                    inserted += 1
                                    if dry_run and inserted <= 2:
                                        print(f"  [DRY] {lead['company_name']} | "
                                              f"{lead['full_name']} | {lead['title']}")
                                except Exception as e:
                                    errors += 1
                                    if conn: conn.rollback()
                    else:
                        lead = _make_lead(org_info)
                        if lead:
                            try:
                                if not dry_run:
                                    _upsert(cur, lead)
                                inserted += 1
                            except Exception:
                                errors += 1
                                if conn: conn.rollback()

                    if not dry_run and inserted % BATCH_COMMIT == 0:
                        conn.commit()
                        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                        rate = inserted / elapsed if elapsed > 0 else 0
                        print(f"\r  {state} | {term} | inserted={inserted:,} | "
                              f"{rate:.0f}/s", end="", flush=True)

                    time.sleep(0.05)  # be polite to ProPublica API

                page += 1
                total_pages = data.get("num_pages", 1)
                if page >= min(total_pages, 5):  # max 5 pages per term/state
                    break
                time.sleep(0.1)

    if not dry_run and conn:
        conn.commit()
        cur.execute("SELECT COUNT(*) FROM us_leads WHERE api_source='PROPUBLICA_990'")
        db_count = cur.fetchone()[0]
        conn.close()
    else:
        db_count = inserted

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"\n\n  {'─'*58}")
    print(f"  ProPublica complete in {elapsed:.0f}s")
    print(f"  Inserted : {inserted:,}")
    print(f"  Errors   : {errors}")
    print(f"  DB total : {db_count:,} ProPublica records in us_leads")
    print(f"  {'─'*58}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state",   default=None, help="Single state code e.g. CA")
    parser.add_argument("--limit",   type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    states = [args.state.upper()] if args.state else None
    run(states=states, limit=args.limit, dry_run=args.dry_run)
