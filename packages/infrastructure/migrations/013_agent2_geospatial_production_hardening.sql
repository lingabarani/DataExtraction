-- Migration 013: Agent 2 (Geospatial & Domain Intelligence) Production Hardening
-- Covers:
--   P0-1: KG Lakehouse Outbox (pending_lakehouse_uploads)
--   P0-2: Durable GMaps Tile Checkpointing (raw_dataextraction.gmaps_tile_checkpoints)
--   P0-4: Partial expression indexes for staging_companies verify/crawl/validate queues,
--         worker lease column (geo_claim_until), unique place IDs on master_dataextraction.locations,
--         organization_locations bridge table, and osm_chunks claiming index.

-- 1. Worker claim lease column on staging_companies (nullable metadata-only DDL, instant in PG 11+)
ALTER TABLE staging_dataextraction.staging_companies
    ADD COLUMN IF NOT EXISTS geo_claim_until TIMESTAMPTZ;

-- 2. Partial expression indexes matching Agent 2 verification, crawling, and geo-validation hot queues
CREATE INDEX IF NOT EXISTS idx_stg_comp_geo_verify_queue
    ON staging_dataextraction.staging_companies (updated_at DESC)
    WHERE source IN ('GOOGLE_MAPS', 'OPENSTREETMAP')
      AND website IS NOT NULL
      AND TRIM(website) <> ''
      AND COALESCE(raw_payload->>'ssl_valid', '') = '';

CREATE INDEX IF NOT EXISTS idx_stg_comp_geo_crawl_queue
    ON staging_dataextraction.staging_companies (
        (CASE WHEN raw_payload->>'ssl_valid' = 'true' THEN 0 ELSE 1 END),
        updated_at DESC
    )
    WHERE source IN ('GOOGLE_MAPS', 'OPENSTREETMAP')
      AND website IS NOT NULL
      AND TRIM(website) <> ''
      AND COALESCE(raw_payload->>'crawled_at', '') = '';

CREATE INDEX IF NOT EXISTS idx_stg_comp_geo_validate_queue
    ON staging_dataextraction.staging_companies (updated_at DESC)
    WHERE source IN ('GOOGLE_MAPS', 'OPENSTREETMAP')
      AND COALESCE(raw_payload->>'geo_validated_at', '') = '';

CREATE INDEX IF NOT EXISTS idx_stg_comp_source_updated_at
    ON staging_dataextraction.staging_companies (source, updated_at DESC);

-- 3. Prevent duplicate locations on master_dataextraction.locations & add spatial/region indexes
-- Safely remove any legacy duplicate rows keeping the oldest location_id before enforcing UNIQUE
DELETE FROM master_dataextraction.locations a
USING master_dataextraction.locations b
WHERE a.google_place_id IS NOT NULL
  AND a.google_place_id = b.google_place_id
  AND a.ctid > b.ctid;

DELETE FROM master_dataextraction.locations a
USING master_dataextraction.locations b
WHERE a.osm_place_id IS NOT NULL
  AND a.osm_place_id = b.osm_place_id
  AND a.ctid > b.ctid;

CREATE UNIQUE INDEX IF NOT EXISTS uq_locations_google_place_id
    ON master_dataextraction.locations (google_place_id)
    WHERE google_place_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_locations_osm_place_id
    ON master_dataextraction.locations (osm_place_id)
    WHERE osm_place_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_locations_country_state
    ON master_dataextraction.locations (country_code, state_code, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_locations_lat_lon
    ON master_dataextraction.locations (latitude, longitude)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- 4. Bridge table linking staged/master organizations cleanly to canonical locations
CREATE TABLE IF NOT EXISTS master_dataextraction.organization_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_company_id VARCHAR(255) NOT NULL,
    org_id UUID,
    location_id UUID REFERENCES master_dataextraction.locations(location_id) ON DELETE CASCADE,
    source_system VARCHAR(64) NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT TRUE,
    confidence NUMERIC(4, 3) NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_company_id, location_id)
);

CREATE INDEX IF NOT EXISTS idx_org_locations_company
    ON master_dataextraction.organization_locations (source_company_id);

CREATE INDEX IF NOT EXISTS idx_org_locations_location
    ON master_dataextraction.organization_locations (location_id);

-- 5. OSM checkpoint claiming & progress indexes
CREATE INDEX IF NOT EXISTS idx_osm_chunks_claim
    ON staging_dataextraction.osm_chunks (state_name, field_name, status, lease_expires_at, chunk_id);

CREATE INDEX IF NOT EXISTS idx_osm_progress_status
    ON staging_dataextraction.osm_progress (status, updated_at DESC);

-- 6. Google Maps durable tile checkpoints (replaces fragile cross-worker SQLite dependence)
CREATE TABLE IF NOT EXISTS raw_dataextraction.gmaps_tile_checkpoints (
    tile_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    region_code TEXT NOT NULL,
    country_code TEXT NOT NULL,
    category TEXT NOT NULL,
    parent_tile_id TEXT,
    min_lat DOUBLE PRECISION NOT NULL,
    max_lat DOUBLE PRECISION NOT NULL,
    min_lng DOUBLE PRECISION NOT NULL,
    max_lng DOUBLE PRECISION NOT NULL,
    center_lat DOUBLE PRECISION NOT NULL,
    center_lng DOUBLE PRECISION NOT NULL,
    span_deg DOUBLE PRECISION NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    results_count INTEGER NOT NULL DEFAULT 0,
    pages_fetched INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    claim_until TIMESTAMPTZ,
    worker_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_gmaps_tile_ckpt_lookup
    ON raw_dataextraction.gmaps_tile_checkpoints (country_code, region_code, category, status, depth, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_gmaps_tile_ckpt_run
    ON raw_dataextraction.gmaps_tile_checkpoints (run_id, status);

-- 7. Knowledge Graph Lakehouse Outbox for graceful degradation & automated retry when MinIO/S3 is unavailable
CREATE TABLE IF NOT EXISTS kg_observation.pending_lakehouse_uploads (
    outbox_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    observation_id UUID,
    source_name VARCHAR(64) NOT NULL,
    source_record_id VARCHAR(255) NOT NULL,
    observed_entity_type VARCHAR(64) NOT NULL DEFAULT 'company',
    payload_json JSONB NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_hash_sha256 CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 10,
    next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    uploaded_at TIMESTAMPTZ,
    lakehouse_s3_uri VARCHAR(1024),
    UNIQUE (source_name, source_record_id, payload_hash_sha256)
);

CREATE INDEX IF NOT EXISTS idx_pending_lakehouse_retry
    ON kg_observation.pending_lakehouse_uploads (status, next_retry_at)
    WHERE status IN ('PENDING', 'FAILED');
