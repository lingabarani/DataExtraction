"""
DataExtraction — Apply Migration 022: Recent Data Priority & End-to-End Customer Reviews Integration
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_db_connection


def apply_migration() -> None:
    sql_path = Path(__file__).parent / "022_recent_data_and_reviews_integration.sql"
    sql = sql_path.read_text(encoding="utf-8")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            print("[INFO] Executing Migration 022 SQL (Reviews & Recency Indexing)...")
            cur.execute(sql)
            print("[INFO] Running ANALYZE on updated tables...")
            cur.execute("ANALYZE master_dataextraction.organizations;")
            cur.execute("ANALYZE master_dataextraction.persons;")
            cur.execute("ANALYZE staging_dataextraction._archived_place_reviews;")
        conn.commit()
        print("[SUCCESS] Migration 022 applied cleanly! Reviews, ratings, and recency indexes are now live.")


if __name__ == "__main__":
    apply_migration()
