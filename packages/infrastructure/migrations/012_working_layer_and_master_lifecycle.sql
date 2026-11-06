-- ============================================================================
-- DataExtraction Migration 012: Pre-Master Working Layer & Master Freshness Lifecycle
-- ============================================================================
-- Establishes decoupled pre-master working canvas in staging_dataextraction
-- and adds lifecycle, freshness, and trust scoring metadata to master_dataextraction.

BEGIN;

CREATE SCHEMA IF NOT EXISTS staging_dataextraction;
CREATE SCHEMA IF NOT EXISTS master_dataextraction;

-- 1. Pre-Master Working Organizations (Canvas for Agents 3, 7, 4, 5)
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
);

-- 2. Pre-Master Working Persons (Decisions Makers & Career Edges)
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
);

-- 3. Pre-Master Working Emails (Discovered & Verified Mailboxes)
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
);

-- 4. Master Organizations Lifecycle & Freshness Metadata
ALTER TABLE master_dataextraction.organizations 
ADD COLUMN IF NOT EXISTS governance_status VARCHAR(50) DEFAULT 'CERTIFIED',
ADD COLUMN IF NOT EXISTS trust_score NUMERIC(5, 4) DEFAULT 0.9500,
ADD COLUMN IF NOT EXISTS freshness_score NUMERIC(5, 4) DEFAULT 1.0000,
ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS next_verification_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '90 days'),
ADD COLUMN IF NOT EXISTS verification_source VARCHAR(100) DEFAULT 'INITIAL_PROMOTION_GATE',
ADD COLUMN IF NOT EXISTS website_last_verified_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS email_last_verified_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS executive_last_verified_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS domain_last_verified_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS maps_last_verified_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS registry_last_verified_at TIMESTAMPTZ DEFAULT NOW();

-- 5. Master Persons Lifecycle Metadata
ALTER TABLE master_dataextraction.persons
ADD COLUMN IF NOT EXISTS governance_status VARCHAR(50) DEFAULT 'CERTIFIED',
ADD COLUMN IF NOT EXISTS trust_score NUMERIC(5, 4) DEFAULT 0.9000,
ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMPTZ DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS next_verification_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '90 days');

-- 6. High-Performance B-Tree Indexing Strategy
CREATE INDEX IF NOT EXISTS idx_working_org_domain ON staging_dataextraction.working_organizations (primary_domain);
CREATE INDEX IF NOT EXISTS idx_working_gov_status ON staging_dataextraction.working_organizations (governance_status);
CREATE INDEX IF NOT EXISTS idx_working_email_status ON staging_dataextraction.working_emails (deliverability_status);
CREATE INDEX IF NOT EXISTS idx_working_person_org ON staging_dataextraction.working_persons (org_id);

CREATE INDEX IF NOT EXISTS idx_master_org_next_verif 
ON master_dataextraction.organizations (next_verification_at ASC)
WHERE governance_status = 'CERTIFIED';

CREATE INDEX IF NOT EXISTS idx_master_org_gov_freshness 
ON master_dataextraction.organizations (governance_status, freshness_score);

COMMIT;
