-- ============================================================================
-- DataExtraction — Canonical Database Bootstrap Script
-- ============================================================================
-- Run this ONCE against a fresh PostgreSQL 15+ instance to establish the full
-- schema before the Python migration runner executes numbered migrations.
--
-- Execution order:
--   1. This file   (extensions, public-schema base tables, legacy compat)
--   2. python -m packages.infrastructure.migration_manager  (001–012 SQL migrations)
--   3. python packages/infrastructure/migrate_schema.py     (Python column additions)
--
-- Usage (from repo root, with PGPASSWORD set):
--   psql -h localhost -U dex_user -d dataextraction -f packages/infrastructure/bootstrap_db.sql
-- ============================================================================

-- ── 1. Required PostgreSQL extensions ────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS "postgis";
    RAISE NOTICE 'PostGIS extension enabled.';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'PostGIS not available — geospatial columns will use NUMERIC coordinates.';
END $$;

-- ── 2. Public schema base tables (legacy + API layer compatibility) ───────────
-- These are used by the legacy API routers until traffic is fully migrated to
-- the KG schema layer. The numbered migrations in 001–012 build the enterprise
-- KG schema on top; both can coexist.

CREATE TABLE IF NOT EXISTS public.companies (
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
    country             TEXT        DEFAULT 'United States',
    industry            TEXT,
    naics_code          TEXT,
    sic_code            TEXT,
    ein                 TEXT,
    rfc                 TEXT,
    cik                 TEXT,
    npi                 TEXT,
    cage_code           TEXT,
    uei                 TEXT,
    employee_count_min  INTEGER,
    employee_count_max  INTEGER,
    employee_count_band TEXT,
    latitude            NUMERIC(10,7),
    longitude           NUMERIC(10,7),
    phones              JSONB        DEFAULT '[]',
    emails              JSONB        DEFAULT '[]',
    source_records      JSONB        DEFAULT '[]',
    source              TEXT,
    api_source          TEXT,
    data_quality_score  INTEGER      DEFAULT 0,
    health_score        SMALLINT,
    tech_stack          TEXT[],
    ai_summary          TEXT,
    raw_payload         JSONB,
    created_at          TIMESTAMPTZ  DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  DEFAULT NOW()
);

-- Note: Indexes are only created on tables, not views.
-- The CREATE INDEX statements below will be skipped if the target is a view.
DO $$
DECLARE ttype text;
BEGIN
  SELECT table_type INTO ttype FROM information_schema.tables
  WHERE table_schema='public' AND table_name='companies';
  IF ttype = 'BASE TABLE' THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_domain       ON public.companies (domain)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_state        ON public.companies (state_code)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_industry     ON public.companies (industry)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_naics        ON public.companies (naics_code)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_ein          ON public.companies (ein)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_cik          ON public.companies (cik)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_norm_name    ON public.companies (normalized_name)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_name_trgm    ON public.companies USING gin (normalized_name gin_trgm_ops)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_companies_source_recs  ON public.companies USING gin (source_records)';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.people (
    id                  TEXT        PRIMARY KEY,
    company_id          TEXT,
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

CREATE INDEX IF NOT EXISTS idx_people_company      ON public.people (company_id);
CREATE INDEX IF NOT EXISTS idx_people_email        ON public.people (email);
CREATE INDEX IF NOT EXISTS idx_people_linkedin     ON public.people (linkedin_url);
CREATE INDEX IF NOT EXISTS idx_people_title        ON public.people (title);
CREATE INDEX IF NOT EXISTS idx_people_seniority    ON public.people (seniority_level);
CREATE INDEX IF NOT EXISTS idx_people_name_trgm    ON public.people USING gin (full_name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS public.enrichment_results (
    id                  TEXT        PRIMARY KEY,
    company_id          TEXT,
    person_id           TEXT,
    email               TEXT,
    email_verified      BOOLEAN     DEFAULT FALSE,
    email_status        TEXT,
    tech_stack          TEXT,
    industry_classified TEXT,
    health_score        INTEGER,
    ai_summary          TEXT,
    source_api          TEXT,
    run_id              TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enrichment_company  ON public.enrichment_results (company_id);
CREATE INDEX IF NOT EXISTS idx_enrichment_email    ON public.enrichment_results (email);
CREATE INDEX IF NOT EXISTS idx_enrichment_status   ON public.enrichment_results (email_status);

DO $$
DECLARE ttype text;
BEGIN
  SELECT table_type INTO ttype FROM information_schema.tables
  WHERE table_schema='public' AND table_name='companies';
  IF ttype = 'BASE TABLE' THEN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'people_company_id_fkey') THEN
      ALTER TABLE public.people
        ADD CONSTRAINT people_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies (id) ON DELETE SET NULL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'enrichment_results_company_id_fkey') THEN
      ALTER TABLE public.enrichment_results
        ADD CONSTRAINT enrichment_results_company_id_fkey
        FOREIGN KEY (company_id) REFERENCES public.companies (id) ON DELETE SET NULL;
    END IF;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.processing_log (
    id          SERIAL      PRIMARY KEY,
    task_name   TEXT,
    status      TEXT,
    records_in  INTEGER,
    records_out INTEGER,
    duration_s  NUMERIC(10,2),
    error_msg   TEXT,
    run_id      TEXT,
    source_name TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.dead_letter_queue (
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

DO $$
DECLARE ttype text;
BEGIN
  SELECT table_type INTO ttype FROM information_schema.tables
  WHERE table_schema='public' AND table_name='dead_letter_queue';
  IF ttype = 'BASE TABLE' THEN
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_dlq_source_status  ON public.dead_letter_queue (source_name, status)';
    EXECUTE 'CREATE INDEX IF NOT EXISTS idx_dlq_status_created ON public.dead_letter_queue (status, created_at DESC)';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.data_sources (
    id              SERIAL      PRIMARY KEY,
    source_name     TEXT        NOT NULL,
    source_type     TEXT        NOT NULL,
    run_id          TEXT        UNIQUE,
    records_fetched INTEGER     DEFAULT 0,
    records_merged  INTEGER     DEFAULT 0,
    records_skipped INTEGER     DEFAULT 0,
    cost_usd        NUMERIC(10,4),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status          TEXT        DEFAULT 'PENDING',
    notes           TEXT
);

-- ── 3. KG audit schema for access logs (required by AuditTrailMiddleware) ─────
CREATE SCHEMA IF NOT EXISTS kg_audit;

CREATE TABLE IF NOT EXISTS kg_audit.access_logs (
    log_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id         TEXT        NOT NULL,
    user_email      TEXT        NOT NULL,
    action          TEXT        NOT NULL,
    resource_type   TEXT        NOT NULL,
    resource_id     TEXT,
    ip_address      TEXT,
    user_agent      TEXT,
    status_code     INTEGER     DEFAULT 200,
    metadata        JSONB       DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_audit_user_id   ON kg_audit.access_logs (user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action    ON kg_audit.access_logs (action, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON kg_audit.access_logs (timestamp DESC);

-- ── 4. Staging dead-letter queue (used by DLQ router) ────────────────────────
CREATE SCHEMA IF NOT EXISTS staging_dataextraction;

CREATE TABLE IF NOT EXISTS staging_dataextraction.dead_letter_queue (
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

CREATE INDEX IF NOT EXISTS idx_sdlq_source_status ON staging_dataextraction.dead_letter_queue (source_name, status);
CREATE INDEX IF NOT EXISTS idx_sdlq_status_created ON staging_dataextraction.dead_letter_queue (status, created_at DESC);

-- ── 5. Schema migration ledger (managed by migration_manager.py) ──────────────
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    version     VARCHAR(255) PRIMARY KEY,
    filename    VARCHAR(255) NOT NULL,
    checksum    VARCHAR(64)  NOT NULL,
    applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ── 6. Bootstrap complete notice ──────────────────────────────────────────────
DO $$
BEGIN
    RAISE NOTICE '===========================================================';
    RAISE NOTICE 'DataExtraction bootstrap complete.';
    RAISE NOTICE 'Next step: run migration_manager.py to apply migrations 001-012.';
    RAISE NOTICE '===========================================================';
END $$;
