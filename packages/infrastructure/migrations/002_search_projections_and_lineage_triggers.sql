-- ============================================================================
-- DataExtraction: Migration 002 — Search Projections, CDC & Bayesian Quality Triggers
-- ============================================================================
-- Adds:
--   1. kg_search.person_search_projection (OpenSearch People Index Projection)
--   2. kg_search.cdc_watermarks (Change Data Capture Stream Checkpoint Tracking)
--   3. kg_search.fn_trg_sync_company_projection & Triggers (Automated CDC projection)
--   4. kg_quality.fn_compute_bayesian_quality_score (Bayesian Multi-Source Scoring)
--   5. kg_quality.fn_trg_recalculate_org_quality (Automated Score Recalculation)
--   6. High-Performance Watermark & CDC Delta Indexes
-- ============================================================================

-- 1. PERSON SEARCH PROJECTION (OpenSearch 2.x People Index)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_search.person_search_projection (
    person_id UUID PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    primary_linkedin_url VARCHAR(500),
    primary_email VARCHAR(255),
    email_deliverability VARCHAR(50) DEFAULT 'untested',
    current_primary_org_id UUID,
    current_org_name VARCHAR(500),
    current_primary_title VARCHAR(255),
    seniority_level VARCHAR(50),
    department VARCHAR(100),
    career_history JSONB NOT NULL DEFAULT '[]',
    quality_score SMALLINT NOT NULL DEFAULT 80,
    sync_version BIGINT NOT NULL DEFAULT 1,
    last_projected_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

-- 2. CDC WATERMARKS (Change Data Capture Checkpoints)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_search.cdc_watermarks (
    consumer_id VARCHAR(100) PRIMARY KEY, -- 'opensearch_companies_v1', 'opensearch_people_v1'
    last_synced_version BIGINT NOT NULL DEFAULT 0,
    last_synced_timestamp TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01 00:00:00+00',
    records_synced_total BIGINT NOT NULL DEFAULT 0,
    last_sync_duration_ms INT,
    last_status VARCHAR(50) NOT NULL DEFAULT 'SUCCESS',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

-- 3. BAYESIAN DATA QUALITY SCORING FUNCTION
-- ============================================================================
CREATE OR REPLACE FUNCTION kg_quality.fn_compute_bayesian_quality_score(
    p_has_tax_id BOOLEAN,
    p_has_domain BOOLEAN,
    p_has_verified_email BOOLEAN,
    p_has_phone BOOLEAN,
    p_has_location BOOLEAN,
    p_corroborating_sources INT
) RETURNS SMALLINT AS $$
DECLARE
    v_score INT := 50; -- Prior baseline confidence
BEGIN
    IF p_has_tax_id THEN
        v_score := v_score + 20; -- Deterministic statutory identity (EIN/RFC/LEI)
    END IF;
    IF p_has_domain THEN
        v_score := v_score + 10; -- Digital domain identity
    END IF;
    IF p_has_verified_email THEN
        v_score := v_score + 10; -- Validated deliverability
    END IF;
    IF p_has_phone THEN
        v_score := v_score + 5;
    END IF;
    IF p_has_location THEN
        v_score := v_score + 5;
    END IF;

    -- Bayesian Multi-Source Corroboration Boost
    IF p_corroborating_sources >= 3 THEN
        v_score := v_score + 15;
    ELSIF p_corroborating_sources = 2 THEN
        v_score := v_score + 10;
    ELSIF p_corroborating_sources = 1 THEN
        v_score := v_score + 5;
    END IF;

    RETURN LEAST(100, GREATEST(0, v_score))::SMALLINT;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- 4. QUALITY RECALCULATION TRIGGER FUNCTION
-- ============================================================================
CREATE OR REPLACE FUNCTION kg_quality.fn_trg_recalculate_org_quality()
RETURNS TRIGGER AS $$
DECLARE
    v_has_tax_id BOOLEAN;
    v_has_domain BOOLEAN;
    v_has_email BOOLEAN;
    v_has_phone BOOLEAN;
    v_has_location BOOLEAN := false;
    v_sources_count INT := 1;
BEGIN
    v_has_tax_id := (NEW.statutory_tax_id IS NOT NULL AND length(TRIM(NEW.statutory_tax_id)) >= 5);
    v_has_domain := (NEW.primary_domain IS NOT NULL AND length(TRIM(NEW.primary_domain)) >= 3);

    SELECT EXISTS(
        SELECT 1 FROM kg_core.contact_emails
        WHERE org_id = NEW.org_id AND deliverability_status = 'verified_deliverable'
    ) INTO v_has_email;

    SELECT EXISTS(
        SELECT 1 FROM kg_core.contact_phones
        WHERE org_id = NEW.org_id
    ) INTO v_has_phone;

    SELECT COUNT(DISTINCT source_name) INTO v_sources_count
    FROM kg_lineage.field_provenance
    WHERE entity_id = NEW.org_id;

    NEW.data_quality_score := kg_quality.fn_compute_bayesian_quality_score(
        v_has_tax_id,
        v_has_domain,
        v_has_email,
        v_has_phone,
        v_has_location,
        GREATEST(1, COALESCE(v_sources_count, 1))
    );

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_org_quality_score ON kg_core.organizations;
CREATE TRIGGER trg_org_quality_score
BEFORE INSERT OR UPDATE OF statutory_tax_id, primary_domain, legal_name ON kg_core.organizations
FOR EACH ROW
EXECUTE FUNCTION kg_quality.fn_trg_recalculate_org_quality();

-- 5. AUTOMATED PROJECTION SYNC TRIGGER FOR ORGANIZATIONS
-- ============================================================================
CREATE OR REPLACE FUNCTION kg_search.fn_trg_sync_company_projection()
RETURNS TRIGGER AS $$
DECLARE
    v_domains TEXT[];
    v_aliases TEXT[];
BEGIN
    SELECT COALESCE(ARRAY_AGG(domain_name), '{}') INTO v_domains
    FROM kg_core.organization_domains
    WHERE org_id = NEW.org_id;

    SELECT COALESCE(ARRAY_AGG(alias_name), '{}') INTO v_aliases
    FROM kg_core.organization_aliases
    WHERE org_id = NEW.org_id;

    INSERT INTO kg_search.company_search_projection (
        org_id, jurisdiction, legal_name, display_name, primary_domain,
        all_domains, all_aliases, industry_naics, quality_score, sync_version, last_projected_at
    ) VALUES (
        NEW.org_id, NEW.jurisdiction, NEW.legal_name, NEW.display_name, NEW.primary_domain,
        COALESCE(v_domains, '{}'), COALESCE(v_aliases, '{}'), NEW.primary_industry_naics,
        NEW.data_quality_score, 1, CLOCK_TIMESTAMP()
    )
    ON CONFLICT (org_id) DO UPDATE SET
        legal_name = EXCLUDED.legal_name,
        display_name = EXCLUDED.display_name,
        primary_domain = EXCLUDED.primary_domain,
        all_domains = CASE WHEN array_length(EXCLUDED.all_domains, 1) > 0 THEN EXCLUDED.all_domains ELSE kg_search.company_search_projection.all_domains END,
        all_aliases = CASE WHEN array_length(EXCLUDED.all_aliases, 1) > 0 THEN EXCLUDED.all_aliases ELSE kg_search.company_search_projection.all_aliases END,
        industry_naics = EXCLUDED.industry_naics,
        quality_score = EXCLUDED.quality_score,
        sync_version = kg_search.company_search_projection.sync_version + 1,
        last_projected_at = CLOCK_TIMESTAMP();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_org_search_projection ON kg_core.organizations;
CREATE TRIGGER trg_org_search_projection
AFTER INSERT OR UPDATE ON kg_core.organizations
FOR EACH ROW
EXECUTE FUNCTION kg_search.fn_trg_sync_company_projection();

-- 6. HIGH-PERFORMANCE WATERMARK & CDC INDEXES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_proj_company_sync ON kg_search.company_search_projection (last_projected_at, sync_version);
CREATE INDEX IF NOT EXISTS idx_proj_person_sync ON kg_search.person_search_projection (last_projected_at, sync_version);
CREATE INDEX IF NOT EXISTS idx_lineage_entity_field ON kg_lineage.field_provenance (entity_id, field_name);
CREATE INDEX IF NOT EXISTS idx_lineage_source ON kg_lineage.field_provenance (source_name);
