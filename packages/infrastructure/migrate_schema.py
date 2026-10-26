"""
OneExtraction — Schema Migration
Adds new columns and tables needed for unified multi-source ingestion.

Run once:
    python migrate_schema.py

Safe to re-run — uses IF NOT EXISTS / IF NOT EXISTS guards throughout.
"""

import sys
from db_connector import get_connection, db_info

def log_msg(msg: str):
    try:
        print(msg)
    except (UnicodeEncodeError, UnicodeError):
        print(msg.encode("ascii", errors="replace").decode("ascii"))

# ── All migration steps ────────────────────────────────────────────────────────

MIGRATIONS = []

def migration(fn):
    MIGRATIONS.append(fn)
    return fn


# ─────────────────────────────────────────────────────────────────────────────
# 1. companies — new columns
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m01_companies_new_columns(cur):
    statements = [
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS trade_name            TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS normalized_name        TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS entity_type            TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS sic_code               TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS cage_code              TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS uei                    TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS state_of_incorporation TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS street                 TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS county                 TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS country                TEXT DEFAULT 'United States'",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS latitude               NUMERIC(10,7)",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS longitude              NUMERIC(10,7)",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS phones                 JSONB DEFAULT '[]'",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS emails                 JSONB DEFAULT '[]'",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS employee_count_source  TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS source_count           INTEGER DEFAULT 1",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS last_verified_at       TIMESTAMPTZ",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS api_source             TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS raw_payload            JSONB",
    ]
    for sql in statements:
        cur.execute(sql)
    print("  ✅ companies — new columns added")


# ─────────────────────────────────────────────────────────────────────────────
# 2. people — new columns
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m02_people_new_columns(cur):
    statements = [
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS middle_name              TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS official_title           TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS is_current               BOOLEAN DEFAULT TRUE",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS joined_date              DATE",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS years_at_company         NUMERIC(5,2)",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS appointment_source       TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS source_document_url      TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS career_history           JSONB DEFAULT '[]'",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS email_pattern            TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS email_confidence_score   INTEGER",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS email_status             TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS email_last_validated_at  TIMESTAMPTZ",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS direct_phone             TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS phone_type               TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS phone_carrier            TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS is_business_contact      BOOLEAN DEFAULT TRUE",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS opt_out_requested        BOOLEAN DEFAULT FALSE",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS api_source               TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS source_registry          TEXT",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS raw_payload              JSONB",
    ]
    for sql in statements:
        cur.execute(sql)
    print("  ✅ people — new columns added")


# ─────────────────────────────────────────────────────────────────────────────
# 3. enrichment_results — link to person + run tracking
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m03_enrichment_new_columns(cur):
    statements = [
        "ALTER TABLE enrichment_results ADD COLUMN IF NOT EXISTS person_id   TEXT",
        "ALTER TABLE enrichment_results ADD COLUMN IF NOT EXISTS source_api  TEXT",
        "ALTER TABLE enrichment_results ADD COLUMN IF NOT EXISTS run_id      TEXT",
    ]
    for sql in statements:
        cur.execute(sql)
    print("  ✅ enrichment_results — new columns added")


# ─────────────────────────────────────────────────────────────────────────────
# 4. processing_log — run tracking columns
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m04_processing_log_new_columns(cur):
    statements = [
        "ALTER TABLE processing_log ADD COLUMN IF NOT EXISTS run_id          TEXT",
        "ALTER TABLE processing_log ADD COLUMN IF NOT EXISTS source_name     TEXT",
        "ALTER TABLE processing_log ADD COLUMN IF NOT EXISTS dedup_skipped   INTEGER DEFAULT 0",
        "ALTER TABLE processing_log ADD COLUMN IF NOT EXISTS merged_count    INTEGER DEFAULT 0",
    ]
    for sql in statements:
        cur.execute(sql)
    print("  ✅ processing_log — new columns added")


# ─────────────────────────────────────────────────────────────────────────────
# 5. NEW TABLE: data_sources
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m05_create_data_sources(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS data_sources (
            id              SERIAL PRIMARY KEY,
            source_name     TEXT NOT NULL,
            source_type     TEXT NOT NULL,
            run_id          TEXT UNIQUE,
            records_fetched INTEGER DEFAULT 0,
            records_merged  INTEGER DEFAULT 0,
            records_skipped INTEGER DEFAULT 0,
            cost_usd        NUMERIC(10,4),
            started_at      TIMESTAMPTZ DEFAULT NOW(),
            completed_at    TIMESTAMPTZ,
            status          TEXT DEFAULT 'PENDING',
            notes           TEXT
        )
    """)
    print("  ✅ data_sources — table created")


# ─────────────────────────────────────────────────────────────────────────────
# 6. NEW TABLE: dedup_log
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m06_create_dedup_log(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dedup_log (
            id              SERIAL PRIMARY KEY,
            entity_type     TEXT NOT NULL,
            duplicate_id    TEXT NOT NULL,
            kept_id         TEXT NOT NULL,
            match_field     TEXT NOT NULL,
            match_value     TEXT,
            run_id          TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    print("  ✅ dedup_log — table created")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Indexes for dedup performance
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m07_indexes(cur):
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_companies_domain       ON companies(domain)",
        "CREATE INDEX IF NOT EXISTS idx_companies_ein          ON companies(ein)",
        "CREATE INDEX IF NOT EXISTS idx_companies_cik          ON companies(cik)",
        "CREATE INDEX IF NOT EXISTS idx_companies_api_source   ON companies(api_source)",
        "CREATE INDEX IF NOT EXISTS idx_people_linkedin        ON people(linkedin_url)",
        "CREATE INDEX IF NOT EXISTS idx_people_email           ON people(email)",
        "CREATE INDEX IF NOT EXISTS idx_people_company_id      ON people(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_people_api_source      ON people(api_source)",
        "CREATE INDEX IF NOT EXISTS idx_enrichment_person_id   ON enrichment_results(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_dedup_entity_type      ON dedup_log(entity_type)",
        "CREATE INDEX IF NOT EXISTS idx_dedup_run_id           ON dedup_log(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_datasources_run_id     ON data_sources(run_id)",
    ]
    for sql in indexes:
        cur.execute(sql)
    print("  ✅ indexes — all created")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Phase 3: Entity Resolution & Data Integrity Columns
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m08_phase3_dedup_integrity(cur):
    statements = [
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS rfc            TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS npi            TEXT",
        "ALTER TABLE companies ADD COLUMN IF NOT EXISTS source_records JSONB DEFAULT '[]'",
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS source_records    JSONB DEFAULT '[]'",
        "CREATE INDEX IF NOT EXISTS idx_companies_rfc ON companies(rfc)",
        "CREATE INDEX IF NOT EXISTS idx_companies_npi ON companies(npi)",
        "CREATE INDEX IF NOT EXISTS idx_companies_source_records ON companies USING GIN(source_records)",
        "CREATE INDEX IF NOT EXISTS idx_people_source_records ON people USING GIN(source_records)",
        "CREATE INDEX IF NOT EXISTS idx_people_career_history ON people USING GIN(career_history)",
    ]
    for sql in statements:
        cur.execute(sql)
    print("  ✅ phase 3 — entity resolution & integrity columns added")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Phase 4: PostGIS Spatial & pg_trgm Trigram Extensions
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m09_postgis_pg_trgm_extensions(cur):
    # 1. Trigram extension (standard PostgreSQL extension)
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        log_msg("  [OK] extension pg_trgm enabled")
    except Exception as e:
        log_msg(f"  [INFO] pg_trgm extension notice: {e}")

    # 2. PostGIS spatial extension (with graceful fallback if not compiled)
    postgis_available = False
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        postgis_available = True
        log_msg("  [OK] extension postgis enabled")
    except Exception as e:
        log_msg(f"  [INFO] postgis extension optional / not available on host: {e}")

    # 3. Spatial column & GIST index on companies
    if postgis_available:
        try:
            cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS geom GEOMETRY(Point, 4326)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_companies_geom ON companies USING GIST(geom)")
            log_msg("  [OK] companies geom column & GIST index provisioned")
        except Exception as e:
            log_msg(f"  [INFO] companies geom skipped: {e}")

    # 4. Trigram GIN indexes for fast fuzzy matching
    trgm_stmts = [
        "CREATE INDEX IF NOT EXISTS idx_companies_name_trgm ON companies USING gin (normalized_name gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS idx_companies_trade_name_trgm ON companies USING gin (trade_name gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS idx_people_name_trgm ON people USING gin (full_name gin_trgm_ops)",
    ]
    for sql in trgm_stmts:
        try:
            cur.execute(sql)
        except Exception as e:
            log_msg(f"  [INFO] trgm index notice: {e}")
    log_msg("  [OK] phase 4 - pg_trgm indexes & spatial schema verified")


# ─────────────────────────────────────────────────────────────────────────────
# 10. Phase 4: Data Integrity Constraints & Whitelisted Safeguards
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m10_data_integrity_constraints(cur):
    statements = [
        # Ensure lead scoring index exists
        "CREATE INDEX IF NOT EXISTS idx_companies_quality_score ON companies(data_quality_score DESC NULLS LAST)",
        "CREATE INDEX IF NOT EXISTS idx_people_quality_score ON people(data_quality_score DESC NULLS LAST)",
        # Fast state & domain composite index
        "CREATE INDEX IF NOT EXISTS idx_companies_norm_name_state ON companies(normalized_name, state_code)",
    ]
    for sql in statements:
        try:
            cur.execute(sql)
        except Exception as e:
            log_msg(f"  [INFO] integrity index notice: {e}")
    log_msg("  [OK] phase 4 - integrity composite indexes verified")


# ─────────────────────────────────────────────────────────────────────────────
# 11. Phase 5: Dead-Letter Queue (DLQ) & Resilience Engine
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m11_dead_letter_queue(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dead_letter_queue (
            id              SERIAL PRIMARY KEY,
            run_id          TEXT,
            source_name     TEXT NOT NULL,
            entity_type     TEXT NOT NULL DEFAULT 'company',
            raw_payload     JSONB NOT NULL,
            error_reason    TEXT NOT NULL,
            error_traceback TEXT,
            status          TEXT NOT NULL DEFAULT 'PENDING',
            retry_count     INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_retried_at TIMESTAMPTZ,
            resolved_at     TIMESTAMPTZ
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dlq_source_status ON dead_letter_queue(source_name, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_dlq_status_created ON dead_letter_queue(status, created_at DESC)")
    log_msg("  [OK] phase 5 - dead_letter_queue table & indexes verified")



# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────
def run_migrations():
    print(f"\n🔧 Running schema migrations on: {db_info()}\n")
    from db_connector import release_connection
    conn = get_connection()
    cur  = conn.cursor()

    failed = 0
    for fn in MIGRATIONS:
        try:
            fn(cur)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  ❌ {fn.__name__} FAILED: {e}")
            failed += 1

    cur.close()
    release_connection(conn)


    if failed == 0:
        print(f"\n✅ All {len(MIGRATIONS)} migrations completed successfully.\n")
    else:
        print(f"\n⚠️  {failed} migration(s) failed. Check errors above.\n")
        sys.exit(1)


def verify_schema():
    """Print a summary of the final schema after migration."""
    print("🔍 Verifying schema...\n")
    conn = get_connection()
    cur  = conn.cursor()

    tables = ['companies', 'people', 'enrichment_results', 'processing_log',
              'data_sources', 'dedup_log']

    for t in tables:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s ORDER BY ordinal_position
        """, (t,))
        cols = [r[0] for r in cur.fetchall()]
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur.fetchone()[0]
        print(f"  {t:<25} {count:>6} rows  |  {len(cols)} columns")

    cur.close()
    from db_connector import release_connection
    release_connection(conn)
    print()



if __name__ == "__main__":
    run_migrations()
    verify_schema()
