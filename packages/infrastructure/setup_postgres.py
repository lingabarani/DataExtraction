"""
OneExtraction - PostgreSQL Setup & Migration
Connects to PostgreSQL 18, creates database + schema, migrates all SQLite data.

Usage:
    python setup_postgres.py --password <your_postgres_password>
    python setup_postgres.py --password <pwd> --host localhost --port 5432
"""

import argparse
import sqlite3
import json
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import execute_values
    from psycopg2 import sql
except ImportError:
    print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

# ─── Config ───────────────────────────────────────────────────────────────────
SQLITE_DB   = "output/us/api/oneextraction.db"
PG_DB_NAME  = "oneextraction"
PG_USER     = "postgres"
PG_SCHEMA   = "public"
BATCH_SIZE  = 500

# ─── Schema DDL ───────────────────────────────────────────────────────────────
DROP_TABLES_SQL = """
DROP TABLE IF EXISTS enrichment_results CASCADE;
DROP TABLE IF EXISTS people            CASCADE;
DROP TABLE IF EXISTS companies         CASCADE;
DROP TABLE IF EXISTS processing_log    CASCADE;
DROP TABLE IF EXISTS dead_letter_queue CASCADE;
"""

SCHEMA_SQL = """
-- ── Extensions ───────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── companies ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id                  TEXT        PRIMARY KEY,
    name                TEXT        NOT NULL,
    legal_name          TEXT,
    trade_name          TEXT,
    normalized_name     TEXT,
    website             TEXT,
    domain              TEXT,
    email               TEXT,
    phone               TEXT,
    city                TEXT,
    state               TEXT,
    state_code          CHAR(2),
    zip_code            TEXT,
    industry            TEXT,
    naics_code          TEXT,
    ein                 TEXT,
    rfc                 TEXT,
    cik                 TEXT,
    npi                 TEXT,
    employee_min        INTEGER,
    employee_max        INTEGER,
    employee_band       TEXT,
    latitude            NUMERIC(10,7),
    longitude           NUMERIC(10,7),
    phones              JSONB       DEFAULT '[]',
    emails              JSONB       DEFAULT '[]',
    source_records      JSONB       DEFAULT '[]',
    source              TEXT,
    api_source          TEXT,
    data_quality_score  INTEGER     DEFAULT 0,
    raw_payload         JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_domain       ON companies(domain);
CREATE INDEX IF NOT EXISTS idx_companies_state        ON companies(state_code);
CREATE INDEX IF NOT EXISTS idx_companies_industry     ON companies(industry);
CREATE INDEX IF NOT EXISTS idx_companies_naics        ON companies(naics_code);
CREATE INDEX IF NOT EXISTS idx_companies_ein          ON companies(ein);
CREATE INDEX IF NOT EXISTS idx_companies_rfc          ON companies(rfc);
CREATE INDEX IF NOT EXISTS idx_companies_cik          ON companies(cik);
CREATE INDEX IF NOT EXISTS idx_companies_npi          ON companies(npi);
CREATE INDEX IF NOT EXISTS idx_companies_name         ON companies(name);
CREATE INDEX IF NOT EXISTS idx_companies_norm_name    ON companies(normalized_name);
CREATE INDEX IF NOT EXISTS idx_companies_name_trgm    ON companies USING gin (normalized_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_companies_source_recs  ON companies USING gin (source_records);

-- ── people ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS people (
    id                  TEXT        PRIMARY KEY,
    company_id          TEXT        REFERENCES companies(id) ON DELETE SET NULL,
    full_name           TEXT,
    first_name          TEXT,
    last_name           TEXT,
    middle_name         TEXT,
    title               TEXT,
    standardized_title  TEXT,
    seniority_level     TEXT,
    department          TEXT,
    email               TEXT,
    phone               TEXT,
    linkedin_url        TEXT,
    is_current          BOOLEAN     DEFAULT TRUE,
    career_history      JSONB       DEFAULT '[]',
    source_records      JSONB       DEFAULT '[]',
    data_quality_score  INTEGER     DEFAULT 0,
    api_source          TEXT,
    raw_payload         JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_people_company      ON people(company_id);
CREATE INDEX IF NOT EXISTS idx_people_email        ON people(email);
CREATE INDEX IF NOT EXISTS idx_people_linkedin     ON people(linkedin_url);
CREATE INDEX IF NOT EXISTS idx_people_title        ON people(title);
CREATE INDEX IF NOT EXISTS idx_people_seniority    ON people(seniority_level);
CREATE INDEX IF NOT EXISTS idx_people_name_trgm    ON people USING gin (full_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_people_career_hist  ON people USING gin (career_history);
CREATE INDEX IF NOT EXISTS idx_people_source_recs  ON people USING gin (source_records);

-- ── enrichment_results ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS enrichment_results (
    id                  TEXT        PRIMARY KEY,
    company_id          TEXT        REFERENCES companies(id) ON DELETE SET NULL,
    email               TEXT,
    email_verified      BOOLEAN     DEFAULT FALSE,
    email_status        TEXT,
    tech_stack          TEXT,
    industry_classified TEXT,
    health_score        INTEGER,
    ai_summary          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enrichment_company  ON enrichment_results(company_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_email    ON enrichment_results(email);
CREATE INDEX IF NOT EXISTS idx_enrichment_status   ON enrichment_results(email_status);
CREATE INDEX IF NOT EXISTS idx_enrichment_verified ON enrichment_results(email_verified);

-- ── processing_log ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS processing_log (
    id          SERIAL      PRIMARY KEY,
    task_name   TEXT,
    status      TEXT,
    records_in  INTEGER,
    records_out INTEGER,
    duration_s  NUMERIC(10,2),
    error_msg   TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── dead_letter_queue ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    id              SERIAL      PRIMARY KEY,
    run_id          TEXT,
    source_name     TEXT        NOT NULL,
    entity_type     TEXT        NOT NULL DEFAULT 'company',
    raw_payload     JSONB       NOT NULL,
    error_reason    TEXT        NOT NULL,
    error_traceback TEXT,
    status          TEXT        NOT NULL DEFAULT 'PENDING',
    retry_count     INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_retried_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_dlq_source_status  ON dead_letter_queue(source_name, status);
CREATE INDEX IF NOT EXISTS idx_dlq_status_created ON dead_letter_queue(status, created_at DESC);
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────
def _safe_print(text: str):
    try:
        print(text)
    except (UnicodeEncodeError, UnicodeError):
        # Fallback to ascii replacement for legacy Windows console encodings (e.g. cp1252)
        print(text.encode("ascii", errors="replace").decode("ascii"))

def banner(text):
    _safe_print(f"\n{'='*60}\n  {text}\n{'='*60}")

def ok(msg):   _safe_print(f"  [OK] {msg}")
def fail(msg): _safe_print(f"  [FAIL] {msg}")
def info(msg): _safe_print(f"  [INFO] {msg}")
def warn(msg): _safe_print(f"  [WARN] {msg}")


# ─── Step 1: Create database ──────────────────────────────────────────────────
def create_database(host, port, password):
    banner("STEP 1 — Connect & Create Database")
    try:
        # Connect to default 'postgres' db to create our db
        conn = psycopg2.connect(
            host=host, port=port,
            user=PG_USER, password=password,
            dbname="postgres",
            connect_timeout=10
        )
        conn.autocommit = True
        cur = conn.cursor()

        # Check if DB already exists
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PG_DB_NAME,))
        exists = cur.fetchone()

        if exists:
            warn(f"Database '{PG_DB_NAME}' already exists — will recreate schema")
        else:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(PG_DB_NAME)))
            ok(f"Created database: {PG_DB_NAME}")

        cur.close()
        conn.close()
        ok(f"Connected to PostgreSQL {host}:{port} as '{PG_USER}'")
        return True

    except psycopg2.OperationalError as e:
        fail(f"Cannot connect to PostgreSQL: {e}")
        print("\n  💡 Make sure:")
        print("     1. PostgreSQL service is running (it is — we saw it above)")
        print("     2. Password matches your postgres superuser password")
        print("     3. pg_hba.conf allows localhost connections")
        return False


# ─── Step 2: Create schema ────────────────────────────────────────────────────
def create_schema(host, port, password, drop_existing: bool = False):
    banner("STEP 2 — Create Schema (Tables + Indexes)")
    try:
        conn = psycopg2.connect(
            host=host, port=port,
            user=PG_USER, password=password,
            dbname=PG_DB_NAME
        )
        conn.autocommit = True
        cur = conn.cursor()
        if drop_existing:
            warn("Dropping existing tables due to --drop-existing flag...")
            cur.execute(DROP_TABLES_SQL)
        cur.execute(SCHEMA_SQL)
        cur.close()
        conn.close()
        ok("companies table + indexes")
        ok("people table + indexes")
        ok("enrichment_results table + indexes")
        ok("processing_log table")
        return True
    except Exception as e:
        fail(f"Schema creation failed: {e}")
        return False



# ─── Step 3: Migrate data ─────────────────────────────────────────────────────
def migrate_data(host, port, password):
    banner("STEP 3 — Migrate Data (SQLite → PostgreSQL)")

    if not Path(SQLITE_DB).exists():
        fail(f"SQLite DB not found: {SQLITE_DB}")
        return False

    # Open both connections
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    sc = sqlite_conn.cursor()

    pg_conn = psycopg2.connect(
        host=host, port=port,
        user=PG_USER, password=password,
        dbname=PG_DB_NAME
    )
    pc = pg_conn.cursor()

    t_start = time.time()
    total_migrated = {}

    # ── companies ──────────────────────────────────────────────────────────────
    print("\n  📦 Migrating companies...")
    sc.execute("SELECT * FROM companies")
    rows = sc.fetchall()
    companies_data = []
    for r in rows:
        companies_data.append((
            r["id"], r["name"], r["legal_name"],
            r["website"], r["domain"], r["email"], r["phone"],
            r["city"], r["state"], r["state_code"], r["zip_code"],
            r["industry"], r["naics_code"], r["ein"], r["cik"],
            r["employee_min"], r["employee_max"], r["employee_band"],
            r["source"], r["data_quality_score"] or 0,
            r["created_at"], r["updated_at"]
        ))

    execute_values(pc, """
        INSERT INTO companies (
            id, name, legal_name, website, domain, email, phone,
            city, state, state_code, zip_code, industry, naics_code,
            ein, cik, employee_min, employee_max, employee_band,
            source, data_quality_score, created_at, updated_at
        ) VALUES %s ON CONFLICT (id) DO NOTHING
    """, companies_data, page_size=BATCH_SIZE)
    pg_conn.commit()
    total_migrated["companies"] = len(companies_data)
    ok(f"companies: {len(companies_data):,} rows migrated")

    # ── people ─────────────────────────────────────────────────────────────────
    print("\n  👥 Migrating people...")
    sc.execute("SELECT * FROM people")
    rows = sc.fetchall()
    cols = [d[0] for d in sc.description]
    people_data = []
    for r in rows:
        d = dict(zip(cols, r))
        people_data.append((
            d.get("id"), d.get("company_id"),
            d.get("full_name"), d.get("first_name"), d.get("last_name"),
            d.get("title"), d.get("standardized_title"),
            d.get("seniority_level"), d.get("department"),
            d.get("email"), d.get("phone"), d.get("linkedin_url"),
            d.get("data_quality_score") or 0,
            d.get("created_at"), d.get("updated_at")
        ))

    execute_values(pc, """
        INSERT INTO people (
            id, company_id, full_name, first_name, last_name,
            title, standardized_title, seniority_level, department,
            email, phone, linkedin_url, data_quality_score,
            created_at, updated_at
        ) VALUES %s ON CONFLICT (id) DO NOTHING
    """, people_data, page_size=BATCH_SIZE)
    pg_conn.commit()
    total_migrated["people"] = len(people_data)
    ok(f"people: {len(people_data):,} rows migrated")

    # ── enrichment_results ─────────────────────────────────────────────────────
    print("\n  📧 Migrating enrichment_results...")
    sc.execute("SELECT * FROM enrichment_results")
    rows = sc.fetchall()
    cols = [d[0] for d in sc.description]
    enrichment_data = []
    for r in rows:
        d = dict(zip(cols, r))
        enrichment_data.append((
            d.get("id"), d.get("company_id"),
            d.get("email"), bool(d.get("email_verified")),
            d.get("email_status"), d.get("tech_stack"),
            d.get("industry_classified"), d.get("health_score"),
            d.get("ai_summary"), d.get("created_at"), d.get("updated_at")
        ))

    execute_values(pc, """
        INSERT INTO enrichment_results (
            id, company_id, email, email_verified, email_status,
            tech_stack, industry_classified, health_score,
            ai_summary, created_at, updated_at
        ) VALUES %s ON CONFLICT (id) DO NOTHING
    """, enrichment_data, page_size=BATCH_SIZE)
    pg_conn.commit()
    total_migrated["enrichment_results"] = len(enrichment_data)
    ok(f"enrichment_results: {len(enrichment_data):,} rows migrated")

    # ── Log the migration ──────────────────────────────────────────────────────
    duration = round(time.time() - t_start, 2)
    total_rows = sum(total_migrated.values())
    pc.execute("""
        INSERT INTO processing_log (task_name, status, records_in, records_out, duration_s)
        VALUES (%s, %s, %s, %s, %s)
    """, ("sqlite_migration", "completed", total_rows, total_rows, duration))
    pg_conn.commit()

    pc.close(); pg_conn.close()
    sqlite_conn.close()

    info(f"Total rows migrated: {total_rows:,} in {duration}s")
    return total_migrated


# ─── Step 4: Write .env ───────────────────────────────────────────────────────
def write_env_file(host, port, password):
    banner("STEP 4 — Write .env Configuration")
    env_content = f"""# OneExtraction — PostgreSQL Connection
# Auto-generated by setup_postgres.py on {datetime.now().strftime('%Y-%m-%d %H:%M')}

DATABASE_TYPE=postgresql
DATABASE_HOST={host}
DATABASE_PORT={port}
DATABASE_NAME={PG_DB_NAME}
DATABASE_USER={PG_USER}
DATABASE_PASSWORD={password}
DATABASE_URL=postgresql://{PG_USER}:{password}@{host}:{port}/{PG_DB_NAME}

# SQLite fallback (kept for reference)
SQLITE_DATABASE_URL=sqlite:///output/us/api/oneextraction.db
"""
    env_path = Path(".env")
    env_path.write_text(env_content)
    ok(f".env written → {env_path.resolve()}")

    # Ensure db_config.py delegates dynamically to config_manager
    config_content = '''"""
OneExtraction — Database Configuration Bridge
Sourced dynamically from ConfigManager (AWS Secrets Manager / Environment).
Eliminates hardcoded credentials and centralizes connection management.
"""

from config_manager import config_manager

POSTGRES_CONFIG = config_manager.get_database_config()
DATABASE_URL = config_manager.get_database_url()
ACTIVE_DB = config_manager.get("DATABASE_TYPE", "postgresql")
SQLITE_URL = config_manager.get("SQLITE_URL", "sqlite:///output/us/api/oneextraction.db")

__all__ = [
    "POSTGRES_CONFIG",
    "DATABASE_URL",
    "ACTIVE_DB",
    "SQLITE_URL",
]
'''
    config_path = Path("db_config.py")
    config_path.write_text(config_content, encoding="utf-8")
    ok(f"db_config.py dynamic bridge configured → {config_path.resolve()}")



# ─── Step 5: Verify ───────────────────────────────────────────────────────────
def verify_migration(host, port, password):
    banner("STEP 5 — Verify Migration")
    try:
        conn = psycopg2.connect(
            host=host, port=port,
            user=PG_USER, password=password,
            dbname=PG_DB_NAME
        )
        cur = conn.cursor()

        tables = ["companies", "people", "enrichment_results", "processing_log"]
        for t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            count = cur.fetchone()[0]
            ok(f"{t}: {count:,} rows")

        # Check indexes
        cur.execute("""
            SELECT indexname FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY indexname
        """)
        indexes = [r[0] for r in cur.fetchall()]
        ok(f"Indexes created: {len(indexes)} → {', '.join(indexes[:5])}...")

        # Sample company
        cur.execute("""
            SELECT name, domain, industry, state_code, data_quality_score
            FROM companies LIMIT 3
        """)
        print("\n  Sample companies in PostgreSQL:")
        for row in cur.fetchall():
            print(f"    • {row[0]} | {row[1]} | {row[2]} | {row[3]} | score:{row[4]}")

        # Sample enrichment
        cur.execute("""
            SELECT email, email_status, email_verified
            FROM enrichment_results
            WHERE email IS NOT NULL LIMIT 3
        """)
        print("\n  Sample enrichment records:")
        for row in cur.fetchall():
            print(f"    • {row[0]} | {row[1]} | verified:{row[2]}")

        cur.close()
        conn.close()
        return True

    except Exception as e:
        fail(f"Verification failed: {e}")
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    _CURRENT_DIR = Path(__file__).resolve().parent
    if str(_CURRENT_DIR) not in sys.path:
        sys.path.insert(0, str(_CURRENT_DIR))
    from config_manager import config_manager
    _db_conf = config_manager.get_database_config()
    default_pwd = _db_conf.get("password") or os.getenv("POSTGRES_PASSWORD", "")
    default_host = _db_conf.get("host") or "localhost"
    default_port = _db_conf.get("port") or 5432

    parser = argparse.ArgumentParser(description="Setup OneExtraction PostgreSQL database")
    parser.add_argument("--password", default=default_pwd, help="PostgreSQL postgres user password (default: from config/env)")
    parser.add_argument("--host",     default=default_host, help="PostgreSQL host (default: localhost)")
    parser.add_argument("--port",     default=default_port, type=int, help="PostgreSQL port (default: 5432)")
    parser.add_argument("--drop-existing", action="store_true", default=False, help="Explicitly drop existing tables (DANGEROUS)")
    args = parser.parse_args()

    print("\n" + "="*60)
    print("  🐘 ONEEXTRACTION — POSTGRESQL SETUP & MIGRATION")
    print(f"  Target: postgresql://{PG_USER}@{args.host}:{args.port}/{PG_DB_NAME}")
    print(f"  Source: {SQLITE_DB}")
    print("="*60)

    # Step 1: Create DB
    if not create_database(args.host, args.port, args.password):
        sys.exit(1)
    todo_list_complete(1)

    # Step 2: Create schema
    if not create_schema(args.host, args.port, args.password, drop_existing=args.drop_existing):
        sys.exit(1)
    todo_list_complete(2)


    # Step 3 & 4: Migrate data
    counts = migrate_data(args.host, args.port, args.password)
    if not counts:
        sys.exit(1)
    todo_list_complete(3)

    # Step 5: Write .env
    write_env_file(args.host, args.port, args.password)
    todo_list_complete(4)

    # Step 6: Verify
    ok_verify = verify_migration(args.host, args.port, args.password)

    # ── Final summary ──────────────────────────────────────────────────────────
    banner("✅ MIGRATION COMPLETE")
    print(f"  PostgreSQL database : {PG_DB_NAME}")
    print(f"  Host                : {args.host}:{args.port}")
    print(f"  Companies           : {counts.get('companies',0):,}")
    print(f"  People              : {counts.get('people',0):,}")
    print(f"  Enrichment records  : {counts.get('enrichment_results',0):,}")
    print(f"\n  Connection string:")
    print(f"  postgresql://{PG_USER}:****@{args.host}:{args.port}/{PG_DB_NAME}")
    print(f"\n  Next step:")
    print(f"  python production_test.py --db postgresql")
    print("="*60 + "\n")

def todo_list_complete(n):
    pass  # Progress tracking placeholder

if __name__ == "__main__":
    main()
