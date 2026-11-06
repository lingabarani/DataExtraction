-- =============================================================================
-- Migration 007: Enterprise Schema Layer Standardization
-- =============================================================================
-- Transitions internal schemas to exact enterprise MDM layers without `_db` suffix:
--   1. raw                   -> raw_dataextraction
--   2. staging               -> staging_dataextraction
--   3. kg_resolution         -> identity_resolution
--   4. kg_core               -> master_dataextraction
--   5. kg_search             -> search_dataextraction
--
-- Features:
--   - Zero-copy atomic table relocation (ALTER TABLE ... SET SCHEMA)
--   - Updatable backward-compatible SQL views in legacy schemas
--   - Default search_path configured on database
--   - Full idempotency (IF EXISTS guards)
-- =============================================================================

-- 1. Create Target Schemas
CREATE SCHEMA IF NOT EXISTS raw_dataextraction;
CREATE SCHEMA IF NOT EXISTS staging_dataextraction;
CREATE SCHEMA IF NOT EXISTS identity_resolution;
CREATE SCHEMA IF NOT EXISTS master_dataextraction;
CREATE SCHEMA IF NOT EXISTS search_dataextraction;

-- 2. Configure Default Search Path
ALTER DATABASE dataextraction SET search_path TO 
    staging_dataextraction, 
    master_dataextraction, 
    identity_resolution, 
    raw_dataextraction, 
    search_dataextraction, 
    public;

-- 3. Grant Permissions
GRANT USAGE, CREATE ON SCHEMA raw_dataextraction TO PUBLIC;
GRANT USAGE, CREATE ON SCHEMA staging_dataextraction TO PUBLIC;
GRANT USAGE, CREATE ON SCHEMA identity_resolution TO PUBLIC;
GRANT USAGE, CREATE ON SCHEMA master_dataextraction TO PUBLIC;
GRANT USAGE, CREATE ON SCHEMA search_dataextraction TO PUBLIC;

