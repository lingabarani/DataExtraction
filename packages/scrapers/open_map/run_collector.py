#!/usr/bin/env python3
"""
US Business Data Collection Runner.
Collects US company data ONLY from publicly accessible open/free sources and APIs.
Strictly adheres to:
- No paid data providers
- No restricted/login-protected scraping
- Source provenance preservation
- Standardized company JSON format
- Deduplication & entity fingerprinting
- Transparent 0-100 data quality scoring
"""

import argparse
import json
import os
import sys

from src.pipeline import CollectionPipeline

def main():
    parser = argparse.ArgumentParser(description="US Business Data Collector (Open/Free Sources Only)")
    parser.add_argument("--name", type=str, help="Company name to search (e.g. 'Apple', 'Boeing', 'Microsoft')")
    parser.add_argument("--industry", type=str, help="Industry or category (e.g. 'Software', 'Manufacturing', 'Retail')")
    parser.add_argument("--state", type=str, help="State name or 2-letter code (e.g. 'CA', 'California', 'TX')")
    parser.add_argument("--city", type=str, help="City name (e.g. 'San Francisco', 'Chicago', 'Los Angeles')")
    parser.add_argument("--zip", type=str, dest="zip_code", help="5-digit US ZIP code")
    parser.add_argument("--naics", type=str, dest="naics_code", help="NAICS code prefix")
    parser.add_argument("--sic", type=str, dest="sic_code", help="SIC code")
    parser.add_argument("--limit", type=int, default=10, help="Target number of companies to collect (default: 10)")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=["sec_edgar", "osm", "open_data_portals", "usaspending"],
        help="Specific open sources to query (default: all available)"
    )

    args = parser.parse_args()

    # Workspace directory
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    pipeline = CollectionPipeline(output_base_dir=workspace_dir)

    print("\n" + "=" * 60)
    print("      US BUSINESS DATA COLLECTION AGENT (STEP 1: OPEN DATA)      ")
    print("=" * 60)

    summary = pipeline.run_collection(
        company_name=args.name,
        industry=args.industry,
        state=args.state,
        city=args.city,
        zip_code=args.zip_code,
        naics_code=args.naics_code,
        sic_code=args.sic_code,
        limit=args.limit,
        sources=args.sources
    )

    print("\n" + "=" * 60)
    print("                     COLLECTION SUMMARY                     ")
    print("=" * 60)
    print(f"1. Number of records collected           : {summary['number_of_records_collected']}")
    print(f"2. Raw records fetched                   : {summary['raw_records_fetched']}")
    print(f"3. Sources used                          :")
    for src in summary['sources_used']:
        print(f"   - {src['source_name']} ({src['source_type']}) -> {src['count']} records [{src['method']}]")
    print(f"4. Collection method                     : {summary['collection_method']}")
    print(f"5. Fields available                      : {', '.join(summary['fields_available'])}")
    print(f"6. Fields missing                        : {', '.join(summary['fields_missing'])}")
    print(f"7. Number of duplicates merged           : {summary['number_of_duplicates']}")
    print(f"8. Records successfully normalized       : {summary['number_of_records_successfully_normalized']}")
    print(f"9. Failed records                        : {summary['number_of_failed_records']}")
    if summary['error_details']:
        print(f"10. Error details                         : {summary['error_details']}")
    else:
        print(f"10. Error details                         : None")
    print("\nOutput File Locations:")
    print(f"  - Raw Data          : {summary['output_file_locations']['raw_data']}")
    print(f"  - Standardized JSON : {summary['output_file_locations']['standardized_json']}")
    print(f"  - CSV Export        : {summary['output_file_locations']['csv']}")
    print(f"  - Collection Log    : {summary['output_file_locations']['logs']}")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    main()
