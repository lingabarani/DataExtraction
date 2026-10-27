"""
OpenStreetMap / Overpass Open Map Extraction Connector.
Bridges Open Map Extraction Engine into OneExtraction's canonical US B2B database pipeline.
Exposes OpenMapConnector from openmap_engine package.
"""

import sys
from pathlib import Path

_BOTASAURUS_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_BOTASAURUS_DIR) not in sys.path:
    sys.path.insert(0, str(_BOTASAURUS_DIR))

from openmap_engine.connector import OpenMapConnector

__all__ = ["OpenMapConnector"]


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description="OneExtraction Open Map Ingestion Tool")
    parser.add_argument("--file", help="Path to exported JSON or CSV file")
    parser.add_argument("--state", help="State name (e.g. Alabama)")
    parser.add_argument("--field", help="Field name (e.g. healthcare)")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing to database")
    args = parser.parse_args()

    connector = OpenMapConnector()
    if args.file:
        recs = connector.load_exported_file(args.file)
    elif args.state and args.field:
        recs = connector.load_state_field_export(args.state, args.field)
    else:
        print("Please specify either --file or --state and --field")
        sys.exit(1)

    print(f"Loaded {len(recs)} records. Ingesting...")
    res = connector.ingest_records(recs, dry_run=args.dry_run)
    print(f"Results: {json.dumps(res, indent=2)}")
