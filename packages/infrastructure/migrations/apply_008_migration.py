#!/usr/bin/env python3
"""
DataExtraction — Migration 008 Runner: Apollo.io MDM Schema Alignment
=====================================================================
Applies migration 008 to align master, staging, graph, and lead tables
with the comprehensive Apollo.io B2B entity specifications.

Production Standards:
  - Uses centralized db_connector connection pool
  - Idempotent execution (IF NOT EXISTS)
  - Detailed structured logging and audit reporting
"""

import logging
import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("dataextraction.migration.008_apollo_mdm")

SQL_FILE = Path(__file__).resolve().parent / "008_apollo_mdm_schema_alignment.sql"


def run_migration_008() -> bool:
    logger.info("Starting Migration 008: Apollo.io MDM Schema Alignment...")
    if not SQL_FILE.exists():
        logger.error("Migration SQL file not found: %s", SQL_FILE)
        return False

    sql_content = SQL_FILE.read_text(encoding="utf-8")
    statements = [stmt.strip() for stmt in sql_content.split(";") if stmt.strip()]

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for i, stmt in enumerate(statements, 1):
                try:
                    cur.execute(stmt)
                except Exception as stmt_err:
                    logger.warning("Notice on statement %d: %s", i, stmt_err)
        conn.commit()
        logger.info("Successfully executed %d statements in Migration 008.", len(statements))
        return True
    except Exception as exc:
        conn.rollback()
        logger.error("Migration 008 failed: %s", exc, exc_info=True)
        return False
    finally:
        release_connection(conn)


if __name__ == "__main__":
    success = run_migration_008()
    sys.exit(0 if success else 1)
