"""
OneExtraction — Schema Migration
Adds new columns and tables needed for unified multi-source ingestion.

Run once:
    python migrate_schema.py

Safe to re-run — uses IF NOT EXISTS / IF NOT EXISTS guards throughout.
"""

import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from db_connector import get_connection, db_info

def log_msg(msg: str):
    try:
        print(msg)
    except (UnicodeEncodeError, UnicodeError):
        print(msg.encode("ascii", errors="replace").decode("ascii"))

def _is_view(cur, table_name: str, schema: str = 'public') -> bool:
    cur.execute(
        "SELECT table_type FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
        (schema, table_name)
    )
    res = cur.fetchone()
    return bool(res and res[0] == 'VIEW')

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
    if _is_view(cur, "companies"):
        log_msg("  [INFO] companies is a view; skipping physical column alterations")
        return
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
    log_msg("  ✅ companies — new columns added")


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
        "CREATE INDEX IF NOT EXISTS idx_people_linkedin        ON people(linkedin_url)",
        "CREATE INDEX IF NOT EXISTS idx_people_email           ON people(email)",
        "CREATE INDEX IF NOT EXISTS idx_people_company_id      ON people(company_id)",
        "CREATE INDEX IF NOT EXISTS idx_people_api_source      ON people(api_source)",
        "CREATE INDEX IF NOT EXISTS idx_enrichment_person_id   ON enrichment_results(person_id)",
        "CREATE INDEX IF NOT EXISTS idx_dedup_entity_type      ON dedup_log(entity_type)",
        "CREATE INDEX IF NOT EXISTS idx_dedup_run_id           ON dedup_log(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_datasources_run_id     ON data_sources(run_id)",
    ]
    if not _is_view(cur, "companies"):
        indexes.extend([
            "CREATE INDEX IF NOT EXISTS idx_companies_domain       ON companies(domain)",
            "CREATE INDEX IF NOT EXISTS idx_companies_ein          ON companies(ein)",
            "CREATE INDEX IF NOT EXISTS idx_companies_cik          ON companies(cik)",
            "CREATE INDEX IF NOT EXISTS idx_companies_api_source   ON companies(api_source)",
        ])
    for sql in indexes:
        cur.execute(sql)
    log_msg("  ✅ indexes — all created")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Phase 3: Entity Resolution & Data Integrity Columns
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m08_phase3_dedup_integrity(cur):
    statements = [
        "ALTER TABLE people ADD COLUMN IF NOT EXISTS source_records    JSONB DEFAULT '[]'",
        "CREATE INDEX IF NOT EXISTS idx_people_source_records ON people USING GIN(source_records)",
        "CREATE INDEX IF NOT EXISTS idx_people_career_history ON people USING GIN(career_history)",
    ]
    if not _is_view(cur, "companies"):
        statements.extend([
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS rfc            TEXT",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS npi            TEXT",
            "ALTER TABLE companies ADD COLUMN IF NOT EXISTS source_records JSONB DEFAULT '[]'",
            "CREATE INDEX IF NOT EXISTS idx_companies_rfc ON companies(rfc)",
            "CREATE INDEX IF NOT EXISTS idx_companies_npi ON companies(npi)",
            "CREATE INDEX IF NOT EXISTS idx_companies_source_records ON companies USING GIN(source_records)",
        ])
    for sql in statements:
        cur.execute(sql)
    log_msg("  ✅ phase 3 — entity resolution & integrity columns added")


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
        cur.execute("SAVEPOINT sp_postgis")
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        cur.execute("RELEASE SAVEPOINT sp_postgis")
        postgis_available = True
        log_msg("  [OK] extension postgis enabled")
    except Exception as e:
        cur.execute("ROLLBACK TO SAVEPOINT sp_postgis")
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
        "CREATE INDEX IF NOT EXISTS idx_people_name_trgm ON people USING gin (full_name gin_trgm_ops)",
    ]
    if not _is_view(cur, "companies"):
        trgm_stmts.extend([
            "CREATE INDEX IF NOT EXISTS idx_companies_name_trgm ON companies USING gin (normalized_name gin_trgm_ops)",
            "CREATE INDEX IF NOT EXISTS idx_companies_trade_name_trgm ON companies USING gin (trade_name gin_trgm_ops)",
        ])
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
        "CREATE INDEX IF NOT EXISTS idx_people_quality_score ON people(data_quality_score DESC NULLS LAST)",
    ]
    if not _is_view(cur, "companies"):
        statements.extend([
            "CREATE INDEX IF NOT EXISTS idx_companies_quality_score ON companies(data_quality_score DESC NULLS LAST)",
            "CREATE INDEX IF NOT EXISTS idx_companies_norm_name_state ON companies(normalized_name, state_code)",
        ])
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
# 12. Pre-Master Working Layer & Master Lifecycle Columns (Sprint 1)
# ─────────────────────────────────────────────────────────────────────────────
@migration
def m12_pre_master_working_layer_and_master_lifecycle(cur):
    # 1. Staging pre-master working canvas
    cur.execute("CREATE SCHEMA IF NOT EXISTS staging_dataextraction")
    cur.execute("CREATE SCHEMA IF NOT EXISTS master_dataextraction")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staging_dataextraction.working_organizations (
            working_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id VARCHAR(100) NOT NULL UNIQUE,
            legal_name VARCHAR(255) NOT NULL,
            display_name VARCHAR(255),
            primary_domain VARCHAR(255),
            website TEXT,
            statutory_tax_id VARCHAR(50),
            sec_cik VARCHAR(20),
            gleif_lei VARCHAR(50),
            jurisdiction VARCHAR(10) DEFAULT 'US',
            industry VARCHAR(150),
            naics_code VARCHAR(10),
            sic_code VARCHAR(10),
            employee_count_min INT,
            employee_count_max INT,
            annual_revenue_usd NUMERIC(15, 2),
            phones JSONB DEFAULT '[]'::jsonb,
            locations JSONB DEFAULT '[]'::jsonb,
            canonical_cluster_id TEXT,
            identity_confidence NUMERIC(5, 4) DEFAULT 1.0000,
            email_verification_status VARCHAR(50) DEFAULT 'PENDING',
            executive_enrichment_status VARCHAR(50) DEFAULT 'PENDING',
            data_quality_score INT DEFAULT 0,
            trust_score NUMERIC(5, 4) DEFAULT 0.0000,
            governance_status VARCHAR(50) DEFAULT 'IN_ENRICHMENT',
            contributing_sources TEXT[] DEFAULT ARRAY['REGISTRY']::TEXT[],
            lineage_ids JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staging_dataextraction.working_persons (
            working_person_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            person_id VARCHAR(100) NOT NULL UNIQUE,
            org_id VARCHAR(100) NOT NULL REFERENCES staging_dataextraction.working_organizations(org_id) ON DELETE CASCADE,
            full_name VARCHAR(255) NOT NULL,
            first_name VARCHAR(100),
            last_name VARCHAR(100),
            title VARCHAR(150),
            seniority VARCHAR(50),
            department VARCHAR(50),
            primary_email VARCHAR(255),
            primary_phone VARCHAR(50),
            linkedin_url TEXT,
            confidence_score NUMERIC(5, 4) DEFAULT 0.8500,
            governance_status VARCHAR(50) DEFAULT 'IN_ENRICHMENT',
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS staging_dataextraction.working_emails (
            working_email_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id VARCHAR(100) NOT NULL REFERENCES staging_dataextraction.working_organizations(org_id) ON DELETE CASCADE,
            email_address VARCHAR(255) NOT NULL,
            mailbox_user VARCHAR(100),
            email_domain VARCHAR(255) NOT NULL,
            deliverability_status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
            confidence_score INT DEFAULT 0,
            is_catchall BOOLEAN DEFAULT FALSE,
            mx_record TEXT,
            smtp_verified_at TIMESTAMPTZ,
            discovery_source VARCHAR(100) DEFAULT 'WEBSITE_CRAWL',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            CONSTRAINT uq_working_org_email UNIQUE (org_id, email_address)
        )
    """)

    # 2. Master Organizations Lifecycle & Freshness Metadata
    master_org_cols = [
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS governance_status VARCHAR(50) DEFAULT 'CERTIFIED'",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS trust_score NUMERIC(5, 4) DEFAULT 0.9500",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS freshness_score NUMERIC(5, 4) DEFAULT 1.0000",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS next_verification_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '90 days')",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS verification_source VARCHAR(100) DEFAULT 'INITIAL_PROMOTION_GATE'",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS website_last_verified_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS email_last_verified_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS executive_last_verified_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS domain_last_verified_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS maps_last_verified_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE master_dataextraction.organizations ADD COLUMN IF NOT EXISTS registry_last_verified_at TIMESTAMPTZ DEFAULT NOW()",
    ]
    for col_sql in master_org_cols:
        cur.execute(col_sql)

    # 3. Master Persons Lifecycle Metadata
    master_person_cols = [
        "ALTER TABLE master_dataextraction.persons ADD COLUMN IF NOT EXISTS governance_status VARCHAR(50) DEFAULT 'CERTIFIED'",
        "ALTER TABLE master_dataextraction.persons ADD COLUMN IF NOT EXISTS trust_score NUMERIC(5, 4) DEFAULT 0.9000",
        "ALTER TABLE master_dataextraction.persons ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE master_dataextraction.persons ADD COLUMN IF NOT EXISTS next_verification_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '90 days')",
    ]
    for col_sql in master_person_cols:
        cur.execute(col_sql)

    # 4. Indexes
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_working_org_domain ON staging_dataextraction.working_organizations (primary_domain)",
        "CREATE INDEX IF NOT EXISTS idx_working_gov_status ON staging_dataextraction.working_organizations (governance_status)",
        "CREATE INDEX IF NOT EXISTS idx_working_email_status ON staging_dataextraction.working_emails (deliverability_status)",
        "CREATE INDEX IF NOT EXISTS idx_working_person_org ON staging_dataextraction.working_persons (org_id)",
        "CREATE INDEX IF NOT EXISTS idx_master_org_next_verif ON master_dataextraction.organizations (next_verification_at ASC) WHERE governance_status = 'CERTIFIED'",
        "CREATE INDEX IF NOT EXISTS idx_master_org_gov_freshness ON master_dataextraction.organizations (governance_status, freshness_score)",
    ]
    for idx_sql in indexes:
        cur.execute(idx_sql)

    log_msg("  [OK] sprint 1 - pre-master working layer & master lifecycle columns migrated successfully")



# ─────────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────────
def run_migrations():
    log_msg(f"\n🔧 Running schema migrations on: {db_info()}\n")
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
            log_msg(f"  ❌ {fn.__name__} FAILED: {e}")
            failed += 1

    cur.close()
    release_connection(conn)


    if failed == 0:
        log_msg(f"\n✅ All {len(MIGRATIONS)} migrations completed successfully.\n")
    else:
        log_msg(f"\n⚠️  {failed} migration(s) failed. Check errors above.\n")
        sys.exit(1)


def verify_schema():
    """Print a summary of the final schema after migration."""
    log_msg("🔍 Verifying schema...\n")
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
        log_msg(f"  {t:<25} {count:>6} rows  |  {len(cols)} columns")

    cur.close()
    from db_connector import release_connection
    release_connection(conn)
    log_msg("")



if __name__ == "__main__":
    run_migrations()
    verify_schema()
