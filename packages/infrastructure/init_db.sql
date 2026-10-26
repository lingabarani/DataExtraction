-- Initialize OneExtraction PostgreSQL database
-- This script creates the schema for Dataforge + OneExtraction

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Main businesses table (Dataforge-compatible)
CREATE TABLE IF NOT EXISTS businesses (
    -- Core identifiers
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id TEXT UNIQUE,
    
    -- Basic info
    name TEXT NOT NULL,
    legal_name TEXT,
    website_url TEXT,
    domain TEXT,
    
    -- Contact info
    phone TEXT,
    email TEXT,
    
    -- Location
    city TEXT,
    state TEXT,
    state_code TEXT,
    zip_code TEXT,
    country TEXT DEFAULT 'United States',
    latitude DECIMAL,
    longitude DECIMAL,
    
    -- Business classification
    industry TEXT,
    sub_industry TEXT,
    naics_code TEXT,
    sic_code TEXT,
    
    -- Company identifiers
    ein TEXT,
    cik TEXT,
    cage_code TEXT,
    uei TEXT,
    
    -- Size & employees
    employee_count_min INTEGER,
    employee_count_max INTEGER,
    employee_count_band TEXT,
    
    -- Enrichment fields
    tech_stack TEXT[],
    cms_detected TEXT,
    ssl_valid BOOLEAN,
    site_speed_ms INTEGER,
    ai_summary TEXT,
    health_score SMALLINT,
    pain_points TEXT[],
    
    -- Email enrichment
    extracted_emails TEXT[],
    email_source TEXT,
    email_validation_status TEXT,
    email_validation_result JSONB,
    smtp_verified BOOLEAN,
    is_disposable BOOLEAN,
    is_role_account BOOLEAN,
    is_catch_all BOOLEAN,
    email_validated_at TIMESTAMPTZ,
    
    -- OneExtraction specific
    source TEXT,
    data_quality_score SMALLINT,
    executives_json JSONB,
    
    -- Metadata
    enrichment_attempts INTEGER DEFAULT 0,
    last_enriched_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Create indexes for common queries
CREATE INDEX idx_businesses_email ON businesses(email) WHERE email IS NOT NULL;
CREATE INDEX idx_businesses_company_id ON businesses(company_id);
CREATE INDEX idx_businesses_ein ON businesses(ein);
CREATE INDEX idx_businesses_cik ON businesses(cik);
CREATE INDEX idx_businesses_domain ON businesses(domain);
CREATE INDEX idx_businesses_state ON businesses(state_code);
CREATE INDEX idx_businesses_industry ON businesses(industry);
CREATE INDEX idx_businesses_verification_status ON businesses(email_validation_status);
CREATE INDEX idx_businesses_health_score ON businesses(health_score);
CREATE INDEX idx_businesses_tech_stack ON businesses USING GIN(tech_stack);

-- Executives/People table
CREATE TABLE IF NOT EXISTS people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id TEXT UNIQUE,
    company_id TEXT NOT NULL REFERENCES businesses(company_id),
    
    -- Personal info
    first_name TEXT,
    last_name TEXT,
    full_name TEXT,
    
    -- Title & role
    title TEXT,
    standardized_title TEXT,
    seniority_level TEXT,
    department TEXT,
    
    -- Contact
    work_email TEXT,
    email_status TEXT,
    email_confidence_score SMALLINT,
    direct_phone TEXT,
    phone_type TEXT,
    
    -- Status
    is_active BOOLEAN DEFAULT true,
    
    -- Metadata
    source TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Create indexes for people
CREATE INDEX idx_people_company_id ON people(company_id);
CREATE INDEX idx_people_work_email ON people(work_email);
CREATE INDEX idx_people_title ON people(standardized_title);
CREATE INDEX idx_people_seniority ON people(seniority_level);

-- Enrichment jobs table (for tracking progress)
CREATE TABLE IF NOT EXISTS enrichment_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name TEXT NOT NULL,
    job_type TEXT NOT NULL,  -- 'email_extraction', 'tech_detection', 'industry_classification', 'validation'
    status TEXT DEFAULT 'pending',  -- 'pending', 'running', 'completed', 'failed'
    
    total_records INTEGER,
    processed_records INTEGER DEFAULT 0,
    failed_records INTEGER DEFAULT 0,
    
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Validation results table (for detailed audit trail)
CREATE TABLE IF NOT EXISTS email_validation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID REFERENCES businesses(id),
    email TEXT NOT NULL,
    
    validation_result JSONB,
    
    is_reachable TEXT,
    is_deliverable BOOLEAN,
    syntax_valid BOOLEAN,
    mx_accepts_mail BOOLEAN,
    smtp_can_connect BOOLEAN,
    has_full_inbox BOOLEAN,
    is_catch_all BOOLEAN,
    is_disposable BOOLEAN,
    is_role_account BOOLEAN,
    
    validated_at TIMESTAMPTZ DEFAULT now()
);

-- Create indexes for validation results
CREATE INDEX idx_validation_email ON email_validation_results(email);
CREATE INDEX idx_validation_business ON email_validation_results(business_id);

-- Analytics summary table
CREATE TABLE IF NOT EXISTS enrichment_analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    total_companies INTEGER,
    companies_with_email INTEGER,
    emails_verified_safe INTEGER,
    emails_risky INTEGER,
    emails_invalid INTEGER,
    
    companies_with_tech INTEGER,
    companies_with_industry INTEGER,
    companies_with_health_score INTEGER,
    
    avg_health_score DECIMAL,
    
    calculated_at TIMESTAMPTZ DEFAULT now()
);

-- Grant permissions to forge user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO forge;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO forge;
GRANT USAGE, CREATE ON SCHEMA public TO forge;

-- Insert initial analytics record
INSERT INTO enrichment_analytics (
    total_companies, companies_with_email, emails_verified_safe,
    emails_risky, emails_invalid, companies_with_tech,
    companies_with_industry, companies_with_health_score, avg_health_score
) VALUES (0, 0, 0, 0, 0, 0, 0, 0, 0);

-- Create views for easier querying
CREATE OR REPLACE VIEW v_enriched_companies AS
SELECT 
    b.id,
    b.company_id,
    b.name,
    b.email,
    b.website_url,
    b.industry,
    b.state_code,
    b.tech_stack,
    b.health_score,
    b.email_validation_status,
    COUNT(p.id) as executive_count,
    STRING_AGG(DISTINCT p.full_name || ' (' || p.standardized_title || ')', ', ') as executives
FROM businesses b
LEFT JOIN people p ON b.company_id = p.company_id AND p.is_active = true
WHERE b.email IS NOT NULL
GROUP BY b.id, b.company_id, b.name, b.email, b.website_url, 
         b.industry, b.state_code, b.tech_stack, b.health_score, b.email_validation_status;

CREATE OR REPLACE VIEW v_verified_leads AS
SELECT 
    b.id,
    b.company_id,
    b.name,
    b.email,
    b.website_url,
    b.industry,
    b.state_code,
    b.phone,
    b.health_score,
    COUNT(p.id) as decision_makers,
    STRING_AGG(p.full_name || ' (' || p.standardized_title || ')', ', ') as contact_names
FROM businesses b
LEFT JOIN people p ON b.company_id = p.company_id AND p.is_active = true
WHERE b.email_validation_status = 'VERIFIED_SAFE'
AND b.email IS NOT NULL
GROUP BY b.id, b.company_id, b.name, b.email, b.website_url, 
         b.industry, b.state_code, b.phone, b.health_score
ORDER BY b.health_score DESC;

-- Log initial setup
INSERT INTO enrichment_jobs (job_name, job_type, status)
VALUES ('Database Initialization', 'setup', 'completed');
