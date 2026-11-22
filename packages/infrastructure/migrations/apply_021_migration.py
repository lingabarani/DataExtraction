"""
DataExtraction — Apply Migration 021: Enterprise B2B Intelligence Extensions
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_db_connection


def apply_migration() -> None:
    sql_path = Path(__file__).parent / "021_b2b_intelligence_extensions.sql"
    sql = sql_path.read_text(encoding="utf-8")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            print("[INFO] Executing Migration 021 SQL (In-place table alterations)...")
            cur.execute(sql)
            print("[INFO] Running ANALYZE on updated tables...")
            cur.execute("ANALYZE master_dataextraction.organizations;")
            cur.execute("ANALYZE master_dataextraction.persons;")
            cur.execute("ANALYZE search_dataextraction.company_search_projection;")
            cur.execute("ANALYZE public.mexico_leads;")
        conn.commit()
        print("[SUCCESS] Migration 021 applied cleanly! All B2B intelligence fields are now live.")


if __name__ == "__main__":
    apply_migration()
