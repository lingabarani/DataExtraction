#!/usr/bin/env python3
"""
DataExtraction — CLI Runner: Promote All Leads to Master MDM
===========================================================
Promotes all enriched B2B decision makers from `public.us_leads` (15,000)
and `public.mexico_leads` (50,208) into `master_dataextraction.organizations`,
`master_dataextraction.persons`, `kg_graph.employment_relationships`, and
`master_dataextraction.contact_emails`.

Usage:
    python scripts/promote_all_leads_to_mdm.py [--limit N] [--jurisdiction US|MX|ALL]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from packages.domain.mdm_lead_promoter import mdm_lead_promoter
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("dataextraction.cli.promote_mdm")


def main():
    parser = argparse.ArgumentParser(description="Promote leads to Master MDM Golden Records")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of leads per table to promote")
    parser.add_argument("--jurisdiction", choices=["US", "MX", "ALL"], default="ALL", help="Jurisdiction to promote")
    args = parser.parse_args()

    print("=" * 70)
    print("  DataExtraction — Master MDM Lead Promotion Pipeline")
    print(f"  Target Jurisdictions: {args.jurisdiction} | Batch Limit: {args.limit or 'ALL'}")
    print("=" * 70)

    results = []

    if args.jurisdiction in ("US", "ALL"):
        print("\n>>> Promoting US Decision-Maker Leads (public.us_leads)...")
        res_us = mdm_lead_promoter.promote_table("us_leads", jurisdiction="US", limit=args.limit)
        results.append(res_us)
        print(f"US Leads Result: {res_us}")

    if args.jurisdiction in ("MX", "ALL"):
        print("\n>>> Promoting Mexico Decision-Maker Leads (public.mexico_leads)...")
        res_mx = mdm_lead_promoter.promote_table("mexico_leads", jurisdiction="MX", limit=args.limit)
        results.append(res_mx)
        print(f"Mexico Leads Result: {res_mx}")

    print("\n" + "=" * 70)
    print("  Promotion Summary:")
    total_persons = sum(r.get("promoted_persons", 0) for r in results)
    total_orgs = sum(r.get("promoted_orgs", 0) for r in results)
    total_employments = sum(r.get("promoted_employments", 0) for r in results)
    total_emails = sum(r.get("promoted_emails", 0) for r in results)
    print(f"  - Total Persons Promoted into master_dataextraction.persons: {total_persons:,}")
    print(f"  - Total Organizations Promoted into master_dataextraction.organizations: {total_orgs:,}")
    print(f"  - Total Employment Graph Edges: {total_employments:,}")
    print(f"  - Total Contact Emails: {total_emails:,}")
    print("=" * 70)


if __name__ == "__main__":
    main()
