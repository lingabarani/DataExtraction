-- =============================================================================
-- Migration 018: store the composed answer with each discovery search run
-- =============================================================================
-- A finished search can be replayed exactly (cards, citations, summary) after a restart.
-- Idempotent and additive.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS discovery_dataextraction;

ALTER TABLE discovery_dataextraction.search_runs
    ADD COLUMN IF NOT EXISTS answer JSONB;

ALTER TABLE discovery_dataextraction.search_runs
    ADD COLUMN IF NOT EXISTS requested_by TEXT;

CREATE INDEX IF NOT EXISTS idx_disc_runs_started ON discovery_dataextraction.search_runs (started_at DESC);

-- Stable lookups used when the same real-world organization appears in several searches.
CREATE INDEX IF NOT EXISTS idx_disc_org_norm_zip
    ON discovery_dataextraction.organizations (normalized_name, address_postal_code);
CREATE INDEX IF NOT EXISTS idx_disc_org_domain
    ON discovery_dataextraction.organizations (domain) WHERE domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_disc_org_ccn
    ON discovery_dataextraction.organizations ((regulatory->>'cms_ccn')) WHERE regulatory ? 'cms_ccn';
CREATE INDEX IF NOT EXISTS idx_disc_org_nclic
    ON discovery_dataextraction.organizations ((regulatory->>'nc_license_number')) WHERE regulatory ? 'nc_license_number';
CREATE INDEX IF NOT EXISTS idx_disc_people_org_norm
    ON discovery_dataextraction.people (org_id, normalized_name);
