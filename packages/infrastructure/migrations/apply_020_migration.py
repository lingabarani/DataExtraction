"""
DataExtraction — Apply Migration 020: B2B AI Chatbot Schema
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.infrastructure.db_connector import get_db_connection


def apply_migration() -> None:
    sql_path = Path(__file__).parent / "020_b2b_chatbot_schema.sql"
    sql = sql_path.read_text(encoding="utf-8")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            print("[INFO] Executing Migration 020 SQL...")
            cur.execute(sql)
            cur.execute("ANALYZE chat_dataextraction.chat_sessions;")
            cur.execute("ANALYZE chat_dataextraction.chat_messages;")
            cur.execute("ANALYZE chat_dataextraction.chat_execution_runs;")
            cur.execute("ANALYZE chat_dataextraction.chat_review_items;")
        conn.commit()
        print("[SUCCESS] Migration 020 applied cleanly!")


if __name__ == "__main__":
    apply_migration()
