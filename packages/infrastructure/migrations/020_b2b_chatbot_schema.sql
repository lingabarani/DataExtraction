-- ==============================================================================
-- Migration: 020_b2b_chatbot_schema.sql
-- Description: Schema and tables for B2B Conversational Intelligence Chatbot,
--              interactive sessions, execution runs, and discovery review queue.
-- Schema: chat_dataextraction
-- Idempotent: safe to run multiple times.
-- ==============================================================================

CREATE SCHEMA IF NOT EXISTS chat_dataextraction;

-- ------------------------------------------------------------------------------
-- 1. Chat Sessions Table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_dataextraction.chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(100) NOT NULL DEFAULT 'anonymous',
    title VARCHAR(255) NOT NULL DEFAULT 'New Conversation',
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON chat_dataextraction.chat_sessions (user_id, updated_at DESC);

-- ------------------------------------------------------------------------------
-- 2. Chat Messages Table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_dataextraction.chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_dataextraction.chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    structured_plan JSONB,
    search_run_id UUID,
    completeness_report JSONB,
    results_summary JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_dataextraction.chat_messages (session_id, created_at ASC);

-- ------------------------------------------------------------------------------
-- 3. Chat Execution Runs Table
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_dataextraction.chat_execution_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_dataextraction.chat_sessions(id) ON DELETE CASCADE,
    message_id UUID REFERENCES chat_dataextraction.chat_messages(id) ON DELETE CASCADE,
    run_type VARCHAR(50) NOT NULL CHECK (run_type IN ('database_only', 'live_discovery_fallback', 'followup_filter')),
    status VARCHAR(50) NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
    plan JSONB NOT NULL DEFAULT '{}'::jsonb,
    db_matches_count INTEGER DEFAULT 0,
    discovered_matches_count INTEGER DEFAULT 0,
    timings JSONB DEFAULT '{}'::jsonb,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_chat_execution_runs_session ON chat_dataextraction.chat_execution_runs (session_id, started_at DESC);

-- ------------------------------------------------------------------------------
-- 4. Chat Review Items Table (Staging Area for Discovered Information)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_dataextraction.chat_review_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_dataextraction.chat_sessions(id) ON DELETE CASCADE,
    run_id UUID REFERENCES chat_dataextraction.chat_execution_runs(id) ON DELETE SET NULL,
    company_id VARCHAR(255) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    field_name VARCHAR(100) NOT NULL,
    existing_value JSONB,
    discovered_value JSONB NOT NULL,
    source_url TEXT,
    source_type VARCHAR(100) NOT NULL,
    evidence TEXT,
    field_confidence REAL DEFAULT 0.8,
    verification_status VARCHAR(50) NOT NULL DEFAULT 'UNVERIFIED'
        CHECK (verification_status IN ('UNVERIFIED', 'VERIFIED', 'CONFLICTING')),
    conflict_details JSONB,
    review_status VARCHAR(50) NOT NULL DEFAULT 'PENDING'
        CHECK (review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'NEEDS_INVESTIGATION')),
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMPTZ,
    rejection_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_review_status ON chat_dataextraction.chat_review_items (review_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_review_company ON chat_dataextraction.chat_review_items (company_id, field_name);
CREATE INDEX IF NOT EXISTS idx_chat_review_session ON chat_dataextraction.chat_review_items (session_id);
