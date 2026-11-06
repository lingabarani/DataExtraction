"""
DataExtraction — Migration 004: Email Enrichment Schema Migration
================================================================
Applies the database schema for FORGE email enrichment, results, and audit telemetry.
Safe to run multiple times (idempotent).
"""

import logging
import sys
from pathlib import Path

# Setup path
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from packages.infrastructure.db_connector import execute_query, get_db_connection
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("migration.004_email_enrichment")

SQL_FILE = Path(__file__).resolve().parent / "004_create_email_enrichment_schema.sql"


def run_migration() -> bool:
    """Executes the email enrichment DDL migration script."""
    logger.info("Starting Migration 004: Email Enrichment Schema...")
    if not SQL_FILE.exists():
        logger.error("Migration SQL file not found: %s", SQL_FILE)
        return False

    sql_content = SQL_FILE.read_text(encoding="utf-8")
    
    # Split queries by semicolon while respecting block formatting
    statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
            conn.commit()
        logger.info("Successfully applied Migration 004: %d DDL statements executed.", len(statements))
        return True
    except Exception as exc:
        logger.error("Migration 004 failed with error: %s", exc, exc_info=True)
        return False


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)

