#!/usr/bin/env python3
"""
Command-line Runner for US OSM State-Wise Complete Business/POI Collector.

Usage Examples:
  # 1. Run default first test (Alabama only):
  python run_osm_state_collector.py

  # 2. Run specific state(s):
  python run_osm_state_collector.py --states Alabama

  # 3. Run specific field(s) for Alabama:
  python run_osm_state_collector.py --states Alabama --fields shop office

  # 4. Run all 50 US States sequentially:
  python run_osm_state_collector.py --all-50-states

  # 5. Customize chunk grid size (e.g. 0.4 degrees):
  python run_osm_state_collector.py --states Alabama --chunk-size 0.4
"""

import argparse
import sys
import os

from src.osm_state_collector import (
    OSMStateCollector,
    US_STATES,
    ENABLED_STATES,
    FIELDS_TAXONOMY,
    STATE_BOUNDING_BOXES
)

def main():
    parser = argparse.ArgumentParser(
        description="US OSM Complete State-Wise Business/POI Data Collector (Free OpenStreetMap Overpass Only)"
    )
    parser.add_argument(
        "--states",
        nargs="+",
        help="Specific state name(s) or 2-letter code(s) to process. Default: resume the full US collection from the existing checkpoint."
    )
    parser.add_argument(
        "--all-50-states",
        action="store_true",
        help="Process ALL 50 US States sequentially in strict order (Alabama -> Wyoming)"
    )
    parser.add_argument(
        "--fields",
        nargs="+",
        choices=[f["field"] for f in FIELDS_TAXONOMY],
        help="Specific taxonomy fields to collect (default: all 13 fields)"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Disable resume; run from scratch ignoring previous progress checkpoint"
    )
    parser.add_argument(
        "--chunk-size",
        type=float,
        default=0.5,
        help="Geographic bounding-box grid step in degrees (default: 0.5)"
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="Custom Overpass API endpoint URL (overrides default https://overpass-api.de/api/interpreter)"
    )
    parser.add_argument(
        "--retry-affected",
        action="store_true",
        help="Specifically identify and retry chunks previously marked complete after empty responses from the incorrect endpoint"
    )

    args = parser.parse_args()

    # Determine state selection
    state_map_by_name = {name.lower(): (name, code) for name, code in US_STATES}
    state_map_by_code = {code.lower(): (name, code) for name, code in US_STATES}

    target_states = []
    if args.all_50_states:
        target_states = list(US_STATES)
    elif args.states:
        for s_arg in args.states:
            s_key = s_arg.strip().lower()
            if s_key in state_map_by_name:
                target_states.append(state_map_by_name[s_key])
            elif s_key in state_map_by_code:
                target_states.append(state_map_by_code[s_key])
            else:
                print(f"Error: Unrecognized US state '{s_arg}'. Valid states: {', '.join(s[0] for s in US_STATES)}")
                sys.exit(1)
    else:
        # Normal command: resume the full US collection from the progress checkpoint.
        target_states = list(US_STATES)

    collector = OSMStateCollector(
        chunk_size_deg=args.chunk_size,
        endpoint_url=args.endpoint
    )

    collector.run_collection_pipeline(
        states=target_states,
        target_fields=args.fields,
        resume=not args.no_resume,
        retry_affected=args.retry_affected
    )


if __name__ == "__main__":
    main()
