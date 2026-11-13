"""
DataExtraction — Apply Migration 014: Agent 7 Email Enrichment Pipeline
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_db_connection


def apply_migration() -> None:
    sql_path = Path(__file__).parent / "014_email_enrichment_pipeline.sql"
    sql = sql_path.read_text(encoding="utf-8")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            print("[INFO] Executing Migration 014 SQL...")
            cur.execute(sql)
            cur.execute("ANALYZE staging_dataextraction.working_organizations;")
            cur.execute("ANALYZE staging_dataextraction.working_emails;")
        conn.commit()
        print("[SUCCESS] Migration 014 applied cleanly!")


if __name__ == "__main__":
    apply_migration()
