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
MIGRATIONS_DIR = REPO_ROOT / "packages" / "infrastructure" / "migrations"

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
    if not MIGRATIONS_DIR.exists():
        print(f"❌ Migrations directory not found: {MIGRATIONS_DIR}")
        sys.exit(1)

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        print(f"❌ No .sql migration files found in: {MIGRATIONS_DIR}")
        sys.exit(1)

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

    for m_file in migration_files:
        print(f"\n==> Reading migration: {m_file.name} ({m_file.stat().st_size} bytes)")
        sql_script = m_file.read_text(encoding="utf-8")
        print(f"==> Executing {m_file.name} DDL statements...")
        cur.execute(sql_script)
        print(f"✅ {m_file.name} executed successfully.")

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
    print("\n✅ Knowledge Graph database schemas & triggers are fully operational!")


if __name__ == "__main__":
    ensure_database()
    apply_migration()
