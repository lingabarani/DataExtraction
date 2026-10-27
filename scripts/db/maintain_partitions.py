"""
DataExtraction — Partition Maintenance Runner
==============================================
Runs automated partition pre-allocation and inspects physical partition catalog.

Usage:
    python scripts/db/maintain_partitions.py
"""

import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES_DIR = REPO_ROOT / "packages"
sys.path.insert(0, str(PACKAGES_DIR))
sys.path.insert(0, str(REPO_ROOT))

import psycopg2
from packages.infrastructure.partition_manager import partition_manager

DB_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("POSTGRES_PORT", 5432))
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "7903")
DB_NAME = os.getenv("POSTGRES_DB", "dataextraction")


def main():
    print(f"\n{'='*70}")
    print(f"DataExtraction — Partition Lifecycle Maintenance ({DB_NAME})")
    print(f"{'='*70}")

    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )
    conn.autocommit = True

    try:
        report = partition_manager.run_all(conn)
        print(f"✅ Observation partitions verified: {report['observation_partitions_verified']}")
        print(f"✅ Employment partitions verified:  {report['employment_partitions_verified']}")
        print(f"✅ Total physical partitions:       {report['total_partitions_in_cluster']}\n")

        print("Active Physical Partition Catalog (Sample):")
        print(f"  {'Parent Table':<35} | {'Partition Name':<30} | {'Size':<10}")
        print(f"  {'-'*35}-+-{'-'*30}-+-{'-'*10}")
        for p in report["catalog"][:15]:
            print(f"  {p['parent']:<35} | {p['partition']:<30} | {p['total_size']:<10}")
        if len(report["catalog"]) > 15:
            print(f"  ... and {len(report['catalog']) - 15} more partitions.")

        print(f"\n{'='*70}")
        print("✅ PARTITION MAINTENANCE COMPLETED SUCCESSFULLY")
        print(f"{'='*70}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

