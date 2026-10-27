"""
DataExtraction — Apply Knowledge Graph Migration 001
=====================================================
Applies `001_knowledge_graph_schema.sql` to PostgreSQL 16/18.
Sets up schemas, enums, declarative partitions, indexes, and tables.
"""

import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SQL_PATH = REPO_ROOT / "packages" / "infrastructure" / "migrations" / "001_knowledge_graph_schema.sql"

DB_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("POSTGRES_PORT", 5432))
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "7903")
DB_NAME = os.getenv("POSTGRES_DB", "dataextraction")


def ensure_database():
    print(f"==> Connecting to PostgreSQL cluster at {DB_HOST}:{DB_PORT} as {DB_USER}...")
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s;", (DB_NAME,))
    exists = cur.fetchone()
    if not exists:
        print(f"==> Database '{DB_NAME}' does not exist. Creating...")
        cur.execute(f'CREATE DATABASE "{DB_NAME}";')
        print(f"✅ Database '{DB_NAME}' created successfully.")
    else:
        print(f"✅ Database '{DB_NAME}' already exists.")

    cur.close()
    conn.close()


def apply_migration():
    if not MIGRATION_SQL_PATH.exists():
        print(f"❌ Migration file not found: {MIGRATION_SQL_PATH}")
        sys.exit(1)

    print(f"==> Reading migration: {MIGRATION_SQL_PATH.name} ({MIGRATION_SQL_PATH.stat().st_size} bytes)")
    sql_script = MIGRATION_SQL_PATH.read_text(encoding="utf-8")

    print(f"==> Connecting to database '{DB_NAME}'...")
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )
    conn.autocommit = True
    cur = conn.cursor()

    print("==> Executing Knowledge Graph DDL statements...")
    cur.execute(sql_script)
    print("✅ Migration 001 executed successfully.")

    # Verification Query
    print("\n" + "=" * 70)
    print("KNOWLEDGE GRAPH SCHEMA VERIFICATION")
    print("=" * 70)

    cur.execute("""
        SELECT table_schema, count(*) as table_count
        FROM information_schema.tables
        WHERE table_schema LIKE 'kg_%'
        GROUP BY table_schema
        ORDER BY table_schema;
    """)
    schemas = cur.fetchall()

    for schema_name, count in schemas:
        print(f"  📁 Schema: {schema_name:<20} | Tables / Partitions: {count:>3}")

    print("\nKey Knowledge Graph Tables Cataloged:")
    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('kg_core', 'kg_graph', 'kg_observation', 'kg_resolution', 'kg_lineage', 'kg_search', 'kg_audit')
          AND table_name NOT LIKE '%_p[0-9]%'  -- Exclude raw hash shard names for brevity
        ORDER BY table_schema, table_name;
    """)
    tables = cur.fetchall()
    for s, t in tables:
        print(f"  • {s}.{t}")

    cur.close()
    conn.close()
    print("\n✅ PHASE 1 COMPLETE — Knowledge Graph database schema is fully operational!")


if __name__ == "__main__":
    ensure_database()
    apply_migration()
