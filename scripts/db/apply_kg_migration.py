"""
DataExtraction — Apply Knowledge Graph Migration 001
=====================================================
Applies `001_knowledge_graph_schema.sql` to PostgreSQL 16/18.
Sets up schemas, enums, declarative partitions, indexes, and tables.
"""

import hashlib
import time
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")
MIGRATIONS_DIR = REPO_ROOT / "packages" / "infrastructure" / "migrations"

DB_HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("POSTGRES_PORT", 5432))
DB_USER = os.getenv("POSTGRES_USER", "dex_user")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
DB_NAME = os.getenv("POSTGRES_DB", "dataextraction")

if not DB_PASSWORD:
    print("[ERROR] POSTGRES_PASSWORD environment variable is not set. Set it in .env or export it.")
    sys.exit(1)


def ensure_database():
    # Test if DB_NAME is already reachable directly
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname=DB_NAME,
            connect_timeout=5,
        )
        conn.close()
        print(f"✅ Database '{DB_NAME}' already exists and is reachable.")
        return
    except psycopg2.OperationalError:
        pass

    print(f"==> Connecting to PostgreSQL cluster at {DB_HOST}:{DB_PORT} as {DB_USER}...")
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            dbname="postgres",
            connect_timeout=10,
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
    except Exception as e:
        print(f"⚠️ ensure_database note: {e}")


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

    # Ensure ops_dataextraction schema and schema_migrations tracking table exist
    cur.execute("CREATE SCHEMA IF NOT EXISTS ops_dataextraction;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ops_dataextraction.schema_migrations (
            migration_name VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            checksum VARCHAR(64) NOT NULL,
            execution_time_ms INTEGER NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'SUCCESS'
        );
    """)

    # Query currently applied migrations
    cur.execute("SELECT migration_name, checksum FROM ops_dataextraction.schema_migrations WHERE status = 'SUCCESS';")
    applied_migrations = dict(cur.fetchall())

    # If this is an existing database being upgraded to schema version tracking,
    # auto-baseline migrations that are already present in the database.
    if not applied_migrations:
        cur.execute("""
            SELECT count(*) FROM information_schema.tables 
            WHERE table_schema = 'master_dataextraction' AND table_name = 'organizations';
        """)
        has_existing_schema = cur.fetchone()[0] > 0
        if has_existing_schema:
            print("==> Existing schema detected. Baselining existing migrations in ops_dataextraction.schema_migrations...")
            for m_file in migration_files:
                sql_script = m_file.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql_script.encode("utf-8")).hexdigest()
                cur.execute("""
                    INSERT INTO ops_dataextraction.schema_migrations (migration_name, checksum, execution_time_ms, status)
                    VALUES (%s, %s, 0, 'SUCCESS')
                    ON CONFLICT (migration_name) DO NOTHING;
                """, (m_file.name, checksum))
                print(f"  📌 [BASELINED] {m_file.name} (checksum: {checksum[:8]}...)")
            cur.execute("SELECT migration_name, checksum FROM ops_dataextraction.schema_migrations WHERE status = 'SUCCESS';")
            applied_migrations = dict(cur.fetchall())
            print(f"✅ Successfully baselined {len(applied_migrations)} migrations.")

    conn.autocommit = False  # Enforce transactional execution for each migration file

    applied_count = 0
    skipped_count = 0

    for m_file in migration_files:
        sql_script = m_file.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql_script.encode("utf-8")).hexdigest()

        if m_file.name in applied_migrations:
            print(f"  ⏭️ [SKIPPED] {m_file.name} (already applied with checksum {checksum[:8]}...)")
            skipped_count += 1
            continue

        print(f"\n==> Applying migration: {m_file.name} ({m_file.stat().st_size} bytes)")
        start_time = time.monotonic()
        try:
            cur.execute(sql_script)
            exec_time_ms = int((time.monotonic() - start_time) * 1000)
            cur.execute("""
                INSERT INTO ops_dataextraction.schema_migrations (migration_name, checksum, execution_time_ms, status)
                VALUES (%s, %s, %s, 'SUCCESS')
                ON CONFLICT (migration_name) DO UPDATE
                SET applied_at = clock_timestamp(), checksum = EXCLUDED.checksum, execution_time_ms = EXCLUDED.execution_time_ms, status = 'SUCCESS';
            """, (m_file.name, checksum, exec_time_ms))
            conn.commit()
            applied_count += 1
            print(f"✅ {m_file.name} executed and recorded in {exec_time_ms}ms.")
        except Exception as e:
            conn.rollback()
            print(f"❌ Failed to execute {m_file.name}: {e}")
            cur.close()
            conn.close()
            sys.exit(1)

    print(f"\nMigration Run Complete: {applied_count} applied, {skipped_count} skipped.")
    conn.autocommit = True

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
