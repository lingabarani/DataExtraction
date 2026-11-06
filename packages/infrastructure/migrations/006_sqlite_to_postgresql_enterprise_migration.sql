-- =============================================================================
-- Migration 006: Complete SQLite-to-PostgreSQL Enterprise Migration
-- =============================================================================
-- Replaces all local SQLite scraper files (gmaps.sqlite, osm_state_progress.db,
-- oneextraction.db) with production PostgreSQL 18 enterprise tables.
--
-- Features:
--   - 5-Layer MDM Architecture (raw, staging, resolution, master, search)
--   - Distributed worker task leasing with FOR UPDATE SKIP LOCKED
--   - High-throughput batch upserts with ON CONFLICT DO UPDATE
--   - Full auditability, Dead Letter Queues, and lease recovery
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- Establish Enterprise Schemas
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS resolution;
CREATE SCHEMA IF NOT EXISTS master;
CREATE SCHEMA IF NOT EXISTS search;

-- =============================================================================
-- 1. STAGING: GOOGLE MAPS SCRAPER TABLES
-- =============================================================================

-- Scraper Jobs: Lifecycle tracking for extraction runs
CREATE TABLE IF NOT EXISTS staging.scraper_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type VARCHAR(50) NOT NULL, -- 'GMAPS_COLLECTION', 'WEBSITE_VERIFY', 'ENRICHMENT'
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING', -- PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    target_country VARCHAR(10) NOT NULL,
    target_region VARCHAR(100),
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    total_tiles INT NOT NULL DEFAULT 0,
    completed_tiles INT NOT NULL DEFAULT 0,
    failed_tiles INT NOT NULL DEFAULT 0,
    records_collected INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraper_jobs_status ON staging.scraper_jobs (status, created_at DESC);

-- Scraper Tiles: Spatial quadtree bounding box partitions with distributed worker leases
CREATE TABLE IF NOT EXISTS staging.scraper_tiles (
    tile_id VARCHAR(100) PRIMARY KEY, -- e.g., 'US_CA_z14_x2671_y6328'
    job_id UUID REFERENCES staging.scraper_jobs(job_id) ON DELETE SET NULL,
    country_code VARCHAR(10) NOT NULL,
    region VARCHAR(100) NOT NULL,
    min_lat NUMERIC(10,7) NOT NULL,
    max_lat NUMERIC(10,7) NOT NULL,
    min_lng NUMERIC(10,7) NOT NULL,
    max_lng NUMERIC(10,7) NOT NULL,
    priority INT NOT NULL DEFAULT 100,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING', -- PENDING, LEASED, COMPLETED, FAILED
    worker_id VARCHAR(100),
    lease_expires_at TIMESTAMPTZ,
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    last_error TEXT,
    records_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Distributed claiming index for SKIP LOCKED queries
CREATE INDEX IF NOT EXISTS idx_scraper_tiles_claiming ON staging.scraper_tiles (status, priority DESC, lease_expires_at)
WHERE status IN ('PENDING', 'FAILED');
CREATE INDEX IF NOT EXISTS idx_scraper_tiles_region ON staging.scraper_tiles (country_code, region);

-- Scraper Results: Raw extracted places buffer
CREATE TABLE IF NOT EXISTS staging.scraper_results (
    cid VARCHAR(50) PRIMARY KEY, -- Google Customer ID / Unique place key
    tile_id VARCHAR(100) REFERENCES staging.scraper_tiles(tile_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    category TEXT,
    vertical TEXT,
    vertical_raw TEXT,
    phone VARCHAR(50),
    phone_e164 VARCHAR(50),
    website_url TEXT,
    normalized_domain VARCHAR(255),
    street_address TEXT,
    city TEXT,
    state_code VARCHAR(10),
    country_code VARCHAR(10),
    postal_code VARCHAR(20),
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    rating NUMERIC(3,2),
    review_count INT NOT NULL DEFAULT 0,
    timezone VARCHAR(50),
    claimed_status INT NOT NULL DEFAULT 0,
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_processed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraper_results_domain ON staging.scraper_results (normalized_domain) WHERE normalized_domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_scraper_results_unprocessed ON staging.scraper_results (is_processed) WHERE is_processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_scraper_results_geo ON staging.scraper_results (city, state_code, country_code);

-- Job Events: Audit telemetry for scraper execution runs
CREATE TABLE IF NOT EXISTS staging.scraper_job_events (
    event_id BIGSERIAL PRIMARY KEY,
    job_id UUID REFERENCES staging.scraper_jobs(job_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL, -- 'TILE_STARTED', 'TILE_COMPLETED', 'ERROR', 'HEARTBEAT'
    worker_id VARCHAR(100),
    message TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scraper_job_events_job ON staging.scraper_job_events (job_id, created_at DESC);

-- =============================================================================
-- 2. STAGING: OPENSTREETMAP (OSM) DISTRIBUTED TRACKER
-- =============================================================================

-- OSM Chunks: Spatial quadtree chunks for state-by-state extraction
CREATE TABLE IF NOT EXISTS staging.osm_chunks (
    state_name VARCHAR(100) NOT NULL,
    field_name VARCHAR(50) NOT NULL,
    chunk_id VARCHAR(100) NOT NULL,
    parent_id VARCHAR(100),
    depth INT NOT NULL DEFAULT 0,
    min_lat NUMERIC(10,7) NOT NULL,
    min_lon NUMERIC(10,7) NOT NULL,
    max_lat NUMERIC(10,7) NOT NULL,
    max_lon NUMERIC(10,7) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING', -- PENDING, LEASED, COMPLETED, FAILED, SPLIT
    worker_id VARCHAR(100),
    lease_expires_at TIMESTAMPTZ,
    records_count INT NOT NULL DEFAULT 0,
    raw_s3_key TEXT,
    proc_s3_key TEXT,
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (state_name, field_name, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_osm_chunks_claim ON staging.osm_chunks (status, lease_expires_at)
WHERE status IN ('PENDING', 'FAILED');

-- OSM Progress: Aggregate extraction status per state and tag family
CREATE TABLE IF NOT EXISTS staging.osm_progress (
    state_name VARCHAR(100) NOT NULL,
    field_name VARCHAR(50) NOT NULL,
    total_chunks INT NOT NULL DEFAULT 0,
    completed_chunks INT NOT NULL DEFAULT 0,
    failed_chunks INT NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (state_name, field_name)
);

-- OSM Retry Queue: Dead Letter Queue for rate-limited Overpass chunks
CREATE TABLE IF NOT EXISTS staging.osm_retry_queue (
    retry_id BIGSERIAL PRIMARY KEY,
    state_name VARCHAR(100) NOT NULL,
    field_name VARCHAR(50) NOT NULL,
    chunk_id VARCHAR(100) NOT NULL,
    attempts INT NOT NULL DEFAULT 1,
    last_error TEXT,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING', -- PENDING, RESOLVED, DEAD_LETTER
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_osm_retry_chunk FOREIGN KEY (state_name, field_name, chunk_id)
        REFERENCES staging.osm_chunks (state_name, field_name, chunk_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_osm_retry_pending ON staging.osm_retry_queue (status, next_retry_at)
WHERE status = 'PENDING';

-- =============================================================================
-- 3. STAGING: BOTASAURUS WEB SCRAPER STAGING BUFFERS
-- =============================================================================

CREATE TABLE IF NOT EXISTS staging.staging_companies (
    id VARCHAR(100) PRIMARY KEY,
    name TEXT NOT NULL,
    legal_name TEXT,
    website TEXT,
    domain VARCHAR(255),
    email TEXT,
    phone TEXT,
    city TEXT,
    state TEXT,
    state_code VARCHAR(10),
    zip_code TEXT,
    country TEXT DEFAULT 'United States',
    industry TEXT,
    naics_code TEXT,
    ein TEXT,
    cik TEXT,
    employee_min INT,
    employee_max INT,
    employee_band TEXT,
    source VARCHAR(100),
    data_quality_score INT DEFAULT 0,
    raw_payload JSONB DEFAULT '{}'::jsonb,
    is_migrated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stg_comp_domain ON staging.staging_companies (domain) WHERE domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stg_comp_unmigrated ON staging.staging_companies (is_migrated) WHERE is_migrated = FALSE;

CREATE TABLE IF NOT EXISTS staging.staging_people (
    id VARCHAR(100) PRIMARY KEY,
    company_id VARCHAR(100),
    first_name TEXT,
    last_name TEXT,
    full_name TEXT,
    title TEXT,
    standardized_title TEXT,
    seniority_level VARCHAR(50),
    department VARCHAR(50),
    work_email TEXT,
    city TEXT,
    state TEXT,
    state_code VARCHAR(10),
    country TEXT DEFAULT 'United States',
    email_status VARCHAR(50) DEFAULT 'UNKNOWN',
    email_confidence_score NUMERIC(4,2),
    is_active BOOLEAN DEFAULT TRUE,
    source VARCHAR(100),
    raw_payload JSONB DEFAULT '{}'::jsonb,
    is_migrated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stg_ppl_email ON staging.staging_people (work_email) WHERE work_email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stg_ppl_unmigrated ON staging.staging_people (is_migrated) WHERE is_migrated = FALSE;

CREATE TABLE IF NOT EXISTS staging.staging_enrichment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id VARCHAR(100),
    email TEXT,
    email_verified BOOLEAN DEFAULT FALSE,
    email_status VARCHAR(50) DEFAULT 'UNKNOWN',
    tech_stack TEXT[] DEFAULT '{}',
    industry_classified TEXT,
    health_score SMALLINT,
    ai_summary TEXT,
    is_migrated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stg_enrich_comp ON staging.staging_enrichment (company_id);

-- =============================================================================
-- 4. RAW LAYER: APPEND-ONLY IMMUTABLE STREAM
-- =============================================================================

CREATE TABLE IF NOT EXISTS raw.scraper_payloads (
    payload_id UUID DEFAULT gen_random_uuid(),
    source_name VARCHAR(50) NOT NULL, -- 'GMAPS', 'OSM', 'SEC_EDGAR', 'CMS_NPI'
    natural_key VARCHAR(255) NOT NULL,
    raw_body TEXT NOT NULL,
    s3_url TEXT,
    payload_hash CHAR(64) NOT NULL, -- SHA-256
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (payload_id, ingested_at)
) PARTITION BY RANGE (ingested_at);

-- Quarterly partitions for raw storage
CREATE TABLE IF NOT EXISTS raw.scraper_payloads_2026_q4 PARTITION OF raw.scraper_payloads
    FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');

CREATE TABLE IF NOT EXISTS raw.scraper_payloads_2027_q1 PARTITION OF raw.scraper_payloads
    FOR VALUES FROM ('2027-01-01') TO ('2027-04-01');

CREATE INDEX IF NOT EXISTS idx_raw_payloads_hash ON raw.scraper_payloads (payload_hash);
CREATE INDEX IF NOT EXISTS idx_raw_payloads_lookup ON raw.scraper_payloads (source_name, natural_key, ingested_at DESC);
