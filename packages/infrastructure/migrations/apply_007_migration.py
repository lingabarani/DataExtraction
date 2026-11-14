#!/usr/bin/env python3
"""
DataExtraction - Migration 007 Runner
=====================================
Executes the schema layer standardization to:
  1. raw_dataextraction
  2. staging_dataextraction
  3. identity_resolution
  4. master_dataextraction
  5. search_dataextraction

Implements:
  - Zero-copy table relocation (ALTER TABLE ... SET SCHEMA)
  - Backward-compatibility view bridge in legacy schemas
  - Database search_path optimization
"""

import logging
import sys
from pathlib import Path
import psycopg2

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from packages.infrastructure.db_connector import DB_HOST, DB_PORT, DB_USER, DB_PASS, DB_NAME

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration_007")

SCHEMA_MAPPINGS = [
    ("raw", "raw_dataextraction"),
    ("staging", "staging_dataextraction"),
    ("kg_resolution", "identity_resolution"),
    ("resolution", "identity_resolution"),
    ("kg_core", "master_dataextraction"),
    ("master", "master_dataextraction"),
    ("kg_search", "search_dataextraction"),
    ("search", "search_dataextraction"),
]


def run_migration_007():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        dbname=DB_NAME,
    )
    conn.autocommit = True
    cur = conn.cursor()

    try:
        logger.info("Step 1: Creating target schemas...")
        target_schemas = [
            "raw_dataextraction",
            "staging_dataextraction",
            "identity_resolution",
            "master_dataextraction",
            "search_dataextraction",
        ]
        for s in target_schemas:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {s};")
            cur.execute(f"GRANT USAGE, CREATE ON SCHEMA {s} TO PUBLIC;")
        logger.info("Target schemas created successfully.")

        logger.info("Step 2: Relocating tables to target schemas...")
        relocated_count = 0
        views_created = 0

        for old_schema, new_schema in SCHEMA_MAPPINGS:
            # Query base tables in old_schema
            cur.execute(
                """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                ORDER BY table_name;
                """,
                (old_schema,),
            )
            tables = [r[0] for r in cur.fetchall()]

            for t in tables:
                # Check if table already exists in target
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_schema = %s AND table_name = %s;
                    """,
                    (new_schema, t),
                )
                already_in_target = cur.fetchone() is not None

                if not already_in_target:
                    logger.info("Relocating %s.%s -> %s.%s", old_schema, t, new_schema, t)
                    try:
                        cur.execute(f'ALTER TABLE "{old_schema}"."{t}" SET SCHEMA "{new_schema}";')
                        relocated_count += 1
                    except Exception as e:
                        logger.warning("Could not relocate %s.%s: %s", old_schema, t, e)

                # Create backward-compatibility view in old_schema
                try:
                    cur.execute(f'CREATE OR REPLACE VIEW "{old_schema}"."{t}" AS SELECT * FROM "{new_schema}"."{t}";')
                    views_created += 1
                except Exception as v_err:
                    logger.debug("View bridge note on %s.%s: %s", old_schema, t, v_err)

        logger.info("Step 3: Setting database default search_path...")
        cur.execute(
            f"""
            ALTER DATABASE "{DB_NAME}" SET search_path TO 
                staging_dataextraction, 
                master_dataextraction, 
                identity_resolution, 
                raw_dataextraction, 
                search_dataextraction, 
                public;
            """
        )

        logger.info(
            "Migration 007 Completed! %d tables relocated, %d compatibility views created.",
            relocated_count,
            views_created,
        )

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run_migration_007()

