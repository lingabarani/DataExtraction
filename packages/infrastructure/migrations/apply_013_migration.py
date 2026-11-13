"""
DataExtraction — Apply Migration 013: Agent 2 Geospatial Production Hardening
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_db_connection


def apply_migration() -> None:
    sql_path = Path(__file__).parent / "013_agent2_geospatial_production_hardening.sql"
    sql = sql_path.read_text(encoding="utf-8")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            print("[INFO] Executing Migration 013 SQL...")
            cur.execute(sql)
            cur.execute("ANALYZE staging_dataextraction.staging_companies;")
            cur.execute("ANALYZE master_dataextraction.locations;")
        conn.commit()
        print("[SUCCESS] Migration 013 applied cleanly!")


if __name__ == "__main__":
    apply_migration()
