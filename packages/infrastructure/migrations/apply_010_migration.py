"""
DataExtraction — Apply Migration 010: OneReach Delivery Log Schema
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_connection, release_connection

def apply_migration():
    sql_path = Path(__file__).parent / "010_onereach_delivery_log.sql"
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = get_connection()
    if not conn:
        print("[ERROR] Could not connect to PostgreSQL")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            print("[INFO] Executing Migration 010 SQL...")
            cur.execute(sql)
        conn.commit()
        print("[SUCCESS] Migration 010 applied cleanly!")

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM master_dataextraction.onereach_delivery_log;")
            print(f"[VERIFY] onereach_delivery_log table ready (current records: {cur.fetchone()[0]})")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Migration 010 failed: {e}")
        sys.exit(1)
    finally:
        release_connection(conn)

if __name__ == "__main__":
    apply_migration()

