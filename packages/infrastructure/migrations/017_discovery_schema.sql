-- ==============================================================================
-- Migration: 017_discovery_schema.sql
-- Description: Unified discovery schema for cross-source entity search & enrichment.
-- Schema: discovery_dataextraction
-- Idempotent: safe to run multiple times.
-- ==============================================================================

CREATE SCHEMA IF NOT EXISTS discovery_dataextraction;

-- Try enable pg_trgm extension if permissions allow
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pg_trgm extension could not be enabled; using standard B-tree / GIN indexes instead';
END $$;

-- ------------------------------------------------------------------------------
-- 1. Organizations table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovery_dataextraction.organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    category TEXT,
    subcategories JSONB DEFAULT '[]'::jsonb,
    address_street TEXT,
    address_city TEXT,
    address_state TEXT,
    address_postal_code TEXT,
    address_country TEXT DEFAULT 'US',
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    phones JSONB DEFAULT '[]'::jsonb,
    emails JSONB DEFAULT '[]'::jsonb,
    website TEXT,
    domain TEXT,
    hours JSONB DEFAULT '[]'::jsonb,
    rating NUMERIC(3, 2),
    review_count INTEGER DEFAULT 0,
    services JSONB DEFAULT '[]'::jsonb,
    regulatory JSONB DEFAULT '{}'::jsonb,
    social JSONB DEFAULT '{}'::jsonb,
    linked_place_id TEXT,
    linked_company_id TEXT,
    quality_score REAL DEFAULT 0.5,
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(canonical_name, '') || ' ' ||
            coalesce(category, '') || ' ' ||
            coalesce(address_city, '') || ' ' ||
            coalesce(address_state, '')
        )
    ) STORED
);

-- ------------------------------------------------------------------------------
-- 2. People table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovery_dataextraction.people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    title TEXT,
    role_type TEXT,
    org_id UUID REFERENCES discovery_dataextraction.organizations(id) ON DELETE SET NULL,
    org_name TEXT,
    headline TEXT,
    city TEXT,
    region TEXT,
    country TEXT DEFAULT 'US',
    profile_urls JSONB DEFAULT '[]'::jsonb,
    emails JSONB DEFAULT '[]'::jsonb,
    phones JSONB DEFAULT '[]'::jsonb,
    provenance TEXT DEFAULT 'discovery',
    verified BOOLEAN DEFAULT FALSE,
    suppressed BOOLEAN DEFAULT FALSE,
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english',
            coalesce(full_name, '') || ' ' ||
            coalesce(title, '') || ' ' ||
            coalesce(city, '') || ' ' ||
            coalesce(headline, '')
        )
    ) STORED
);

-- ------------------------------------------------------------------------------
-- 3. Facts provenance table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovery_dataextraction.facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    field TEXT NOT NULL,
    value JSONB NOT NULL,
    value_hash TEXT GENERATED ALWAYS AS (md5(value::text)) STORED,
    source TEXT NOT NULL,
    source_url TEXT,
    retrieved_at TIMESTAMPTZ DEFAULT NOW(),
    confidence REAL DEFAULT 0.8,
    CONSTRAINT uq_discovery_fact UNIQUE (entity_type, entity_id, field, source, value_hash)
);

-- ------------------------------------------------------------------------------
-- 4. Search runs & search results
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovery_dataextraction.search_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query TEXT NOT NULL,
    parsed JSONB DEFAULT '{}'::jsonb,
    status TEXT DEFAULT 'pending',
    timings JSONB DEFAULT '{}'::jsonb,
    source_status JSONB DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS discovery_dataextraction.search_results (
    run_id UUID NOT NULL REFERENCES discovery_dataextraction.search_runs(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    rank INTEGER NOT NULL,
    score REAL DEFAULT 0.0,
    PRIMARY KEY (run_id, entity_type, entity_id)
);

-- ------------------------------------------------------------------------------
-- 5. Discovery cache
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS discovery_dataextraction.discovery_cache (
    cache_key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    payload JSONB NOT NULL,
    etag TEXT,
    last_modified TEXT,
    content_hash TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- ------------------------------------------------------------------------------
-- 6. Indexes
-- ------------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_disc_org_norm_domain ON discovery_dataextraction.organizations (normalized_name, domain);
CREATE INDEX IF NOT EXISTS idx_disc_org_tsv ON discovery_dataextraction.organizations USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_disc_org_phones ON discovery_dataextraction.organizations USING gin(phones);
CREATE INDEX IF NOT EXISTS idx_disc_org_emails ON discovery_dataextraction.organizations USING gin(emails);
CREATE INDEX IF NOT EXISTS idx_disc_org_category ON discovery_dataextraction.organizations (category);

CREATE INDEX IF NOT EXISTS idx_disc_people_norm ON discovery_dataextraction.people (normalized_name);
CREATE INDEX IF NOT EXISTS idx_disc_people_org_id ON discovery_dataextraction.people (org_id);
CREATE INDEX IF NOT EXISTS idx_disc_people_not_suppressed ON discovery_dataextraction.people (id) WHERE NOT suppressed;
CREATE INDEX IF NOT EXISTS idx_disc_people_tsv ON discovery_dataextraction.people USING gin(tsv);

CREATE INDEX IF NOT EXISTS idx_disc_facts_entity ON discovery_dataextraction.facts (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_disc_cache_expires ON discovery_dataextraction.discovery_cache (expires_at);
CREATE INDEX IF NOT EXISTS idx_disc_cache_source ON discovery_dataextraction.discovery_cache (source);
