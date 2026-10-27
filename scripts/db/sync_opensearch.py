"""
DataExtraction — OpenSearch CDC Synchronization Runner
======================================================
Synchronizes PostgreSQL Knowledge Graph search projections to OpenSearch 2.x.

Usage:
    python scripts/db/sync_opensearch.py
    python scripts/db/sync_opensearch.py --batch-size 2000
    python scripts/db/sync_opensearch.py --check-health
"""

import argparse
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
from packages.infrastructure.opensearch_cdc_sync import opensearch_client

DB_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("POSTGRES_PORT", 5432))
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "7903")
DB_NAME = os.getenv("POSTGRES_DB", "dataextraction")


def main():
    parser = argparse.ArgumentParser(description="OpenSearch CDC Synchronization")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--check-health", action="store_true")
    args = parser.parse_args()

    print(f"\n{'='*70}")
    print(f"DataExtraction — OpenSearch 2.x CDC Synchronizer ({DB_NAME})")
    print(f"{'='*70}")

    is_online = opensearch_client.ping()
    print(f"  Cluster Reachability: {'ONLINE (200 OK)' if is_online else 'OFFLINE / STANDBY'}")
    idx_status = opensearch_client.ensure_indices()
    for idx, stat in idx_status.items():
        print(f"  Index '{idx}': {stat}")

    if args.check_health:
        print("\nHealth check complete.")
        return

    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )
    conn.autocommit = True

    try:
        print(f"\n==> Streaming delta projections (Batch limit: {args.batch_size})...")
        res = opensearch_client.sync_companies_cdc(conn, batch_limit=args.batch_size)
        print(f"  Status:         {res['status']}")
        print(f"  Records Synced: {res['records_synced']}")
        print(f"  Total Synced:   {res['total_synced']}")
        print(f"  Duration:       {res['duration_ms']} ms")
        print(f"\n{'='*70}")
        print("✅ OPENSEARCH CDC SYNCHRONIZATION COMPLETED")
        print(f"{'='*70}\n")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
