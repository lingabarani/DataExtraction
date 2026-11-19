-- =============================================================================
-- Migration 019: Website Intelligence, Review Checkpointing & Taxonomy Schema
-- =============================================================================
-- Idempotent schema enhancement supporting:
-- 1. Review extraction checkpointing and independent review analysis metadata.
-- 2. Hierarchical service taxonomy classification for Google Maps & websites.
-- 3. Dedicated Website Intelligence (Agent 8) verification & crawl tracking.
-- 4. Field-level cross-verification & conflict detection audit trail.
-- 5. Technology stack discovery tracking.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS staging_dataextraction;

-- ── 1. Enhance place_reviews for independent sentiment & topic analysis ────────
ALTER TABLE staging_dataextraction.place_reviews
    ADD COLUMN IF NOT EXISTS complaints JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS praise JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS frequently_mentioned_services JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS customer_experience_indicators JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS analysis_confidence NUMERIC(3,2),
    ADD COLUMN IF NOT EXISTS analysis_model TEXT,
    ADD COLUMN IF NOT EXISTS analyzed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_place_reviews_analyzed ON staging_dataextraction.place_reviews (analyzed_at);
CREATE INDEX IF NOT EXISTS idx_place_reviews_sentiment ON staging_dataextraction.place_reviews (sentiment);

-- ── 2. Enhance place_services for hierarchical taxonomy classification ────────
ALTER TABLE staging_dataextraction.place_services
    ADD COLUMN IF NOT EXISTS main_category TEXT,
    ADD COLUMN IF NOT EXISTS subcategory TEXT,
    ADD COLUMN IF NOT EXISTS price NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS currency VARCHAR(8),
    ADD COLUMN IF NOT EXISTS duration TEXT,
    ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS taxonomy_version TEXT;

CREATE INDEX IF NOT EXISTS idx_place_services_category ON staging_dataextraction.place_services (main_category, subcategory);

-- ── 3. place_review_checkpoints: crash-resilient pagination resumption ─────────
CREATE TABLE IF NOT EXISTS staging_dataextraction.place_review_checkpoints (
    place_id                TEXT PRIMARY KEY,
    next_pagination_token   TEXT,
    reviews_extracted       INTEGER NOT NULL DEFAULT 0,
    status                  VARCHAR(20) NOT NULL DEFAULT 'in_progress', -- in_progress | complete | blocked
    last_extracted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id                  TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_checkpoints_status ON staging_dataextraction.place_review_checkpoints (status);

-- ── 4. website_verifications: SSRF-safe domain verification results ────────────
CREATE TABLE IF NOT EXISTS staging_dataextraction.website_verifications (
    domain                  TEXT PRIMARY KEY,
    company_id              TEXT,
    place_id                TEXT,
    input_url               TEXT NOT NULL,
    final_url               TEXT,
    http_status             INTEGER,
    is_reachable            BOOLEAN NOT NULL DEFAULT FALSE,
    is_secure               BOOLEAN NOT NULL DEFAULT FALSE,
    has_ssl                 BOOLEAN NOT NULL DEFAULT FALSE,
    dns_resolves            BOOLEAN NOT NULL DEFAULT FALSE,
    ip_address              TEXT,
    response_time_ms        INTEGER,
    redirect_chain          JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_message           TEXT,
    verified_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_website_verifications_reachable ON staging_dataextraction.website_verifications (is_reachable);
CREATE INDEX IF NOT EXISTS idx_website_verifications_company ON staging_dataextraction.website_verifications (company_id);

-- ── 5. field_cross_verifications: field-level truth & conflict auditing ───────
CREATE TABLE IF NOT EXISTS staging_dataextraction.field_cross_verifications (
    id                      BIGSERIAL PRIMARY KEY,
    domain                  TEXT NOT NULL,
    company_id              TEXT,
    place_id                TEXT,
    field_name              TEXT NOT NULL, -- company_name | phone | address | city | state | postal_code | email
    original_value          TEXT,
    website_value           TEXT,
    status                  VARCHAR(24) NOT NULL DEFAULT 'UNVERIFIED', -- VERIFIED | CONFLICT | UNVERIFIED | NEW_DISCOVERY
    evidence_url            TEXT,
    evidence_snippet        TEXT,
    confidence              NUMERIC(3,2) NOT NULL DEFAULT 0.50,
    checked_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_field_cross_verification UNIQUE (domain, field_name, original_value, website_value)
);

CREATE INDEX IF NOT EXISTS idx_field_verifications_domain ON staging_dataextraction.field_cross_verifications (domain);
CREATE INDEX IF NOT EXISTS idx_field_verifications_status ON staging_dataextraction.field_cross_verifications (status);

-- ── 6. company_tech_stack: detected technology signatures ─────────────────────
CREATE TABLE IF NOT EXISTS staging_dataextraction.company_tech_stack (
    id                      BIGSERIAL PRIMARY KEY,
    domain                  TEXT NOT NULL,
    company_id              TEXT,
    place_id                TEXT,
    technology_name         TEXT NOT NULL,
    category                TEXT NOT NULL, -- CMS | Analytics | Ecommerce | Hosting | Framework | CRM | Marketing
    version                 TEXT,
    evidence_url            TEXT,
    confidence              NUMERIC(3,2) NOT NULL DEFAULT 0.80,
    detected_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_company_tech_stack UNIQUE (domain, technology_name)
);

CREATE INDEX IF NOT EXISTS idx_tech_stack_domain ON staging_dataextraction.company_tech_stack (domain);
CREATE INDEX IF NOT EXISTS idx_tech_stack_category ON staging_dataextraction.company_tech_stack (category);
