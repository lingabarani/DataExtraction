-- =============================================================================
-- Migration 005: SOC-2 Type II Immutable Access Audit Logs & Compliance
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS kg_audit;

-- ── 1. SOC-2 Type II Access Audit Log ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS kg_audit.access_logs (
    log_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    user_id VARCHAR(255) NOT NULL,
    user_email VARCHAR(255) NOT NULL,
    action VARCHAR(100) NOT NULL,            -- LEAD_READ, LEAD_EXPORT, SEARCH_QUERY, COMPLIANCE_OPT_OUT, COMPLIANCE_PURGE
    resource_type VARCHAR(100) NOT NULL,     -- leads, people, search, export, compliance
    resource_id VARCHAR(255),
    ip_address VARCHAR(50),
    user_agent VARCHAR(500),
    status_code INT NOT NULL DEFAULT 200,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON kg_audit.access_logs (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON kg_audit.access_logs (user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON kg_audit.access_logs (action, timestamp DESC);

-- ── 2. Active Suppression List Table (GDPR / CCPA) ───────────────────────────
CREATE TABLE IF NOT EXISTS kg_audit.suppression_lists (
    suppression_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hashed_identifier CHAR(64) NOT NULL UNIQUE,
    identifier_type VARCHAR(50) NOT NULL,
    reason VARCHAR(100) NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    is_active BOOLEAN NOT NULL DEFAULT true
);

CREATE INDEX IF NOT EXISTS idx_suppression_hash ON kg_audit.suppression_lists (hashed_identifier) WHERE is_active = true;

