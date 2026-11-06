"""
DataExtraction — Apply Migration 009: MDM Data Flow De-Fragmentation
"""

import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_connection, release_connection

def apply_migration():
    sql_path = Path(__file__).parent / "009_mdm_defragmentation_views.sql"
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = get_connection()
    if not conn:
        print("[ERROR] Could not connect to PostgreSQL")
        sys.exit(1)

    try:
        with conn.cursor() as cur:
            print("[INFO] Executing Migration 009 SQL...")
            cur.execute(sql)
        conn.commit()
        print("[SUCCESS] Migration 009 applied cleanly!")

        # Verify views
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM public.companies;")
            comp_count = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM public.us_leads;")
            leads_count = cur.fetchone()[0]
            print(f"[VERIFY] public.companies live view count: {comp_count:,}")
            print(f"[VERIFY] public.us_leads live view count: {leads_count:,}")
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] Migration 009 failed: {e}")
        sys.exit(1)
    finally:
        release_connection(conn)

if __name__ == "__main__":
    apply_migration()

