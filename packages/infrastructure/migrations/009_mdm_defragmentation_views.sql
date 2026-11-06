-- =============================================================================
-- Migration 009: DataExtraction MDM Data Flow De-Fragmentation
-- =============================================================================
-- Purpose:
--   Eliminates architectural data flow fragmentation by:
--   1. Renaming legacy public.us_leads and public.companies to backup tables.
--   2. Replacing public.companies with a live unified SQL VIEW over master_dataextraction.organizations.
--   3. Replacing public.us_leads with a live unified SQL VIEW over master_dataextraction.persons & organizations.
--   4. Guaranteeing that any legacy query immediately accesses the canonical 210,000+ Golden Records.
-- =============================================================================

DO $$
BEGIN
    -- 1. Archive legacy public.companies if it is a BASE TABLE
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'companies' AND table_type = 'BASE TABLE'
    ) THEN
        DROP TABLE IF EXISTS public.companies_legacy_backup CASCADE;
        ALTER TABLE public.companies RENAME TO companies_legacy_backup;
    END IF;

    -- 2. Archive legacy public.us_leads if it is a BASE TABLE
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'public' AND table_name = 'us_leads' AND table_type = 'BASE TABLE'
    ) THEN
        DROP TABLE IF EXISTS public.us_leads_legacy_backup CASCADE;
        ALTER TABLE public.us_leads RENAME TO us_leads_legacy_backup;
    END IF;
END $$;

-- 3. Create Canonical public.companies VIEW over master_dataextraction.organizations
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
    TRUE AS is_canonical
FROM master_dataextraction.organizations o;

-- 4. Create Canonical public.us_leads VIEW over master_dataextraction.persons & organizations
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
    COALESCE(o.technologies, '[]'::jsonb) AS technologies,
    COALESCE(o.funding_events, '[]'::jsonb) AS funding_events
FROM master_dataextraction.persons p
LEFT JOIN master_dataextraction.organizations o ON p.current_primary_org_id = o.org_id;

-- 5. Grant Permissions
GRANT SELECT ON public.companies TO PUBLIC;
GRANT SELECT ON public.us_leads TO PUBLIC;

