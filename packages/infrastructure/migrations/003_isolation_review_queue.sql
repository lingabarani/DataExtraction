-- ============================================================================
-- DataExtraction Database Migration 003: Three-Tier Isolation Review Queue
-- ============================================================================
-- Author: Principal Software Engineer & Enterprise Data Architect
-- Purpose:
--   Implements the 70% - 94.99% isolation bucket for entity resolution review.
--   Enforces auditable, non-destructive quarantine for ambiguous matches
--   without corrupting golden clusters or losing incoming source payloads.
-- ============================================================================

CREATE TABLE IF NOT EXISTS kg_resolution.isolation_review_queue (
    review_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type VARCHAR(50) NOT NULL DEFAULT 'organization',
    incoming_record_id VARCHAR(255) NOT NULL,
    incoming_source VARCHAR(100) NOT NULL,
    incoming_payload JSONB NOT NULL,
    candidate_canonical_id UUID,
    match_score NUMERIC(4, 3) NOT NULL,
    match_rule VARCHAR(100) NOT NULL,
    match_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    review_status VARCHAR(50) NOT NULL DEFAULT 'PENDING_REVIEW'
        CHECK (review_status IN ('PENDING_REVIEW', 'APPROVED_MERGE', 'REJECTED_SPLIT', 'DISMISSED')),
    reviewed_by VARCHAR(100),
    review_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    reviewed_at TIMESTAMPTZ
);

-- Index on status and score for high-throughput worker and operator dispatch
CREATE INDEX IF NOT EXISTS idx_isolation_review_status_score 
ON kg_resolution.isolation_review_queue (review_status, match_score DESC);

CREATE INDEX IF NOT EXISTS idx_isolation_review_candidate 
ON kg_resolution.isolation_review_queue (candidate_canonical_id);

CREATE INDEX IF NOT EXISTS idx_isolation_review_incoming 
ON kg_resolution.isolation_review_queue (incoming_source, incoming_record_id);

