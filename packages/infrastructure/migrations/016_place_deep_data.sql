-- =============================================================================
-- Migration 016: Deep place data (details, services, reviews, contacts, people)
-- =============================================================================
-- Idempotent. All tables upsert on natural keys so re-scraping never duplicates.
-- Every row carries source, source_url, scraped_at, run_id.
-- place_id is the Google Maps cid (string) used by the existing scraper.
-- company_id optionally links to staging_dataextraction.staging_companies.id.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS staging_dataextraction;

-- ── 1. place_details ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS staging_dataextraction.place_details (
    place_id        TEXT PRIMARY KEY,
    ftid            TEXT,
    company_id      TEXT,
    name            TEXT,
    categories      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    address         TEXT,
    street_address  TEXT,
    city            TEXT,
    region          TEXT,
    postal_code     TEXT,
    country_code    VARCHAR(8),
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    phone           TEXT,
    website         TEXT,
    rating          NUMERIC(3,2),
    review_count    INTEGER,
    price_level     TEXT,
    timezone        TEXT,
    claimed_status  INTEGER,
    hours           JSONB        NOT NULL DEFAULT '[]'::jsonb,
    attributes      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    photo_urls      JSONB        NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(20)  NOT NULL DEFAULT 'complete',  -- complete | partial | blocked
    source          VARCHAR(50)  NOT NULL DEFAULT 'GOOGLE_MAPS',
    source_url      TEXT,
    run_id          TEXT,
    scraped_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_place_details_company ON staging_dataextraction.place_details (company_id);
CREATE INDEX IF NOT EXISTS idx_place_details_scraped ON staging_dataextraction.place_details (scraped_at DESC);

-- ── 2. place_services ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS staging_dataextraction.place_services (
    id              BIGSERIAL PRIMARY KEY,
    place_id        TEXT         NOT NULL,
    group_name      TEXT         NOT NULL DEFAULT '',
    service_name    TEXT         NOT NULL,
    is_enabled      BOOLEAN      NOT NULL DEFAULT TRUE,
    display_value   TEXT,
    origin          VARCHAR(20)  NOT NULL DEFAULT 'attribute',  -- attribute | llm
    source          VARCHAR(50)  NOT NULL DEFAULT 'GOOGLE_MAPS',
    source_url      TEXT,
    run_id          TEXT,
    scraped_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_place_services UNIQUE (place_id, group_name, service_name)
);

CREATE INDEX IF NOT EXISTS idx_place_services_place ON staging_dataextraction.place_services (place_id);

-- ── 3. place_reviews ─────────────────────────────────────────────────────────
-- reviewer_name holds the plain name only when REVIEWER_NAME_MODE=plain,
-- otherwise a salted SHA-256 hash (reviewer_name_hash) and reviewer_name is NULL.
CREATE TABLE IF NOT EXISTS staging_dataextraction.place_reviews (
    id                  BIGSERIAL PRIMARY KEY,
    place_id            TEXT         NOT NULL,
    review_id           TEXT         NOT NULL,
    reviewer_name       TEXT,
    reviewer_name_hash  VARCHAR(64),
    reviewer_id         TEXT,
    rating              SMALLINT,
    review_text         TEXT,
    language            VARCHAR(16),
    published_at        TIMESTAMPTZ,
    relative_date       TEXT,
    owner_response_text TEXT,
    owner_response_date TEXT,
    reaction_count      INTEGER      NOT NULL DEFAULT 0,
    photo_urls          JSONB        NOT NULL DEFAULT '[]'::jsonb,
    sentiment           VARCHAR(16),
    topics              JSONB        NOT NULL DEFAULT '[]'::jsonb,
    source              VARCHAR(50)  NOT NULL DEFAULT 'GOOGLE_MAPS',
    source_url          TEXT,
    run_id              TEXT,
    scraped_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_place_reviews UNIQUE (place_id, review_id)
);

CREATE INDEX IF NOT EXISTS idx_place_reviews_place ON staging_dataextraction.place_reviews (place_id);
CREATE INDEX IF NOT EXISTS idx_place_reviews_published ON staging_dataextraction.place_reviews (published_at DESC);

-- ── 4. place_contacts ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS staging_dataextraction.place_contacts (
    id                  BIGSERIAL PRIMARY KEY,
    place_id            TEXT         NOT NULL,
    contact_type        VARCHAR(20)  NOT NULL,   -- email | phone | social | address
    value               TEXT         NOT NULL,
    label               TEXT,
    extraction_method   VARCHAR(20)  NOT NULL DEFAULT 'regex',  -- regex | llm | maps
    source              VARCHAR(50)  NOT NULL DEFAULT 'GOOGLE_MAPS',
    source_url          TEXT,
    run_id              TEXT,
    scraped_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_place_contacts UNIQUE (place_id, contact_type, value)
);

CREATE INDEX IF NOT EXISTS idx_place_contacts_place ON staging_dataextraction.place_contacts (place_id);

-- ── 5. place_people ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS staging_dataextraction.place_people (
    id                  BIGSERIAL PRIMARY KEY,
    place_id            TEXT         NOT NULL,
    full_name           TEXT         NOT NULL,
    role_title          TEXT         NOT NULL DEFAULT '',
    email               TEXT,
    phone               TEXT,
    profile_url         TEXT,
    extraction_method   VARCHAR(20)  NOT NULL DEFAULT 'regex',
    source              VARCHAR(50)  NOT NULL DEFAULT 'GOOGLE_MAPS',
    source_url          TEXT,
    run_id              TEXT,
    scraped_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_place_people UNIQUE (place_id, full_name, role_title)
);

CREATE INDEX IF NOT EXISTS idx_place_people_place ON staging_dataextraction.place_people (place_id);

-- ── 6. place_extraction_runs ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS staging_dataextraction.place_extraction_runs (
    run_id          TEXT PRIMARY KEY,
    status          VARCHAR(20)  NOT NULL DEFAULT 'running',  -- running | complete | partial | blocked | failed
    requested       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    places_done     INTEGER      NOT NULL DEFAULT 0,
    reviews_saved   INTEGER      NOT NULL DEFAULT 0,
    error           TEXT,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ
);
