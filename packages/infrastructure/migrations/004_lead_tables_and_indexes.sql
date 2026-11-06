-- =============================================================================
-- Migration 004: Lead Tables & Production High-Throughput Composite Indexes
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── 1. US Leads Table ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.us_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    full_name VARCHAR(255),
    email VARCHAR(255),
    email_status VARCHAR(50) DEFAULT 'UNKNOWN',
    phone VARCHAR(50),
    industry VARCHAR(150),
    seniority_level VARCHAR(50),
    department VARCHAR(50),
    state_code VARCHAR(10),
    country VARCHAR(10) DEFAULT 'US',
    lead_score INT DEFAULT 0,
    api_source VARCHAR(100),
    person JSONB DEFAULT '{}'::jsonb,
    company JSONB DEFAULT '{}'::jsonb,
    contact JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── 2. Mexico Leads Table ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.mexico_leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name VARCHAR(255) NOT NULL,
    domain VARCHAR(255),
    full_name VARCHAR(255),
    email VARCHAR(255),
    email_status VARCHAR(50) DEFAULT 'UNKNOWN',
    phone VARCHAR(50),
    industry VARCHAR(150),
    seniority_level VARCHAR(50),
    department VARCHAR(50),
    state_code VARCHAR(10),
    country VARCHAR(10) DEFAULT 'MX',
    lead_score INT DEFAULT 0,
    api_source VARCHAR(100),
    person JSONB DEFAULT '{}'::jsonb,
    company JSONB DEFAULT '{}'::jsonb,
    contact JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Ensure column compatibility if tables existed prior to migration
ALTER TABLE public.us_leads ADD COLUMN IF NOT EXISTS state_code VARCHAR(10);
ALTER TABLE public.us_leads ADD COLUMN IF NOT EXISTS industry VARCHAR(150);
ALTER TABLE public.us_leads ADD COLUMN IF NOT EXISTS lead_score INT DEFAULT 0;
ALTER TABLE public.us_leads ADD COLUMN IF NOT EXISTS email_status VARCHAR(50) DEFAULT 'UNKNOWN';

ALTER TABLE public.mexico_leads ADD COLUMN IF NOT EXISTS state_code VARCHAR(10);
ALTER TABLE public.mexico_leads ADD COLUMN IF NOT EXISTS state VARCHAR(100);
ALTER TABLE public.mexico_leads ADD COLUMN IF NOT EXISTS industry VARCHAR(150);
ALTER TABLE public.mexico_leads ADD COLUMN IF NOT EXISTS lead_score INT DEFAULT 0;
ALTER TABLE public.mexico_leads ADD COLUMN IF NOT EXISTS email_status VARCHAR(50) DEFAULT 'UNKNOWN';

-- ── 3. High-Performance Composite & Partial Indexes: US Leads ────────────────
CREATE INDEX IF NOT EXISTS idx_us_leads_domain ON public.us_leads (domain) WHERE domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_us_leads_email ON public.us_leads (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_us_leads_score_status ON public.us_leads (email_status, lead_score DESC);
CREATE INDEX IF NOT EXISTS idx_us_leads_geo ON public.us_leads (state_code, industry);
CREATE INDEX IF NOT EXISTS idx_us_leads_created ON public.us_leads (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_us_leads_company_trgm ON public.us_leads USING gin (company_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_us_leads_person_trgm ON public.us_leads USING gin (full_name gin_trgm_ops);

-- ── 4. High-Performance Composite & Partial Indexes: Mexico Leads ────────────
CREATE INDEX IF NOT EXISTS idx_mx_leads_domain ON public.mexico_leads (domain) WHERE domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mx_leads_email ON public.mexico_leads (email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_mx_leads_score_status ON public.mexico_leads (email_status, lead_score DESC);
CREATE INDEX IF NOT EXISTS idx_mx_leads_geo ON public.mexico_leads (state_code, industry);
CREATE INDEX IF NOT EXISTS idx_mx_leads_created ON public.mexico_leads (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_mx_leads_company_trgm ON public.mexico_leads USING gin (company_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_mx_leads_person_trgm ON public.mexico_leads USING gin (full_name gin_trgm_ops);
