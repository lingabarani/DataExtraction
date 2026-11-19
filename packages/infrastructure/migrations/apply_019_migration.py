"""
DataExtraction — Apply Migration 019: Website Intelligence, Review Checkpointing & Taxonomy Schema
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_db_connection


def apply_migration() -> None:
    sql_path = Path(__file__).parent / "019_website_intelligence.sql"
    sql = sql_path.read_text(encoding="utf-8")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            print("[INFO] Executing Migration 019 SQL...")
            cur.execute(sql)
            cur.execute("ANALYZE staging_dataextraction.place_reviews;")
            cur.execute("ANALYZE staging_dataextraction.place_services;")
            cur.execute("ANALYZE staging_dataextraction.place_review_checkpoints;")
            cur.execute("ANALYZE staging_dataextraction.website_verifications;")
            cur.execute("ANALYZE staging_dataextraction.field_cross_verifications;")
            cur.execute("ANALYZE staging_dataextraction.company_tech_stack;")
        conn.commit()
        print("[SUCCESS] Migration 019 applied cleanly!")


if __name__ == "__main__":
    apply_migration()
