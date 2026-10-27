-- ============================================================================
-- DataExtraction Enterprise Knowledge Graph — Schema Migration 001
-- ============================================================================
-- Engine: PostgreSQL 16+
-- Modules:
--   1. Extensions & Schemas
--   2. Core Canonical Entities (Organizations, Persons, Locations, Tech)
--   3. Organization Aliases & Multi-Domain Infrastructure
--   4. Person Aliases & Contact Intelligence (Emails, Phones)
--   5. Temporal Graph Edges (Employment, Hierarchies, Tech Usage)
--   6. Lakehouse Observation Metadata (Parquet S3 Pointer Model)
--   7. Identity Resolution & Reversible Cluster Graph (Splink Support)
--   8. Field-Level Lineage & Provenance
--   9. Search Projections (Debezium CDC to OpenSearch)
--  10. Governance, Audit & PII Suppression (GDPR / CCPA)
-- ============================================================================

-- 1. EXTENSIONS & SCHEMAS
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "btree_gist";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS "postgis";
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'PostGIS extension not available in this environment, geospatial functions will use fallback geometry/coordinates.';
END $$;

CREATE SCHEMA IF NOT EXISTS kg_core;
CREATE SCHEMA IF NOT EXISTS kg_graph;
CREATE SCHEMA IF NOT EXISTS kg_observation;
CREATE SCHEMA IF NOT EXISTS kg_resolution;
CREATE SCHEMA IF NOT EXISTS kg_lineage;
CREATE SCHEMA IF NOT EXISTS kg_quality;
CREATE SCHEMA IF NOT EXISTS kg_search;
CREATE SCHEMA IF NOT EXISTS kg_audit;

-- 2. DOMAIN ENUMS
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'entity_status' AND typnamespace = 'kg_core'::regnamespace) THEN
        CREATE TYPE kg_core.entity_status AS ENUM ('active', 'inactive', 'dissolved', 'merged', 'disputed');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'jurisdiction_code' AND typnamespace = 'kg_core'::regnamespace) THEN
        CREATE TYPE kg_core.jurisdiction_code AS ENUM ('US', 'MX', 'CA', 'GLOBAL');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'alias_type' AND typnamespace = 'kg_core'::regnamespace) THEN
        CREATE TYPE kg_core.alias_type AS ENUM ('legal_name', 'dba', 'trade_name', 'former_name', 'acronym', 'local_translation');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'domain_type' AND typnamespace = 'kg_core'::regnamespace) THEN
        CREATE TYPE kg_core.domain_type AS ENUM ('primary_web', 'secondary_redirect', 'email_only', 'brand_subdomain', 'regional_cctld');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'email_type' AND typnamespace = 'kg_core'::regnamespace) THEN
        CREATE TYPE kg_core.email_type AS ENUM ('work_direct', 'work_general', 'personal', 'role_based');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'deliverability_status' AND typnamespace = 'kg_core'::regnamespace) THEN
        CREATE TYPE kg_core.deliverability_status AS ENUM ('verified_deliverable', 'risky_catchall', 'undeliverable_bounced', 'disposable_blocked', 'untested');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'phone_line_type' AND typnamespace = 'kg_core'::regnamespace) THEN
        CREATE TYPE kg_core.phone_line_type AS ENUM ('mobile', 'landline', 'voip', 'toll_free', 'unknown');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'employment_type' AND typnamespace = 'kg_graph'::regnamespace) THEN
        CREATE TYPE kg_graph.employment_type AS ENUM ('full_time', 'part_time', 'contractor', 'founder', 'board_member', 'advisor', 'intern');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hierarchy_type' AND typnamespace = 'kg_graph'::regnamespace) THEN
        CREATE TYPE kg_graph.hierarchy_type AS ENUM ('ultimate_parent', 'immediate_parent', 'subsidiary', 'branch', 'division', 'joint_venture');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'match_type' AND typnamespace = 'kg_resolution'::regnamespace) THEN
        CREATE TYPE kg_resolution.match_type AS ENUM ('deterministic_tax_id', 'deterministic_domain', 'probabilistic_splink', 'graph_transitive', 'manual_override');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'cluster_status' AND typnamespace = 'kg_resolution'::regnamespace) THEN
        CREATE TYPE kg_resolution.cluster_status AS ENUM ('stable', 'provisional', 'quarantined', 'split_pending');
    END IF;
END $$;

-- ============================================================================
-- 3. KG_CORE: CANONICAL ORGANIZATIONS (Partitioned by Jurisdiction)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_core.organizations (
    org_id UUID NOT NULL DEFAULT gen_random_uuid(),
    jurisdiction kg_core.jurisdiction_code NOT NULL,
    legal_name VARCHAR(500) NOT NULL,
    display_name VARCHAR(500),
    primary_domain VARCHAR(255),
    statutory_tax_id VARCHAR(50),      -- EIN (US), RFC (MX), BN (CA)
    sec_cik VARCHAR(10),
    gleif_lei VARCHAR(20),
    duns_number VARCHAR(9),
    entity_status kg_core.entity_status NOT NULL DEFAULT 'active',
    incorporation_date DATE,
    dissolution_date DATE,
    primary_industry_naics VARCHAR(6),
    primary_industry_sic VARCHAR(4),
    employee_count_min INT,
    employee_count_max INT,
    annual_revenue_usd NUMERIC(15,2),
    total_funding_usd NUMERIC(15,2),
    data_quality_score SMALLINT CHECK (data_quality_score BETWEEN 0 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (org_id, jurisdiction)
) PARTITION BY LIST (jurisdiction);

CREATE TABLE IF NOT EXISTS kg_core.organizations_us PARTITION OF kg_core.organizations FOR VALUES IN ('US');
CREATE TABLE IF NOT EXISTS kg_core.organizations_mx PARTITION OF kg_core.organizations FOR VALUES IN ('MX');
CREATE TABLE IF NOT EXISTS kg_core.organizations_ca PARTITION OF kg_core.organizations FOR VALUES IN ('CA');
CREATE TABLE IF NOT EXISTS kg_core.organizations_global PARTITION OF kg_core.organizations FOR VALUES IN ('GLOBAL');

-- ============================================================================
-- 4. KG_CORE: ORGANIZATION ALIASES & MULTI-DOMAIN INFRASTRUCTURE
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_core.organization_aliases (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    jurisdiction kg_core.jurisdiction_code NOT NULL,
    alias_name VARCHAR(500) NOT NULL,
    alias_type kg_core.alias_type NOT NULL,
    clean_name VARCHAR(500) NOT NULL,
    soundex_code VARCHAR(10),
    dmetaphone_code VARCHAR(20),
    valid_from DATE,
    valid_to DATE,
    confidence_score NUMERIC(4,3) DEFAULT 1.000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    CONSTRAINT fk_alias_org FOREIGN KEY (org_id, jurisdiction) 
        REFERENCES kg_core.organizations (org_id, jurisdiction) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS kg_core.organization_domains (
    domain_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    jurisdiction kg_core.jurisdiction_code NOT NULL,
    domain_name VARCHAR(255) NOT NULL,
    domain_type kg_core.domain_type NOT NULL DEFAULT 'primary_web',
    is_primary BOOLEAN NOT NULL DEFAULT false,
    has_active_dns BOOLEAN NOT NULL DEFAULT true,
    has_active_mx BOOLEAN NOT NULL DEFAULT true,
    ssl_certified BOOLEAN NOT NULL DEFAULT true,
    http_status_code INT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    last_verified_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    CONSTRAINT fk_domain_org FOREIGN KEY (org_id, jurisdiction) 
        REFERENCES kg_core.organizations (org_id, jurisdiction) ON DELETE CASCADE,
    CONSTRAINT uq_org_domain UNIQUE (org_id, domain_name)
);

-- ============================================================================
-- 5. KG_CORE: CANONICAL PERSONS & ALIASES (Hash Partitioned Across 32 Shards)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_core.persons (
    person_id UUID NOT NULL DEFAULT gen_random_uuid(),
    full_name VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    middle_name VARCHAR(100),
    primary_linkedin_url VARCHAR(500),
    primary_email VARCHAR(255),
    primary_phone_e164 VARCHAR(20),
    current_primary_org_id UUID,
    current_primary_title VARCHAR(255),
    seniority_level VARCHAR(50),
    department VARCHAR(100),
    country_code VARCHAR(2),
    data_quality_score SMALLINT CHECK (data_quality_score BETWEEN 0 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (person_id)
) PARTITION BY HASH (person_id);

DO $$
BEGIN
    FOR i IN 0..31 LOOP
        EXECUTE format('CREATE TABLE IF NOT EXISTS kg_core.persons_p%s PARTITION OF kg_core.persons FOR VALUES WITH (MODULUS 32, REMAINDER %s);', i, i);
    END LOOP;
END $$;

CREATE TABLE IF NOT EXISTS kg_core.person_aliases (
    alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL,
    alias_name VARCHAR(255) NOT NULL,
    alias_type VARCHAR(50) NOT NULL,      -- maiden_name, former_legal, transliteration, nickname
    source_attribution VARCHAR(100) NOT NULL,
    confidence_score NUMERIC(4,3) DEFAULT 1.000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

-- ============================================================================
-- 6. KG_CORE: CONTACT INTELLIGENCE (EMAILS & PHONES)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_core.contact_emails (
    email_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_address VARCHAR(255) NOT NULL UNIQUE,
    normalized_domain VARCHAR(255) NOT NULL,
    person_id UUID,
    org_id UUID,
    email_type kg_core.email_type NOT NULL DEFAULT 'work_direct',
    deliverability_status kg_core.deliverability_status NOT NULL DEFAULT 'untested',
    deliverability_score SMALLINT CHECK (deliverability_score BETWEEN 0 AND 100),
    is_catch_all BOOLEAN NOT NULL DEFAULT false,
    is_disposable BOOLEAN NOT NULL DEFAULT false,
    mx_provider VARCHAR(100),            -- Google Workspace, Microsoft 365, Proofpoint
    smtp_handshake_code INT,             -- 250, 451, 550
    last_verified_at TIMESTAMPTZ,
    bounce_count SMALLINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS kg_core.contact_phones (
    phone_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone_e164 VARCHAR(20) NOT NULL,
    country_code VARCHAR(4) NOT NULL,    -- +1, +52
    national_number VARCHAR(15) NOT NULL,
    person_id UUID,
    org_id UUID,
    line_type kg_core.phone_line_type NOT NULL DEFAULT 'unknown',
    carrier_name VARCHAR(100),           -- Verizon Wireless, AT&T, Telcel, Movistar
    is_active_line BOOLEAN,
    is_ported BOOLEAN,
    is_dnc_registered BOOLEAN NOT NULL DEFAULT false, -- National Do Not Call list
    confidence_score NUMERIC(4,3) DEFAULT 0.800,
    last_validated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

-- ============================================================================
-- 7. KG_CORE: LOCATIONS & TECHNOLOGIES
-- ============================================================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'postgis') THEN
        CREATE TABLE IF NOT EXISTS kg_core.locations (
            location_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            raw_address TEXT NOT NULL,
            formatted_address TEXT NOT NULL,
            street_number VARCHAR(50),
            route VARCHAR(255),
            locality VARCHAR(255),
            administrative_area_level_1 VARCHAR(100),
            administrative_area_level_2 VARCHAR(100),
            postal_code VARCHAR(20),
            country_code VARCHAR(2) NOT NULL,
            geom GEOMETRY(Point, 4326),
            geocoding_precision VARCHAR(50),
            osm_place_id BIGINT,
            google_place_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
        );
    ELSE
        CREATE TABLE IF NOT EXISTS kg_core.locations (
            location_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            raw_address TEXT NOT NULL,
            formatted_address TEXT NOT NULL,
            street_number VARCHAR(50),
            route VARCHAR(255),
            locality VARCHAR(255),
            administrative_area_level_1 VARCHAR(100),
            administrative_area_level_2 VARCHAR(100),
            postal_code VARCHAR(20),
            country_code VARCHAR(2) NOT NULL,
            latitude NUMERIC(10,7),
            longitude NUMERIC(10,7),
            geocoding_precision VARCHAR(50),
            osm_place_id BIGINT,
            google_place_id VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS kg_core.technologies (
    tech_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(100) NOT NULL,
    parent_company VARCHAR(255),
    slug VARCHAR(100) NOT NULL UNIQUE
);

-- ============================================================================
-- 8. KG_GRAPH: TEMPORAL EMPLOYMENT & HIERARCHIES (Range Partitioned)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_graph.employment_relationships (
    employment_id UUID NOT NULL DEFAULT gen_random_uuid(),
    person_id UUID NOT NULL,
    org_id UUID NOT NULL,
    title VARCHAR(255) NOT NULL,
    normalized_title VARCHAR(255),
    department VARCHAR(100),
    seniority_level VARCHAR(50),
    relationship_type kg_graph.employment_type NOT NULL DEFAULT 'full_time',
    is_current BOOLEAN NOT NULL DEFAULT true,
    valid_from DATE NOT NULL,
    valid_to DATE,
    confidence_score NUMERIC(4,3) CHECK (confidence_score BETWEEN 0 AND 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (employment_id, valid_from)
) PARTITION BY RANGE (valid_from);

CREATE TABLE IF NOT EXISTS kg_graph.employment_pre_2020 PARTITION OF kg_graph.employment_relationships FOR VALUES FROM ('1970-01-01') TO ('2020-01-01');
CREATE TABLE IF NOT EXISTS kg_graph.employment_2020_2022 PARTITION OF kg_graph.employment_relationships FOR VALUES FROM ('2020-01-01') TO ('2023-01-01');
CREATE TABLE IF NOT EXISTS kg_graph.employment_2023_2025 PARTITION OF kg_graph.employment_relationships FOR VALUES FROM ('2023-01-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS kg_graph.employment_future PARTITION OF kg_graph.employment_relationships FOR VALUES FROM ('2026-01-01') TO ('2035-01-01');

CREATE TABLE IF NOT EXISTS kg_graph.corporate_hierarchies (
    hierarchy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_org_id UUID NOT NULL,
    child_org_id UUID NOT NULL,
    hierarchy_type kg_graph.hierarchy_type NOT NULL,
    ownership_percentage NUMERIC(5,2) CHECK (ownership_percentage BETWEEN 0 AND 100),
    direct_parent BOOLEAN NOT NULL DEFAULT true,
    valid_from DATE NOT NULL,
    valid_to DATE,
    confidence_score NUMERIC(4,3) CHECK (confidence_score BETWEEN 0 AND 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    CONSTRAINT chk_no_self_parenting CHECK (parent_org_id <> child_org_id)
);

CREATE TABLE IF NOT EXISTS kg_graph.org_technologies (
    org_tech_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    tech_id UUID NOT NULL REFERENCES kg_core.technologies(tech_id),
    first_detected_at TIMESTAMPTZ NOT NULL,
    last_detected_at TIMESTAMPTZ NOT NULL,
    detection_method VARCHAR(100),
    confidence_score NUMERIC(4,3) CHECK (confidence_score BETWEEN 0 AND 1),
    is_active BOOLEAN NOT NULL DEFAULT true,
    CONSTRAINT uq_org_tech UNIQUE (org_id, tech_id)
);

-- ============================================================================
-- 9. KG_OBSERVATION: LAKEHOUSE OBSERVATION METADATA (Parquet S3 Pointer Model)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_observation.observation_metadata (
    observation_id UUID NOT NULL DEFAULT gen_random_uuid(),
    source_name VARCHAR(100) NOT NULL,
    source_record_id VARCHAR(255) NOT NULL,
    observed_entity_type VARCHAR(50) NOT NULL,
    payload_hash_sha256 CHAR(64) NOT NULL,
    lakehouse_s3_uri VARCHAR(1024) NOT NULL, -- s3://data-lake/observations/source/2026/10/sha256.parquet
    extracted_summary JSONB NOT NULL,        -- Key indexed attributes only (< 2KB)
    observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (observation_id, ingested_at)
) PARTITION BY RANGE (ingested_at);

CREATE TABLE IF NOT EXISTS kg_observation.obs_meta_2026_q1 PARTITION OF kg_observation.observation_metadata FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS kg_observation.obs_meta_2026_q2 PARTITION OF kg_observation.observation_metadata FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
CREATE TABLE IF NOT EXISTS kg_observation.obs_meta_2026_q3 PARTITION OF kg_observation.observation_metadata FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
CREATE TABLE IF NOT EXISTS kg_observation.obs_meta_2026_q4 PARTITION OF kg_observation.observation_metadata FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');

-- ============================================================================
-- 10. KG_RESOLUTION: REVERSIBLE IDENTITY CLUSTERS (Splink Model)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_resolution.identity_clusters (
    cluster_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_entity_id UUID NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    status kg_resolution.cluster_status NOT NULL DEFAULT 'stable',
    cluster_entropy NUMERIC(5,4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS kg_resolution.cluster_members (
    member_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id UUID NOT NULL REFERENCES kg_resolution.identity_clusters(cluster_id) ON DELETE CASCADE,
    source_record_id VARCHAR(255) NOT NULL,
    source_name VARCHAR(100) NOT NULL,
    match_type kg_resolution.match_type NOT NULL,
    match_probability NUMERIC(5,4) NOT NULL CHECK (match_probability BETWEEN 0 AND 1),
    match_features JSONB NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS kg_resolution.unmerge_events (
    unmerge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_cluster_id UUID NOT NULL,
    new_cluster_id UUID NOT NULL,
    member_id UUID NOT NULL,
    reason TEXT NOT NULL,
    operator VARCHAR(100) NOT NULL,
    unmerged_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

-- ============================================================================
-- 11. KG_LINEAGE: FIELD-LEVEL ATTRIBUTION VECTOR
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_lineage.field_provenance (
    provenance_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    chosen_value TEXT NOT NULL,
    source_name VARCHAR(100) NOT NULL,
    observation_id UUID NOT NULL,
    authority_weight NUMERIC(3,2) NOT NULL,
    asserted_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    CONSTRAINT uq_entity_field UNIQUE (entity_id, field_name)
);

-- ============================================================================
-- 12. KG_SEARCH: CDC SEARCH PROJECTIONS (Materialized for OpenSearch 2.x)
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_search.company_search_projection (
    org_id UUID PRIMARY KEY,
    jurisdiction kg_core.jurisdiction_code NOT NULL,
    legal_name VARCHAR(500) NOT NULL,
    display_name VARCHAR(500),
    primary_domain VARCHAR(255),
    all_domains TEXT[] NOT NULL DEFAULT '{}',
    all_aliases TEXT[] NOT NULL DEFAULT '{}',
    industry_naics VARCHAR(6),
    employee_count INT,
    annual_revenue_usd NUMERIC(15,2),
    technologies TEXT[] NOT NULL DEFAULT '{}',
    current_leadership JSONB NOT NULL DEFAULT '[]',
    latitude NUMERIC(10,7),
    longitude NUMERIC(10,7),
    quality_score SMALLINT NOT NULL DEFAULT 80,
    sync_version BIGINT NOT NULL DEFAULT 1,
    last_projected_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP()
);

-- ============================================================================
-- 13. KG_AUDIT: COMPLIANCE & PII SUPPRESSION LISTS
-- ============================================================================
CREATE TABLE IF NOT EXISTS kg_audit.suppression_lists (
    suppression_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hashed_identifier CHAR(64) NOT NULL UNIQUE, -- SHA-256(email / phone / domain)
    identifier_type VARCHAR(50) NOT NULL,      -- email, phone, domain, individual
    reason VARCHAR(100) NOT NULL,              -- GDPR_FORGOTTEN, CCPA_OPT_OUT, DO_NOT_CALL
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    is_active BOOLEAN NOT NULL DEFAULT true
);

-- ============================================================================
-- 14. HIGH-PERFORMANCE INDEXES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_org_legal_name_trgm ON kg_core.organizations USING gin (legal_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_org_domain ON kg_core.organizations (primary_domain) WHERE primary_domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_org_tax_id ON kg_core.organizations (statutory_tax_id) WHERE statutory_tax_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_org_aliases_trgm ON kg_core.organization_aliases USING gin (alias_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_org_aliases_clean ON kg_core.organization_aliases (clean_name);
CREATE INDEX IF NOT EXISTS idx_org_domains_lookup ON kg_core.organization_domains (domain_name);

CREATE INDEX IF NOT EXISTS idx_persons_name_trgm ON kg_core.persons USING gin (full_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_emails_address ON kg_core.contact_emails (email_address);
CREATE INDEX IF NOT EXISTS idx_emails_deliverable ON kg_core.contact_emails (deliverability_status) WHERE deliverability_status = 'verified_deliverable';
CREATE INDEX IF NOT EXISTS idx_phones_e164 ON kg_core.contact_phones (phone_e164);

CREATE INDEX IF NOT EXISTS idx_emp_search_perf ON kg_graph.employment_relationships (org_id, is_current) INCLUDE (person_id, title);
CREATE INDEX IF NOT EXISTS idx_obs_lake_hash ON kg_observation.observation_metadata (source_name, payload_hash_sha256);
CREATE INDEX IF NOT EXISTS idx_suppression_hash ON kg_audit.suppression_lists (hashed_identifier) WHERE is_active = true;

