-- =============================================================================
-- Migration 010: DataExtraction OneReach Delivery Log Schema
-- =============================================================================
-- Purpose:
--   Creates immutable audit log table for outbound OneReach.ai delivery events:
--   - Tracks lead dispatch attempts, delivery status, and webhook response codes.
--   - Supports exponential backoff tracking and DLQ correlation.
-- =============================================================================

CREATE TABLE IF NOT EXISTS master_dataextraction.onereach_delivery_log (
    delivery_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id VARCHAR(100),
    channel VARCHAR(50) NOT NULL DEFAULT 'WEBHOOK',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    delivery_status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    http_status INT,
    response_body TEXT,
    attempt_count INT NOT NULL DEFAULT 1,
    signature VARCHAR(128),
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_onereach_log_status ON master_dataextraction.onereach_delivery_log (delivery_status);
CREATE INDEX IF NOT EXISTS idx_onereach_log_lead ON master_dataextraction.onereach_delivery_log (lead_id);
CREATE INDEX IF NOT EXISTS idx_onereach_log_created ON master_dataextraction.onereach_delivery_log (created_at DESC);

-- Backward compatibility view in public schema
CREATE OR REPLACE VIEW public.onereach_delivery_log AS
SELECT * FROM master_dataextraction.onereach_delivery_log;

GRANT SELECT, INSERT, UPDATE ON master_dataextraction.onereach_delivery_log TO PUBLIC;
GRANT SELECT ON public.onereach_delivery_log TO PUBLIC;

