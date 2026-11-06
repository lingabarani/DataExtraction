-- DataExtraction Migration 011: Dead Letter Queue Schema
-- ========================================================
-- Provides persistent storage for failed ingestion, validation, or delivery payloads.
-- Multi-tier architecture: Base table in staging_dataextraction, updatable view in public.

CREATE SCHEMA IF NOT EXISTS staging_dataextraction;

CREATE TABLE IF NOT EXISTS staging_dataextraction.dead_letter_queue (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(100),
    source_name VARCHAR(100) NOT NULL DEFAULT 'UNKNOWN_SOURCE',
    entity_type VARCHAR(50) NOT NULL DEFAULT 'company',
    raw_payload JSONB NOT NULL,
    error_reason TEXT NOT NULL,
    error_traceback TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    retry_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_retried_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_dlq_status_created ON staging_dataextraction.dead_letter_queue (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dlq_source ON staging_dataextraction.dead_letter_queue (source_name);

-- Public schema backward-compatibility updatable view
-- Allows legacy clients, workers, and pool connections with default search_path=public to query and mutate DLQ
CREATE OR REPLACE VIEW public.dead_letter_queue AS
SELECT * FROM staging_dataextraction.dead_letter_queue;
