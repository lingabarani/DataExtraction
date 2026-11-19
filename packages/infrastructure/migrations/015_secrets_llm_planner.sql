-- =============================================================================
-- Migration 015: Secrets store, LLM usage ledger, autonomy planner audit
-- =============================================================================
-- Idempotent: safe to run more than once.
-- api_keys.ciphertext holds Fernet-encrypted values. Plaintext is never stored.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS ops_dataextraction;

-- ── 1. api_keys ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ops_dataextraction.api_keys (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider            VARCHAR(50)  NOT NULL,
    label               VARCHAR(120) NOT NULL DEFAULT '',
    ciphertext          TEXT         NOT NULL,
    last4               VARCHAR(8)   NOT NULL DEFAULT '',
    status              VARCHAR(20)  NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'disabled', 'invalid', 'expired')),
    priority            INTEGER      NOT NULL DEFAULT 100,
    expires_at          TIMESTAMPTZ,
    cooldown_until      TIMESTAMPTZ,
    daily_token_quota   BIGINT,
    fail_count          INTEGER      NOT NULL DEFAULT 0,
    last_used_at        TIMESTAMPTZ,
    created_by          VARCHAR(255),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_provider_status
    ON ops_dataextraction.api_keys (provider, status);

-- ── 2. llm_usage ─────────────────────────────────────────────────────────────
-- Never stores prompt or completion text. Counters only.
CREATE TABLE IF NOT EXISTS ops_dataextraction.llm_usage (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    provider            VARCHAR(50)  NOT NULL,
    model               VARCHAR(120),
    key_id              UUID,
    purpose             VARCHAR(80),
    prompt_tokens       INTEGER      NOT NULL DEFAULT 0,
    completion_tokens   INTEGER      NOT NULL DEFAULT 0,
    latency_ms          INTEGER,
    status_code         INTEGER,
    success             BOOLEAN      NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_ts ON ops_dataextraction.llm_usage (ts DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_key ON ops_dataextraction.llm_usage (key_id, ts DESC);

-- ── 3. planner_decisions ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ops_dataextraction.planner_decisions (
    id                  BIGSERIAL PRIMARY KEY,
    ts                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    mode                VARCHAR(20)  NOT NULL,          -- 'llm' | 'fallback'
    dry_run             BOOLEAN      NOT NULL DEFAULT FALSE,
    llm_provider        VARCHAR(50),
    llm_model           VARCHAR(120),
    inputs_json         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    plan_json           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    executed_json       JSONB        NOT NULL DEFAULT '[]'::jsonb,
    rejected_json       JSONB        NOT NULL DEFAULT '[]'::jsonb,
    note                TEXT
);

CREATE INDEX IF NOT EXISTS idx_planner_decisions_ts ON ops_dataextraction.planner_decisions (ts DESC);
