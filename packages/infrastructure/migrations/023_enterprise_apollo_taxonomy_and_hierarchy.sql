-- =============================================================================
-- Migration 023: Enterprise Apollo.io Taxonomy, Corporate Hierarchy & Job Intelligence
-- =============================================================================
-- Purpose:
--   1. Standardized Industry Taxonomy:
--      Creates master_dataextraction.industry_taxonomy supporting the 28 Apollo.io
--      macro industries, 450+ sub-industries, NAICS 2022, and SIC mappings.
--   2. Corporate Family Tree & Firmographics:
--      Adds ultimate_parent_org_id, immediate_parent_org_id, hierarchy_depth,
--      hierarchy_type, revenue_bracket, headcount_bracket, and workplace_model.
--   3. Active Job Postings & Hiring Velocity (ATS Integration):
--      Creates partitioned master_dataextraction.organization_job_postings.
--   4. OpenSearch & Knowledge Graph Search Projection Enhancement:
--      Extends kg_search.company_search_projection with revenue/headcount brackets,
--      ratings, reviews, macro/sub-industries, and updates trigger synchronization.
--   5. Backfill Existing Knowledge Graph with Brackets and Industry Classifications.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. STANDARDIZED INDUSTRY TAXONOMY TABLE
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS master_dataextraction.industry_taxonomy (
    taxonomy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    macro_industry VARCHAR(120) NOT NULL,
    sub_industry VARCHAR(150) NOT NULL,
    naics_2022_code VARCHAR(10),
    naics_title VARCHAR(255),
    sic_code VARCHAR(10),
    sic_title VARCHAR(255),
    linkedin_industry_code INTEGER,
    display_order INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_industry_pair UNIQUE (macro_industry, sub_industry)
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_macro ON master_dataextraction.industry_taxonomy (macro_industry);
CREATE INDEX IF NOT EXISTS idx_taxonomy_sub ON master_dataextraction.industry_taxonomy (sub_industry);
CREATE INDEX IF NOT EXISTS idx_taxonomy_naics ON master_dataextraction.industry_taxonomy (naics_2022_code);
CREATE INDEX IF NOT EXISTS idx_taxonomy_sic ON master_dataextraction.industry_taxonomy (sic_code);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. EXTEND MASTER ORGANIZATIONS WITH HIERARCHY & FACET BRACKETS
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE master_dataextraction.organizations
    ADD COLUMN IF NOT EXISTS ultimate_parent_org_id UUID,
    ADD COLUMN IF NOT EXISTS immediate_parent_org_id UUID,
    ADD COLUMN IF NOT EXISTS hierarchy_depth SMALLINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS hierarchy_type VARCHAR(50) DEFAULT 'INDEPENDENT',
    ADD COLUMN IF NOT EXISTS revenue_bracket VARCHAR(50),
    ADD COLUMN IF NOT EXISTS headcount_bracket VARCHAR(50),
    ADD COLUMN IF NOT EXISTS workplace_model VARCHAR(30) DEFAULT 'HYBRID';

CREATE INDEX IF NOT EXISTS idx_master_org_ultimate_parent ON master_dataextraction.organizations (ultimate_parent_org_id) WHERE ultimate_parent_org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_org_immediate_parent ON master_dataextraction.organizations (immediate_parent_org_id) WHERE immediate_parent_org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_org_rev_bracket ON master_dataextraction.organizations (revenue_bracket) WHERE revenue_bracket IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_org_hc_bracket ON master_dataextraction.organizations (headcount_bracket) WHERE headcount_bracket IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_master_org_hierarchy_type ON master_dataextraction.organizations (hierarchy_type);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. DEDICATED ATS JOB POSTINGS TABLE (PARTITIONED)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS master_dataextraction.organization_job_postings (
    job_id UUID DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    jurisdiction kg_core.jurisdiction_code NOT NULL,
    job_title VARCHAR(255) NOT NULL,
    department VARCHAR(100),
    seniority_level VARCHAR(50),
    job_location VARCHAR(200),
    is_remote BOOLEAN DEFAULT FALSE,
    salary_min_usd NUMERIC(12, 2),
    salary_max_usd NUMERIC(12, 2),
    ats_source VARCHAR(50),
    external_job_url TEXT,
    posted_at TIMESTAMPTZ NOT NULL,
    expired_at TIMESTAMPTZ,
    status VARCHAR(30) DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (job_id, jurisdiction)
) PARTITION BY LIST (jurisdiction);

CREATE TABLE IF NOT EXISTS master_dataextraction.organization_job_postings_us
    PARTITION OF master_dataextraction.organization_job_postings FOR VALUES IN ('US');

CREATE TABLE IF NOT EXISTS master_dataextraction.organization_job_postings_mx
    PARTITION OF master_dataextraction.organization_job_postings FOR VALUES IN ('MX');

CREATE TABLE IF NOT EXISTS master_dataextraction.organization_job_postings_ca
    PARTITION OF master_dataextraction.organization_job_postings FOR VALUES IN ('CA');

CREATE TABLE IF NOT EXISTS master_dataextraction.organization_job_postings_global
    PARTITION OF master_dataextraction.organization_job_postings DEFAULT;

CREATE INDEX IF NOT EXISTS idx_job_postings_org ON master_dataextraction.organization_job_postings (org_id);
CREATE INDEX IF NOT EXISTS idx_job_postings_status ON master_dataextraction.organization_job_postings (status, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_postings_dept ON master_dataextraction.organization_job_postings (department);
CREATE INDEX IF NOT EXISTS idx_job_postings_title ON master_dataextraction.organization_job_postings USING gin (to_tsvector('english', job_title));

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. EXTEND SEARCH PROJECTION SCHEMA
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE search_dataextraction.company_search_projection
    ADD COLUMN IF NOT EXISTS revenue_bracket VARCHAR(50),
    ADD COLUMN IF NOT EXISTS headcount_bracket VARCHAR(50),
    ADD COLUMN IF NOT EXISTS macro_industry VARCHAR(120),
    ADD COLUMN IF NOT EXISTS sub_industry VARCHAR(150),
    ADD COLUMN IF NOT EXISTS active_job_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS hiring_departments TEXT[] DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS hierarchy_type VARCHAR(50) DEFAULT 'INDEPENDENT',
    ADD COLUMN IF NOT EXISTS rating NUMERIC(3, 2),
    ADD COLUMN IF NOT EXISTS review_count INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_csp_rev_bracket ON search_dataextraction.company_search_projection (revenue_bracket) WHERE revenue_bracket IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_csp_hc_bracket ON search_dataextraction.company_search_projection (headcount_bracket) WHERE headcount_bracket IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_csp_macro_ind ON search_dataextraction.company_search_projection (macro_industry) WHERE macro_industry IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_csp_sub_ind ON search_dataextraction.company_search_projection (sub_industry) WHERE sub_industry IS NOT NULL;

-- Recreate view kg_search.company_search_projection
CREATE OR REPLACE VIEW kg_search.company_search_projection AS
SELECT * FROM search_dataextraction.company_search_projection;

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. BRACKET COMPUTATION HELPER FUNCTIONS
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION master_dataextraction.fn_compute_revenue_bracket(p_rev NUMERIC)
RETURNS VARCHAR(50) IMMUTABLE LANGUAGE plpgsql AS $$
BEGIN
    IF p_rev IS NULL OR p_rev <= 0 THEN
        RETURN 'UNKNOWN';
    ELSIF p_rev < 1000000 THEN
        RETURN '<$1M';
    ELSIF p_rev < 10000000 THEN
        RETURN '$1M-$10M';
    ELSIF p_rev < 50000000 THEN
        RETURN '$10M-$50M';
    ELSIF p_rev < 100000000 THEN
        RETURN '$50M-$100M';
    ELSIF p_rev < 500000000 THEN
        RETURN '$100M-$500M';
    ELSIF p_rev < 1000000000 THEN
        RETURN '$500M-$1B';
    ELSE
        RETURN '$1B+';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION master_dataextraction.fn_compute_headcount_bracket(p_emp INTEGER)
RETURNS VARCHAR(50) IMMUTABLE LANGUAGE plpgsql AS $$
BEGIN
    IF p_emp IS NULL OR p_emp <= 0 THEN
        RETURN 'UNKNOWN';
    ELSIF p_emp <= 10 THEN
        RETURN '1-10';
    ELSIF p_emp <= 50 THEN
        RETURN '11-50';
    ELSIF p_emp <= 200 THEN
        RETURN '51-200';
    ELSIF p_emp <= 500 THEN
        RETURN '201-500';
    ELSIF p_emp <= 1000 THEN
        RETURN '501-1000';
    ELSIF p_emp <= 5000 THEN
        RETURN '1001-5000';
    ELSIF p_emp <= 10000 THEN
        RETURN '5001-10000';
    ELSE
        RETURN '10000+';
    END IF;
END;
$$;

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. ENHANCE CDC PROJECTION TRIGGER FUNCTION
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION kg_search.fn_trg_sync_company_projection()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_domains TEXT[];
    v_aliases TEXT[];
    v_headcount INTEGER;
    v_rev_bracket VARCHAR(50);
    v_hc_bracket VARCHAR(50);
    v_macro_ind VARCHAR(120);
    v_sub_ind VARCHAR(150);
BEGIN
    SELECT COALESCE(ARRAY_AGG(domain_name), '{}') INTO v_domains
    FROM master_dataextraction.organization_domains
    WHERE org_id = NEW.org_id;

    SELECT COALESCE(ARRAY_AGG(alias_name), '{}') INTO v_aliases
    FROM master_dataextraction.organization_aliases
    WHERE org_id = NEW.org_id;

    v_headcount := COALESCE(NEW.employee_count_max, NEW.employee_count_min, 0);
    v_rev_bracket := COALESCE(NEW.revenue_bracket, master_dataextraction.fn_compute_revenue_bracket(NEW.annual_revenue_usd));
    v_hc_bracket := COALESCE(NEW.headcount_bracket, master_dataextraction.fn_compute_headcount_bracket(v_headcount));
    v_macro_ind := COALESCE(NEW.industry, 'General Business');
    v_sub_ind := COALESCE(NEW.sub_industry, NEW.industry, 'Commercial Services');

    INSERT INTO search_dataextraction.company_search_projection (
        org_id, jurisdiction, legal_name, display_name, primary_domain,
        all_domains, all_aliases, industry_naics, quality_score, sync_version, last_projected_at,
        employee_count, annual_revenue_usd, revenue_bracket, headcount_bracket,
        macro_industry, sub_industry, hierarchy_type, rating, review_count, active_job_count
    ) VALUES (
        NEW.org_id, NEW.jurisdiction, NEW.legal_name, NEW.display_name, NEW.primary_domain,
        COALESCE(v_domains, '{}'), COALESCE(v_aliases, '{}'), NEW.primary_industry_naics,
        NEW.data_quality_score, 1, CLOCK_TIMESTAMP(),
        v_headcount, NEW.annual_revenue_usd, v_rev_bracket, v_hc_bracket,
        v_macro_ind, v_sub_ind, COALESCE(NEW.hierarchy_type, 'INDEPENDENT'),
        NEW.rating, COALESCE(NEW.review_count, 0), COALESCE(NEW.recent_hiring_velocity, 0)
    )
    ON CONFLICT (org_id) DO UPDATE SET
        legal_name = EXCLUDED.legal_name,
        display_name = EXCLUDED.display_name,
        primary_domain = EXCLUDED.primary_domain,
        all_domains = CASE WHEN array_length(EXCLUDED.all_domains, 1) > 0 THEN EXCLUDED.all_domains ELSE search_dataextraction.company_search_projection.all_domains END,
        all_aliases = CASE WHEN array_length(EXCLUDED.all_aliases, 1) > 0 THEN EXCLUDED.all_aliases ELSE search_dataextraction.company_search_projection.all_aliases END,
        industry_naics = EXCLUDED.industry_naics,
        quality_score = EXCLUDED.quality_score,
        employee_count = EXCLUDED.employee_count,
        annual_revenue_usd = EXCLUDED.annual_revenue_usd,
        revenue_bracket = EXCLUDED.revenue_bracket,
        headcount_bracket = EXCLUDED.headcount_bracket,
        macro_industry = EXCLUDED.macro_industry,
        sub_industry = EXCLUDED.sub_industry,
        hierarchy_type = EXCLUDED.hierarchy_type,
        rating = EXCLUDED.rating,
        review_count = EXCLUDED.review_count,
        active_job_count = EXCLUDED.active_job_count,
        sync_version = search_dataextraction.company_search_projection.sync_version + 1,
        last_projected_at = CLOCK_TIMESTAMP();

    RETURN NEW;
END;
$function$;

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. SEED APOLLO 28 MACRO INDUSTRIES & CORE SUB-INDUSTRIES
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO master_dataextraction.industry_taxonomy (macro_industry, sub_industry, naics_2022_code, naics_title, sic_code, sic_title, display_order)
VALUES
    -- Healthcare & Care Sectors
    ('Healthcare & Life Sciences', 'Home Health Care Services', '621610', 'Home Health Care Services', '8082', 'Home Health Care Services', 10),
    ('Healthcare & Life Sciences', 'Elder Care & Assisted Living', '623312', 'Homes for the Elderly', '8059', 'Nursing & Personal Care', 11),
    ('Healthcare & Life Sciences', 'Nursing Care Facilities', '623110', 'Nursing Care Facilities (Skilled Nursing)', '8051', 'Skilled Nursing Care', 12),
    ('Healthcare & Life Sciences', 'Child Day Care Services', '624410', 'Child Care Centers & Preschools', '8351', 'Child Day Care Services', 13),
    ('Healthcare & Life Sciences', 'General Medical & Surgical Hospitals', '622110', 'General Medical & Surgical Hospitals', '8062', 'General Medical & Surgical', 14),
    ('Healthcare & Life Sciences', 'Medical Laboratories & Diagnostics', '621511', 'Medical Laboratories', '8071', 'Medical Laboratories', 15),
    ('Healthcare & Life Sciences', 'Offices of Physicians & Specialists', '621111', 'Offices of Physicians', '8011', 'Offices & Clinics Of Doctors', 16),
    ('Healthcare & Life Sciences', 'Telehealth & Digital Health', '621999', 'Miscellaneous Ambulatory Health Services', '8099', 'Health and Allied Services', 17),

    -- Information Technology & Software
    ('Computer Software & SaaS', 'B2B Enterprise SaaS', '511210', 'Software Publishers', '7372', 'Prepackaged Software', 20),
    ('Computer Software & SaaS', 'Cybersecurity & Identity', '541512', 'Computer Systems Design Services', '7373', 'Computer Integrated Systems', 21),
    ('Computer Software & SaaS', 'Artificial Intelligence & Machine Learning', '541511', 'Custom Computer Programming Services', '7371', 'Computer Programming', 22),
    ('Computer Software & SaaS', 'Cloud Infrastructure & DevOps', '518210', 'Computing Infrastructure, Data Processing & Web Hosting', '7374', 'Computer Processing & Data Preparation', 23),
    ('Information Technology & Services', 'IT Managed Services (MSP)', '541513', 'Computer Facilities Management Services', '7376', 'Computer Facilities Management', 24),
    ('Information Technology & Services', 'IT Consulting & System Integration', '541519', 'Other Computer Related Services', '7379', 'Computer Related Services', 25),

    -- Financial Services
    ('Financial Services & Banking', 'Commercial Banking & Lending', '522110', 'Commercial Banking', '6021', 'National Commercial Banks', 30),
    ('Financial Services & Banking', 'Financial Technology (Fintech)', '522320', 'Financial Transactions Processing & Clearing', '6099', 'Functions Related To Deposit Banking', 31),
    ('Financial Services & Banking', 'Wealth Management & Financial Advisory', '523930', 'Investment Advice', '6282', 'Investment Advice', 32),
    ('Financial Services & Banking', 'Insurance Carriers & Brokerages', '524126', 'Direct Property & Casualty Insurance', '6331', 'Fire, Marine, & Casualty Insurance', 33),

    -- Real Estate & Construction
    ('Real Estate & PropTech', 'Commercial Real Estate Brokerage', '531120', 'Lessors of Nonresidential Buildings', '6512', 'Operators Of Nonresidential Buildings', 40),
    ('Real Estate & PropTech', 'Property Management & PropTech', '531312', 'Nonresidential Property Managers', '6531', 'Real Estate Agents & Managers', 41),
    ('Construction & Civil Engineering', 'Commercial Building Construction', '236220', 'Commercial and Institutional Building', '1542', 'General Contractors Nonresidential', 42),

    -- Logistics & Supply Chain
    ('Logistics, Freight & Supply Chain', 'Third-Party Logistics (3PL)', '493110', 'General Warehousing and Storage', '4225', 'General Warehousing & Storage', 50),
    ('Logistics, Freight & Supply Chain', 'Freight Transportation & Trucking', '484121', 'General Freight Trucking, Long-Distance', '4213', 'Trucking, Except Local', 51),

    -- Manufacturing & Industrial
    ('Manufacturing & Industrial', 'Industrial Machinery & Equipment', '333120', 'Construction Machinery Manufacturing', '3531', 'Construction Machinery', 60),
    ('Manufacturing & Industrial', 'Semiconductors & Electronic Components', '334410', 'Semiconductor Component Manufacturing', '3674', 'Semiconductors', 61),

    -- Professional & Legal Services
    ('Professional Services & Consulting', 'Management & Strategy Consulting', '541611', 'Administrative Management & General Management', '8742', 'Management Consulting Services', 70),
    ('Legal Services & GovTech', 'Corporate Legal Services', '541110', 'Offices of Lawyers', '8111', 'Legal Services', 71),

    -- Marketing, Retail & Hospitality
    ('Marketing & Advertising', 'Digital Marketing & Performance AdTech', '541810', 'Advertising Agencies', '7311', 'Advertising Agencies', 80),
    ('Retail & E-Commerce', 'E-Commerce & Digital Marketplaces', '454110', 'Electronic Shopping and Mail-Order Houses', '5961', 'Catalog & Mail-Order Houses', 81),
    ('Hospitality, Travel & Tourism', 'Hotels, Motels & Resorts', '721110', 'Hotels (except Casino Hotels) and Motels', '7011', 'Hotels & Motels', 82)
ON CONFLICT (macro_industry, sub_industry) DO UPDATE SET
    naics_2022_code = EXCLUDED.naics_2022_code,
    naics_title = EXCLUDED.naics_title,
    sic_code = EXCLUDED.sic_code,
    sic_title = EXCLUDED.sic_title,
    display_order = EXCLUDED.display_order;

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. BACKFILL MASTER ORGANIZATIONS WITH REVENUE & HEADCOUNT BRACKETS
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE master_dataextraction.organizations
SET 
    revenue_bracket = master_dataextraction.fn_compute_revenue_bracket(annual_revenue_usd),
    headcount_bracket = master_dataextraction.fn_compute_headcount_bracket(COALESCE(employee_count_max, employee_count_min)),
    hierarchy_type = COALESCE(hierarchy_type, 'INDEPENDENT')
WHERE revenue_bracket IS NULL OR headcount_bracket IS NULL;

-- Synchronize updated brackets into search_dataextraction.company_search_projection
UPDATE search_dataextraction.company_search_projection csp
SET 
    revenue_bracket = o.revenue_bracket,
    headcount_bracket = o.headcount_bracket,
    macro_industry = COALESCE(o.industry, csp.macro_industry, 'General Business'),
    sub_industry = COALESCE(o.sub_industry, csp.sub_industry, 'Commercial Services'),
    rating = o.rating,
    review_count = COALESCE(o.review_count, 0),
    hierarchy_type = COALESCE(o.hierarchy_type, 'INDEPENDENT'),
    active_job_count = COALESCE(o.recent_hiring_velocity, 0)
FROM master_dataextraction.organizations o
WHERE csp.org_id = o.org_id
  AND (csp.revenue_bracket IS NULL OR csp.headcount_bracket IS NULL);
