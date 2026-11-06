-- =============================================================================
-- Migration 008: DataExtraction Apollo.io MDM Schema Alignment & Entity Extensions
-- =============================================================================
-- Purpose:
--   Aligns master_dataextraction, staging_dataextraction, and kg_graph schemas
--   with the comprehensive Apollo.io B2B entity specifications:
--   1. Organizations: Social URLs, Keywords, Funding rounds, Headcount growth,
--      Departmental headcount breakdown, Ticker, Exchange, Logo.
--   2. Persons: Headline, Photo URL, Department array, Engagement flags.
--   3. Employment Relationships: Rich corporate tenure tracking and confidence scores.
--   4. Composite performance indexes for sub-millisecond filtering.
-- =============================================================================

-- ── 1. Master Organizations Apollo.io Extensions ─────────────────────────────
ALTER TABLE master_dataextraction.organizations 
    ADD COLUMN IF NOT EXISTS industry VARCHAR(150),
    ADD COLUMN IF NOT EXISTS sub_industry VARCHAR(150),
    ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS linkedin_uid VARCHAR(100),
    ADD COLUMN IF NOT EXISTS social_urls JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS keywords TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS secondary_industries TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS departmental_headcount JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS headcount_growth_6m NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS headcount_growth_12m NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS latest_funding_stage VARCHAR(50),
    ADD COLUMN IF NOT EXISTS funding_events JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS publicly_traded_symbol VARCHAR(20),
    ADD COLUMN IF NOT EXISTS publicly_traded_exchange VARCHAR(50),
    ADD COLUMN IF NOT EXISTS technologies JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS short_description TEXT;

-- High-performance indexes for Organizations
CREATE INDEX IF NOT EXISTS idx_master_org_domain ON master_dataextraction.organizations (primary_domain) WHERE primary_domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_org_ticker ON master_dataextraction.organizations (publicly_traded_symbol) WHERE publicly_traded_symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_org_funding ON master_dataextraction.organizations (total_funding_usd DESC) WHERE total_funding_usd IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_org_keywords ON master_dataextraction.organizations USING GIN (keywords);

-- ── 2. Master Persons Apollo.io Extensions ───────────────────────────────────
ALTER TABLE master_dataextraction.persons 
    ADD COLUMN IF NOT EXISTS headline VARCHAR(255),
    ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS departments TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS linkedin_uid VARCHAR(100),
    ADD COLUMN IF NOT EXISTS is_likely_to_engage BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS email_status VARCHAR(50) DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS email_confidence_score SMALLINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS direct_dial_status VARCHAR(50),
    ADD COLUMN IF NOT EXISTS city VARCHAR(100),
    ADD COLUMN IF NOT EXISTS state VARCHAR(100),
    ADD COLUMN IF NOT EXISTS state_code VARCHAR(10),
    ADD COLUMN IF NOT EXISTS country VARCHAR(100);

-- Indexes for Persons
CREATE INDEX IF NOT EXISTS idx_master_persons_email ON master_dataextraction.persons (primary_email) WHERE primary_email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_persons_linkedin ON master_dataextraction.persons (primary_linkedin_url) WHERE primary_linkedin_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_persons_title ON master_dataextraction.persons (current_primary_title);
CREATE INDEX IF NOT EXISTS idx_master_persons_seniority ON master_dataextraction.persons (seniority_level);

-- ── 3. Employment Relationships Enhancements ─────────────────────────────────
ALTER TABLE kg_graph.employment_relationships
    ADD COLUMN IF NOT EXISTS headline VARCHAR(255),
    ADD COLUMN IF NOT EXISTS department_details JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_emp_rel_active ON kg_graph.employment_relationships (person_id, is_current);
CREATE INDEX IF NOT EXISTS idx_emp_rel_org_active ON kg_graph.employment_relationships (org_id, is_current);
CREATE INDEX IF NOT EXISTS idx_emp_rel_seniority ON kg_graph.employment_relationships (seniority_level);

-- ── 4. Staging Schema Alignment ──────────────────────────────────────────────
ALTER TABLE staging_dataextraction.staging_companies
    ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS social_urls JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS keywords TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS technologies JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS funding_events JSONB DEFAULT '[]'::jsonb;

ALTER TABLE staging_dataextraction.staging_people
    ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS headline VARCHAR(255),
    ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS departments TEXT[] DEFAULT '{}';

-- ── 5. Serving Projections (us_leads & mexico_leads) ─────────────────────────
ALTER TABLE public.us_leads
    ADD COLUMN IF NOT EXISTS headline VARCHAR(255),
    ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS technologies JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS funding_events JSONB DEFAULT '[]'::jsonb;

ALTER TABLE public.mexico_leads
    ADD COLUMN IF NOT EXISTS headline VARCHAR(255),
    ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS logo_url VARCHAR(500),
    ADD COLUMN IF NOT EXISTS technologies JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS funding_events JSONB DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_us_leads_composite_score ON public.us_leads (email_status, lead_score DESC);
CREATE INDEX IF NOT EXISTS idx_mexico_leads_composite_score ON public.mexico_leads (email_status, lead_score DESC);
