-- =============================================================================
-- Migration: 004_create_email_enrichment_schema.sql
-- Description: Establishes schema for FORGE email enrichment, results, and audit telemetry
-- Safe to re-run (idempotent DDL with IF NOT EXISTS)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── 1. email_enrichment_jobs ──────────────────────────────────────────────────
-- Durable tracking of batch enrichment runs, offsets, and progress metrics
CREATE TABLE IF NOT EXISTS email_enrichment_jobs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type                VARCHAR(50) NOT NULL DEFAULT 'POST_DEDUP_CANONICAL',
    status                  VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    total_records           INTEGER NOT NULL DEFAULT 0,
    processed_records       INTEGER NOT NULL DEFAULT 0,
    successful_discoveries  INTEGER NOT NULL DEFAULT 0,
    failed_records          INTEGER NOT NULL DEFAULT 0,
    last_processed_id       TEXT,
    target_table            VARCHAR(50) NOT NULL DEFAULT 'companies',
    batch_size              INTEGER NOT NULL DEFAULT 500,
    max_concurrency         INTEGER NOT NULL DEFAULT 50,
    error_message           TEXT,
    execution_metadata      JSONB DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ee_jobs_status ON email_enrichment_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ee_jobs_created ON email_enrichment_jobs(created_at DESC);

-- ── 2. email_enrichment_results ───────────────────────────────────────────────
-- Verified email assets, deliverability ratings, and technical profiling
CREATE TABLE IF NOT EXISTS email_enrichment_results (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                  UUID REFERENCES email_enrichment_jobs(id) ON DELETE SET NULL,
    company_id              TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    domain                  VARCHAR(255) NOT NULL,
    primary_email           VARCHAR(255),
    all_emails              JSONB NOT NULL DEFAULT '[]'::jsonb,
    discovery_source        VARCHAR(50) NOT NULL,
    deliverability_status   VARCHAR(30) NOT NULL,
    confidence_score        NUMERIC(4,3) NOT NULL DEFAULT 0.000,
    is_catchall             BOOLEAN NOT NULL DEFAULT FALSE,
    tech_stack              JSONB DEFAULT '[]'::jsonb,
    cms_detected            VARCHAR(100),
    ssl_valid               BOOLEAN,
    site_speed_ms           INTEGER,
    http_status_code        INTEGER,
    enrichment_attempts     INTEGER NOT NULL DEFAULT 1,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_company_email_result UNIQUE (company_id)
);

CREATE INDEX IF NOT EXISTS idx_ee_results_company ON email_enrichment_results(company_id);
CREATE INDEX IF NOT EXISTS idx_ee_results_domain ON email_enrichment_results(domain);
CREATE INDEX IF NOT EXISTS idx_ee_results_status ON email_enrichment_results(deliverability_status);
CREATE INDEX IF NOT EXISTS idx_ee_results_confidence ON email_enrichment_results(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_ee_results_all_emails ON email_enrichment_results USING gin (all_emails);

-- ── 3. email_discovery_audit ──────────────────────────────────────────────────
-- Immutable telemetry of every HTTP crawl request and SMTP probe
CREATE TABLE IF NOT EXISTS email_discovery_audit (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                  UUID REFERENCES email_enrichment_jobs(id) ON DELETE CASCADE,
    company_id              TEXT REFERENCES companies(id) ON DELETE CASCADE,
    target_domain           VARCHAR(255) NOT NULL,
    probed_email            VARCHAR(255),
    probe_type              VARCHAR(40) NOT NULL,
    mx_host                 VARCHAR(255),
    smtp_code               INTEGER,
    smtp_response           TEXT,
    duration_ms             NUMERIC(8,2) NOT NULL,
    is_success              BOOLEAN NOT NULL DEFAULT FALSE,
    error_trace             TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ee_audit_company ON email_discovery_audit(company_id);
CREATE INDEX IF NOT EXISTS idx_ee_audit_domain ON email_discovery_audit(target_domain);
CREATE INDEX IF NOT EXISTS idx_ee_audit_created ON email_discovery_audit(created_at DESC);

