#!/usr/bin/env python3
"""
US Business Data Source Registry Manager & Validator.

Central registry management tool for all relevant US open/public business data sources.
Validates:
- Required registry schema fields
- Duplicate source IDs & URLs
- Valid controlled vocabularies (source_category, source_type, access_method, status, priority)
- Exports registry to CSV and JSON formats
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SourceRegistry")

# =====================================================================
# CONTROLLED VOCABULARIES
# =====================================================================

ALLOWED_CATEGORIES: Set[str] = {
    "FEDERAL",
    "STATE",
    "COUNTY",
    "CITY",
    "OPEN_MAP",
    "GOVERNMENT",
    "BUSINESS_REGISTRY",
    "LICENSE_REGISTRY",
    "CORPORATE_REGISTRY",
    "PUBLIC_DATASET",
    "OPEN_DIRECTORY",
    "OTHER"
}

ALLOWED_SOURCE_TYPES: Set[str] = {
    "API",
    "CSV",
    "JSON",
    "XML",
    "GEOJSON",
    "EXCEL",
    "ZIP",
    "HTML",
    "PDF",
    "DATABASE",
    "MULTIPLE"
}

ALLOWED_ACCESS_METHODS: Set[str] = {
    "REST_API",
    "DIRECT_DOWNLOAD",
    "WEB_PAGE",
    "WEB_SCRAPING",
    "PLAYWRIGHT",
    "OVERPASS",
    "MULTIPLE"
}

ALLOWED_STATUSES: Set[str] = {
    "DISCOVERED",
    "EVALUATING",
    "READY",
    "WORKING",
    "PARTIAL",
    "BLOCKED",
    "REQUIRES_AUTH",
    "REQUIRES_CAPTCHA",
    "BROKEN",
    "DUPLICATE",
    "NOT_RELEVANT"
}

ALLOWED_PRIORITIES: Set[str] = {
    "P1",
    "P2",
    "P3"
}

# 39 standardized schema fields
REGISTRY_FIELDS: List[str] = [
    "source_id",
    "source_name",
    "publisher",
    "country",
    "state",
    "city",
    "source_category",
    "source_type",
    "source_url",
    "data_url",
    "api_url",
    "access_method",
    "data_format",
    "authentication_required",
    "login_required",
    "captcha_required",
    "robots_restriction",
    "rate_limit",
    "business_data_available",
    "company_data_available",
    "people_data_available",
    "contact_data_available",
    "address_data_available",
    "industry_data_available",
    "license_data_available",
    "registration_data_available",
    "government_data_available",
    "available_fields",
    "record_identifier",
    "update_frequency",
    "historical_data",
    "estimated_data_volume",
    "open_access",
    "terms_url",
    "documentation_url",
    "priority",
    "status",
    "last_checked",
    "notes"
]

REQUIRED_FIELDS: List[str] = [
    "source_id",
    "source_name",
    "publisher",
    "country",
    "source_category",
    "source_type",
    "source_url",
    "access_method",
    "data_format",
    "authentication_required",
    "login_required",
    "captcha_required",
    "open_access",
    "priority",
    "status"
]


class SourceRegistry:
    """
    Manager and validator for US Open Data Source Registry.
    """

    def __init__(
        self,
        json_path: str = "data/export/source_registry.json",
        csv_path: str = "data/export/source_registry.csv"
    ):
        self.json_path = json_path
        self.csv_path = csv_path
        self.sources: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        """Load sources from JSON registry file if it exists."""
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, "r", encoding="utf-8") as f:
                    self.sources = json.load(f)
            except Exception as e:
                logger.error(f"Error reading {self.json_path}: {e}")
                self.sources = []
        else:
            self.sources = []

    def get_all(self) -> List[Dict[str, Any]]:
        """Return all registered sources."""
        return self.sources

    def get_by_id(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific source by its deterministic ID."""
        for src in self.sources:
            if src.get("source_id") == source_id:
                return src
        return None

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate all sources in the registry.
        Checks:
        - Required fields present and non-empty
        - Duplicate source_id
        - Duplicate source_url
        - Controlled vocabularies for status, priority, source_type, access_method, source_category
        """
        errors: List[str] = []
        seen_ids: Set[str] = set()
        seen_urls: Dict[str, str] = {}

        for idx, src in enumerate(self.sources, 1):
            source_id = src.get("source_id")
            source_name = src.get("source_name") or f"Source #{idx}"

            # 1. Required fields
            for rf in REQUIRED_FIELDS:
                val = src.get(rf)
                if val is None or (isinstance(val, str) and not val.strip()):
                    errors.append(f"[{source_id or source_name}] Missing required field: '{rf}'")

            # 2. Duplicate source_id
            if source_id:
                if source_id in seen_ids:
                    errors.append(f"Duplicate source_id detected: '{source_id}'")
                else:
                    seen_ids.add(source_id)

            # 3. Duplicate source_url
            source_url = src.get("source_url")
            if source_url:
                norm_url = source_url.lower().rstrip("/")
                if norm_url in seen_urls:
                    errors.append(
                        f"Duplicate source_url '{source_url}' in '{source_id}' "
                        f"(already registered by '{seen_urls[norm_url]}')"
                    )
                else:
                    seen_urls[norm_url] = source_id or source_name

            # 4. Controlled vocabulary checks
            category = src.get("source_category")
            if category and category not in ALLOWED_CATEGORIES:
                errors.append(
                    f"[{source_id}] Invalid source_category: '{category}'. Allowed: {sorted(ALLOWED_CATEGORIES)}"
                )

            stype = src.get("source_type")
            if stype and stype not in ALLOWED_SOURCE_TYPES:
                errors.append(
                    f"[{source_id}] Invalid source_type: '{stype}'. Allowed: {sorted(ALLOWED_SOURCE_TYPES)}"
                )

            method = src.get("access_method")
            if method and method not in ALLOWED_ACCESS_METHODS:
                errors.append(
                    f"[{source_id}] Invalid access_method: '{method}'. Allowed: {sorted(ALLOWED_ACCESS_METHODS)}"
                )

            status = src.get("status")
            if status and status not in ALLOWED_STATUSES:
                errors.append(
                    f"[{source_id}] Invalid status: '{status}'. Allowed: {sorted(ALLOWED_STATUSES)}"
                )

            priority = src.get("priority")
            if priority and priority not in ALLOWED_PRIORITIES:
                errors.append(
                    f"[{source_id}] Invalid priority: '{priority}'. Allowed: {sorted(ALLOWED_PRIORITIES)}"
                )

        is_valid = len(errors) == 0
        return is_valid, errors

    def save(self):
        """Save sources to both JSON and CSV files."""
        os.makedirs(os.path.dirname(self.json_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.csv_path), exist_ok=True)

        # 1. Save JSON
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(self.sources, f, indent=2)

        # 2. Save CSV
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REGISTRY_FIELDS)
            writer.writeheader()
            for src in self.sources:
                row = {}
                for field in REGISTRY_FIELDS:
                    val = src.get(field)
                    if isinstance(val, bool):
                        row[field] = "true" if val else "false"
                    elif val is None:
                        row[field] = ""
                    else:
                        row[field] = str(val)
                writer.writerow(row)

        logger.info(f"Registry saved to {self.json_path} and {self.csv_path}")

    def summary(self) -> Dict[str, Any]:
        """Generate comprehensive summary statistics for the registry."""
        total = len(self.sources)
        by_priority: Dict[str, int] = {"P1": 0, "P2": 0, "P3": 0}
        by_category: Dict[str, int] = {}
        by_access: Dict[str, int] = {}
        by_source_type: Dict[str, int] = {}
        by_status: Dict[str, int] = {}

        for src in self.sources:
            p = src.get("priority", "UNKNOWN")
            by_priority[p] = by_priority.get(p, 0) + 1

            cat = src.get("source_category", "UNKNOWN")
            by_category[cat] = by_category.get(cat, 0) + 1

            acc = src.get("access_method", "UNKNOWN")
            by_access[acc] = by_access.get(acc, 0) + 1

            st = src.get("source_type", "UNKNOWN")
            by_source_type[st] = by_source_type.get(st, 0) + 1

            stat = src.get("status", "UNKNOWN")
            by_status[stat] = by_status.get(stat, 0) + 1

        return {
            "total_sources": total,
            "by_priority": by_priority,
            "by_category": by_category,
            "by_access": by_access,
            "by_source_type": by_source_type,
            "by_status": by_status
        }


def print_summary(registry: SourceRegistry):
    stats = registry.summary()
    print("\n" + "=" * 65)
    print("           US B2B OPEN DATA SOURCE REGISTRY SUMMARY           ")
    print("=" * 65)
    print(f"Total sources registered : {stats['total_sources']}")
    print("-" * 65)
    print("By Priority:")
    for p in ["P1", "P2", "P3"]:
        cnt = stats['by_priority'].get(p, 0)
        desc = "High value company source" if p == "P1" else ("Supporting source" if p == "P2" else "Enrichment source")
        print(f"  - {p:<3} : {cnt:>2}  ({desc})")

    print("\nBy Category:")
    for cat, cnt in sorted(stats['by_category'].items(), key=lambda x: -x[1]):
        print(f"  - {cat:<20} : {cnt:>2}")

    print("\nBy Access Method:")
    for acc, cnt in sorted(stats['by_access'].items(), key=lambda x: -x[1]):
        print(f"  - {acc:<20} : {cnt:>2}")

    print("\nBy Source Type:")
    for st, cnt in sorted(stats['by_source_type'].items(), key=lambda x: -x[1]):
        print(f"  - {st:<20} : {cnt:>2}")

    print("\nBy Status:")
    for stat, cnt in sorted(stats['by_status'].items(), key=lambda x: -x[1]):
        print(f"  - {stat:<20} : {cnt:>2}")
    print("=" * 65 + "\n")


def print_list(registry: SourceRegistry):
    sources = registry.get_all()
    print("\n" + "=" * 105)
    print(f"{'ID':<28} | {'PRIORITY':<8} | {'STATUS':<10} | {'CATEGORY':<14} | {'METHOD':<15} | {'NAME'}")
    print("-" * 105)
    for src in sources:
        sid = src.get("source_id", "")[:28]
        prio = src.get("priority", "")[:8]
        stat = src.get("status", "")[:10]
        cat = src.get("source_category", "")[:14]
        meth = src.get("access_method", "")[:15]
        name = src.get("source_name", "")[:25]
        print(f"{sid:<28} | {prio:<8} | {stat:<10} | {cat:<14} | {meth:<15} | {name}")
    print("=" * 105)
    print(f"Total: {len(sources)} sources\n")


def print_validation(registry: SourceRegistry):
    is_valid, errors = registry.validate()
    print("\n" + "=" * 65)
    print("               SOURCE REGISTRY VALIDATION               ")
    print("=" * 65)
    if is_valid:
        print(f"Validation Result : PASSED")
        print(f"Total Sources     : {len(registry.get_all())}")
        print(f"Errors Found      : 0")
        print("All required fields, unique IDs, URLs, and controlled vocabularies are valid.")
    else:
        print(f"Validation Result : FAILED")
        print(f"Errors Found      : {len(errors)}")
        for e in errors:
            print(f"  - [ERROR] {e}")
    print("=" * 65 + "\n")
    return is_valid


def main():
    parser = argparse.ArgumentParser(description="US B2B Open Data Source Registry")
    parser.add_argument("--list", action="store_true", help="List all registered sources in a table")
    parser.add_argument("--validate", action="store_true", help="Validate registry records against schema rules")
    parser.add_argument("--summary", action="store_true", help="Display comprehensive registry breakdown summary")
    parser.add_argument("--json-file", type=str, default="data/export/source_registry.json", help="Path to registry JSON")
    parser.add_argument("--csv-file", type=str, default="data/export/source_registry.csv", help="Path to registry CSV")

    args = parser.parse_args()

    # Determine base directory
    workspace_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(workspace_dir, args.json_file) if not os.path.isabs(args.json_file) else args.json_file
    csv_path = os.path.join(workspace_dir, args.csv_file) if not os.path.isabs(args.csv_file) else args.csv_file

    registry = SourceRegistry(json_path=json_path, csv_path=csv_path)

    if not (args.list or args.validate or args.summary):
        # Default behavior if no flag passed: print summary
        print_summary(registry)
        return

    if args.list:
        print_list(registry)

    if args.summary:
        print_summary(registry)

    if args.validate:
        is_valid = print_validation(registry)
        if not is_valid:
            sys.exit(1)


if __name__ == "__main__":
    main()
