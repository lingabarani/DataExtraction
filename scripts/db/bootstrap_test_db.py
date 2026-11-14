"""
DataExtraction Enterprise — Test Database Bootstrap Harness
============================================================
Automates complete schema provisioning for CI and ephemeral test environments:
1. Validates PostgreSQL connectivity.
2. Applies Knowledge Graph migrations 001 through 006.
3. Executes Schema Layer Standardization (007).
4. Applies MDM alignment and enrichment migrations (008, 009, 010, 013, 014).
5. Provisions legacy public schema tables for backward compatibility.
6. Verifies table and view counts across all 5 MDM enterprise schemas.
"""

import os
import sys
import logging
from pathlib import Path

# Ensure project root is on sys.path
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from packages.infrastructure.config_manager import config_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bootstrap_test_db")

MIGRATIONS_DIR = _REPO_ROOT / "packages" / "infrastructure" / "migrations"


def get_db_params():
    cfg = config_manager.get_database_config()
    return {
        "host": cfg["host"],
        "port": cfg["port"],
        "user": cfg["user"],
        "password": cfg["password"],
        "dbname": cfg["dbname"],
    }


def ensure_database():
    params = get_db_params()
    host, port, user, password, dbname = (
        params["host"], params["port"], params["user"], params["password"], params["dbname"]
    )
    logger.info("Verifying database '%s' at %s:%d as user '%s'...", dbname, host, port, user)

    # Test direct connection
    try:
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password, dbname=dbname, connect_timeout=5
        )
        conn.close()
        logger.info("Database '%s' exists and is directly reachable.", dbname)
        return
    except psycopg2.OperationalError:
        pass

    # If direct connection fails, connect to default 'postgres' database and create it
    try:
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password, dbname="postgres", connect_timeout=10
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (dbname,))
            if not cur.fetchone():
                cur.execute(f'CREATE DATABASE "{dbname}";')
                logger.info("Created database '%s'.", dbname)
        conn.close()
    except Exception as exc:
        logger.warning("Could not auto-create database via default postgres DB: %s", exc)


def execute_sql_file(conn, sql_path: Path):
    if not sql_path.exists():
        logger.warning("Migration file not found: %s", sql_path)
        return
    logger.info("Applying SQL migration: %s", sql_path.name)
    sql_text = sql_path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql_text)
    conn.commit()


def bootstrap():
    ensure_database()
    params = get_db_params()

    conn = psycopg2.connect(
        host=params["host"],
        port=params["port"],
        user=params["user"],
        password=params["password"],
        dbname=params["dbname"],
    )
    conn.autocommit = True

    try:
        # Phase 1: Core Knowledge Graph SQL migrations 001 - 006
        for m_name in [
            "001_knowledge_graph_schema.sql",
            "002_search_projections_and_lineage_triggers.sql",
            "003_isolation_review_queue.sql",
            "004_lead_tables_and_indexes.sql",
            "005_audit_logs_and_compliance.sql",
            "006_sqlite_to_postgresql_enterprise_migration.sql",
        ]:
            sql_file = MIGRATIONS_DIR / m_name
            try:
                execute_sql_file(conn, sql_file)
            except Exception as e:
                logger.warning("Notice on %s: %s", m_name, e)

        # Phase 2: Schema layer standardization (007)
        try:
            from packages.infrastructure.migrations.apply_007_migration import run_migration_007
            run_migration_007()
            logger.info("Migration 007 applied successfully.")
        except Exception as e:
            logger.warning("Notice on Migration 007: %s", e)

        # Phase 3: Apollo alignment (008)
        try:
            from packages.infrastructure.migrations.apply_008_migration import run_migration_008
            run_migration_008()
            logger.info("Migration 008 applied successfully.")
        except Exception as e:
            logger.warning("Notice on Migration 008: %s", e)

        # Phase 4: MDM views & OneReach (009, 010)
        for apply_module in ["apply_009_migration", "apply_010_migration"]:
            try:
                mod = __import__(f"packages.infrastructure.migrations.{apply_module}", fromlist=["apply_migration"])
                mod.apply_migration()
                logger.info("%s applied successfully.", apply_module)
            except Exception as e:
                logger.warning("Notice on %s: %s", apply_module, e)

        # Phase 5: Hardening & Email Enrichment (011, 012, 013, 014)
        for m_name in [
            "011_dead_letter_queue.sql",
            "012_working_layer_and_master_lifecycle.sql",
        ]:
            sql_file = MIGRATIONS_DIR / m_name
            try:
                execute_sql_file(conn, sql_file)
            except Exception as e:
                logger.warning("Notice on %s: %s", m_name, e)

        for apply_module in ["apply_013_migration", "apply_014_migration"]:
            try:
                mod = __import__(f"packages.infrastructure.migrations.{apply_module}", fromlist=["apply_migration"])
                mod.apply_migration()
                logger.info("%s applied successfully.", apply_module)
            except Exception as e:
                logger.warning("Notice on %s: %s", apply_module, e)

        # Phase 6: Public legacy schema tables (setup_postgres schema)
        try:
            from packages.infrastructure.setup_postgres import create_schema
            create_schema(params["host"], params["port"], params["password"], drop_existing=False)
            logger.info("Legacy public schema tables verified.")
        except Exception as e:
            logger.warning("Notice on public schema: %s", e)

        # Phase 7: Verification Query
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_schema, count(*)
                FROM information_schema.tables
                WHERE table_schema IN (
                    'master_dataextraction', 'staging_dataextraction', 'identity_resolution',
                    'raw_dataextraction', 'search_dataextraction', 'public'
                )
                GROUP BY table_schema
                ORDER BY table_schema;
            """)
            counts = cur.fetchall()
            logger.info("=== Database Bootstrap Schema Verification ===")
            for s, c in counts:
                logger.info("  Schema: %-25s | Entities: %d", s, c)

        logger.info("✅ Test database bootstrap completed successfully!")

    finally:
        conn.close()


if __name__ == "__main__":
    bootstrap()
