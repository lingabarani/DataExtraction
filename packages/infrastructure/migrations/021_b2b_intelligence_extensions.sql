-- =============================================================================
-- Migration 021: Enterprise B2B Intelligence & Buying Committee In-Place Extensions
-- =============================================================================
-- Purpose:
--   Transforms the core schema into an Apollo / ZoomInfo / 6sense rival:
--   1. Extends master_dataextraction.organizations with Technographics, Intent Signals,
--      Scoops, and Hiring Velocity.
--   2. Extends master_dataextraction.persons with Buying Committee roles, Org Chart
--      reporting hierarchy, AI Propensity-to-Buy, and Lead Grades.
--   3. Synchronizes projections in search_dataextraction for sub-50ms search.
--   4. Updates public.companies and public.us_leads views, and extends public.mexico_leads.
--   NO NEW SCHEMAS. Modifies only existing tables with safe, non-destructive defaults.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. EXTEND MASTER ORGANIZATIONS
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE master_dataextraction.organizations
    ADD COLUMN IF NOT EXISTS tech_categories TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS primary_crm VARCHAR(100),
    ADD COLUMN IF NOT EXISTS primary_cloud VARCHAR(100),
    ADD COLUMN IF NOT EXISTS detected_technologies JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS intent_score NUMERIC(5,4) DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS intent_strength VARCHAR(20) DEFAULT 'NONE',
    ADD COLUMN IF NOT EXISTS intent_topics TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS buying_stage VARCHAR(50) DEFAULT 'Cold',
    ADD COLUMN IF NOT EXISTS intent_signals_detail JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS recent_hiring_velocity INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS company_scoops JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS intelligence_last_updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_master_org_intent_score ON master_dataextraction.organizations (intent_score DESC);
CREATE INDEX IF NOT EXISTS idx_master_org_intent_strength ON master_dataextraction.organizations (intent_strength);
CREATE INDEX IF NOT EXISTS idx_master_org_tech_categories ON master_dataextraction.organizations USING GIN (tech_categories);
CREATE INDEX IF NOT EXISTS idx_master_org_intent_topics ON master_dataextraction.organizations USING GIN (intent_topics);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. EXTEND MASTER PERSONS
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE master_dataextraction.persons
    ADD COLUMN IF NOT EXISTS reports_to_person_id UUID REFERENCES master_dataextraction.persons(person_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS management_level VARCHAR(50) DEFAULT 'INDIVIDUAL_CONTRIBUTOR',
    ADD COLUMN IF NOT EXISTS org_chart_depth SMALLINT DEFAULT 1,
    ADD COLUMN IF NOT EXISTS buying_role VARCHAR(50) DEFAULT 'INFLUENCER',
    ADD COLUMN IF NOT EXISTS propensity_to_buy_score NUMERIC(5,4) DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS lead_grade VARCHAR(5) DEFAULT 'C',
    ADD COLUMN IF NOT EXISTS score_reasoning JSONB DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_master_persons_buying_role ON master_dataextraction.persons (buying_role);
CREATE INDEX IF NOT EXISTS idx_master_persons_propensity ON master_dataextraction.persons (propensity_to_buy_score DESC);
CREATE INDEX IF NOT EXISTS idx_master_persons_reports_to ON master_dataextraction.persons (reports_to_person_id);
CREATE INDEX IF NOT EXISTS idx_master_persons_mgt_level ON master_dataextraction.persons (management_level);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. EXTEND SEARCH PROJECTIONS
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE search_dataextraction.company_search_projection
    ADD COLUMN IF NOT EXISTS intent_score NUMERIC(5,4) DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS intent_strength VARCHAR(20) DEFAULT 'NONE',
    ADD COLUMN IF NOT EXISTS intent_topics TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS tech_categories TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS primary_crm VARCHAR(100),
    ADD COLUMN IF NOT EXISTS primary_cloud VARCHAR(100),
    ADD COLUMN IF NOT EXISTS recent_hiring_velocity INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_proj_intent_score ON search_dataextraction.company_search_projection (intent_score DESC);
CREATE INDEX IF NOT EXISTS idx_proj_intent_topics ON search_dataextraction.company_search_projection USING GIN (intent_topics);
CREATE INDEX IF NOT EXISTS idx_proj_tech_categories ON search_dataextraction.company_search_projection USING GIN (tech_categories);

ALTER TABLE search_dataextraction.person_search_projection
    ADD COLUMN IF NOT EXISTS reports_to_person_id UUID,
    ADD COLUMN IF NOT EXISTS management_level VARCHAR(50) DEFAULT 'INDIVIDUAL_CONTRIBUTOR',
    ADD COLUMN IF NOT EXISTS buying_role VARCHAR(50) DEFAULT 'INFLUENCER',
    ADD COLUMN IF NOT EXISTS propensity_to_buy_score NUMERIC(5,4) DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS lead_grade VARCHAR(5) DEFAULT 'C',
    ADD COLUMN IF NOT EXISTS score_reasoning JSONB DEFAULT '{}'::jsonb;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. EXTEND MEXICO LEADS TABLE
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.mexico_leads
    ADD COLUMN IF NOT EXISTS reports_to_person_id TEXT,
    ADD COLUMN IF NOT EXISTS management_level VARCHAR(50) DEFAULT 'INDIVIDUAL_CONTRIBUTOR',
    ADD COLUMN IF NOT EXISTS buying_role VARCHAR(50) DEFAULT 'INFLUENCER',
    ADD COLUMN IF NOT EXISTS propensity_to_buy_score NUMERIC(5,4) DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS lead_grade VARCHAR(5) DEFAULT 'C',
    ADD COLUMN IF NOT EXISTS score_reasoning JSONB DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS intent_score NUMERIC(5,4) DEFAULT 0.0000,
    ADD COLUMN IF NOT EXISTS intent_strength VARCHAR(20) DEFAULT 'NONE',
    ADD COLUMN IF NOT EXISTS intent_topics TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS tech_categories TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS primary_crm VARCHAR(100);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. REFRESH CONSUMER VIEWS IN PUBLIC SCHEMA
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW public.companies AS
SELECT 
    o.org_id::text AS id,
    COALESCE(o.display_name, o.legal_name, 'Commercial Entity') AS name,
    o.legal_name,
    CASE 
        WHEN o.primary_domain IS NOT NULL AND o.primary_domain != '' 
        THEN 'https://' || o.primary_domain 
        ELSE NULL 
    END AS website,
    o.primary_domain AS domain,
    NULL::text AS email,
    NULL::text AS phone,
    NULL::text AS city,
    NULL::text AS state,
    NULL::character(2) AS state_code,
    NULL::text AS zip_code,
    COALESCE(o.industry, o.primary_industry_naics, 'Commercial Enterprise') AS industry,
    o.primary_industry_naics AS naics_code,
    o.statutory_tax_id AS ein,
    o.sec_cik AS cik,
    o.employee_count_min AS employee_min,
    o.employee_count_max AS employee_max,
    CASE 
        WHEN o.employee_count_max IS NOT NULL 
        THEN o.employee_count_min::text || '-' || o.employee_count_max::text 
        ELSE '1-50' 
    END AS employee_band,
    'MDM_MASTER' AS source,
    COALESCE(o.data_quality_score, 85)::integer AS data_quality_score,
    o.created_at,
    o.updated_at,
    o.display_name AS trade_name,
    o.legal_name AS normalized_name,
    o.jurisdiction::text AS entity_type,
    o.primary_industry_sic AS sic_code,
    NULL::text AS cage_code,
    NULL::text AS uei,
    NULL::text AS state_of_incorporation,
    NULL::text AS street,
    NULL::text AS county,
    'United States'::text AS country,
    NULL::numeric AS latitude,
    NULL::numeric AS longitude,
    '[]'::jsonb AS phones,
    '[]'::jsonb AS emails,
    'ESTIMATED'::text AS employee_count_source,
    1 AS source_count,
    o.updated_at AS last_verified_at,
    'MDM_MASTER'::text AS api_source,
    jsonb_build_object(
        'org_id', o.org_id,
        'domain', o.primary_domain,
        'legal_name', o.legal_name,
        'ein', o.statutory_tax_id
    ) AS raw_payload,
    o.updated_at AS deduplicated_at,
    o.org_id::text AS canonical_cluster_id,
    TRUE AS is_canonical,
    -- B2B Intelligence Extensions
    o.tech_categories,
    o.primary_crm,
    o.primary_cloud,
    o.detected_technologies,
    o.intent_score,
    o.intent_strength,
    o.intent_topics,
    o.buying_stage,
    o.recent_hiring_velocity,
    o.company_scoops
FROM master_dataextraction.organizations o;

CREATE OR REPLACE VIEW public.us_leads AS
SELECT 
    p.person_id::text AS id,
    p.full_name,
    p.first_name,
    p.last_name,
    p.current_primary_title AS title,
    p.current_primary_title AS standardized_title,
    COALESCE(p.seniority_level, 'EXECUTIVE') AS seniority_level,
    COALESCE(p.department, 'LEADERSHIP') AS department,
    p.primary_email AS email,
    COALESCE(p.email_status, 'UNKNOWN') AS email_status,
    COALESCE(p.email_confidence_score, 85)::integer AS email_confidence_score,
    p.primary_phone_e164 AS phone,
    p.primary_linkedin_url AS linkedin_url,
    TRUE AS is_current,
    o.org_id::text AS company_id,
    COALESCE(o.display_name, o.legal_name, 'Commercial Entity') AS company_name,
    o.primary_domain AS domain,
    COALESCE(o.industry, o.primary_industry_naics, 'Commercial Enterprise') AS industry,
    o.primary_industry_naics AS naics_code,
    o.statutory_tax_id AS ein,
    o.sec_cik AS cik,
    CASE 
        WHEN o.employee_count_max IS NOT NULL 
        THEN o.employee_count_min::text || '-' || o.employee_count_max::text 
        ELSE '1-50' 
    END AS employee_band,
    p.city,
    p.state,
    p.state_code,
    NULL::text AS zip_code,
    COALESCE(p.country, 'United States') AS country,
    COALESCE(p.data_quality_score, 80)::integer AS person_quality_score,
    COALESCE(o.data_quality_score, 90)::integer AS company_quality_score,
    ((COALESCE(p.data_quality_score, 80) + COALESCE(o.data_quality_score, 90)) / 2)::integer AS lead_score,
    'MDM_GOLDEN_RECORD' AS api_source,
    jsonb_build_object(
        'person_id', p.person_id,
        'full_name', p.full_name,
        'title', p.current_primary_title,
        'email', p.primary_email,
        'linkedin', p.primary_linkedin_url
    ) AS person,
    jsonb_build_object(
        'org_id', o.org_id,
        'name', o.display_name,
        'domain', o.primary_domain,
        'ein', o.statutory_tax_id,
        'industry', o.industry
    ) AS company,
    jsonb_build_object(
        'email', p.primary_email,
        'phone', p.primary_phone_e164,
        'email_status', p.email_status
    ) AS contact,
    p.created_at,
    p.updated_at,
    p.headline,
    p.photo_url,
    o.logo_url,
    o.technologies,
    o.funding_events,
    -- B2B Intelligence Extensions
    p.reports_to_person_id::text AS reports_to_person_id,
    p.management_level,
    p.buying_role,
    p.propensity_to_buy_score,
    p.lead_grade,
    p.score_reasoning,
    o.intent_score,
    o.intent_strength,
    o.intent_topics,
    o.tech_categories,
    o.primary_crm,
    o.primary_cloud
FROM master_dataextraction.persons p
LEFT JOIN master_dataextraction.organizations o ON p.current_primary_org_id = o.org_id;
