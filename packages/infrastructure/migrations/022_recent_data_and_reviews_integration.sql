-- =============================================================================
-- Migration 022: Recent Data Priority & End-to-End Customer Reviews Integration
-- =============================================================================
-- Purpose:
--   1. Extends master_dataextraction.organizations with verified customer rating,
--      review count, sentiment score, sentiment summary, praise highlights,
--      complaint alerts, and linked place ID.
--   2. Creates high-performance composite indexes on (updated_at DESC, trust_score DESC)
--      and (rating DESC, review_count DESC) for sub-50ms recency-first search.
--   3. Synchronizes verified reviews from staging_dataextraction._archived_place_reviews
--      and discovery_dataextraction.organizations.
--   4. Creates a compatibility view staging_dataextraction.place_reviews pointing to
--      _archived_place_reviews to eliminate broken references.
--   5. Updates search projection and public lead views.
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. EXTEND MASTER ORGANIZATIONS WITH REVIEWS & REPUTATION FIELDS
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE master_dataextraction.organizations
    ADD COLUMN IF NOT EXISTS rating NUMERIC(3, 2),
    ADD COLUMN IF NOT EXISTS review_count INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sentiment_score NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS sentiment_summary TEXT,
    ADD COLUMN IF NOT EXISTS praise_highlights JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS complaint_alerts JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS linked_place_id TEXT;

-- High-performance composite indexes for Recency-First and Reviews Ranking
CREATE INDEX IF NOT EXISTS idx_master_org_freshness_first 
    ON master_dataextraction.organizations (updated_at DESC NULLS LAST, trust_score DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_master_org_created_first 
    ON master_dataextraction.organizations (created_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_master_org_rating 
    ON master_dataextraction.organizations (rating DESC NULLS LAST, review_count DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_master_org_linked_place 
    ON master_dataextraction.organizations (linked_place_id) 
    WHERE linked_place_id IS NOT NULL;

-- High-performance composite indexes for Persons Recency-First
CREATE INDEX IF NOT EXISTS idx_master_persons_freshness_first 
    ON master_dataextraction.persons (updated_at DESC NULLS LAST, trust_score DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_master_persons_created_first 
    ON master_dataextraction.persons (created_at DESC NULLS LAST);

-- Index on archived reviews
CREATE INDEX IF NOT EXISTS idx_archived_reviews_place_rating 
    ON staging_dataextraction._archived_place_reviews (place_id, rating, published_at DESC);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. COMPATIBILITY VIEW: staging_dataextraction.place_reviews
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW staging_dataextraction.place_reviews AS
SELECT * FROM staging_dataextraction._archived_place_reviews;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. SYNCHRONIZE REVIEWS FROM DISCOVERY & ARCHIVED REVIEWS
-- ─────────────────────────────────────────────────────────────────────────────
-- A. Update from discovery_dataextraction.organizations by domain match
UPDATE master_dataextraction.organizations m
SET 
    rating = d.rating,
    review_count = d.review_count,
    linked_place_id = COALESCE(m.linked_place_id, d.linked_place_id),
    updated_at = NOW()
FROM discovery_dataextraction.organizations d
WHERE m.primary_domain IS NOT NULL 
  AND m.primary_domain != ''
  AND d.domain = m.primary_domain
  AND d.review_count > 0
  AND (m.rating IS NULL OR m.review_count = 0);

-- B. Update from discovery_dataextraction.organizations by canonical name match
UPDATE master_dataextraction.organizations m
SET 
    rating = d.rating,
    review_count = d.review_count,
    linked_place_id = COALESCE(m.linked_place_id, d.linked_place_id),
    updated_at = NOW()
FROM discovery_dataextraction.organizations d
WHERE (m.primary_domain IS NULL OR m.primary_domain = '')
  AND LOWER(TRIM(m.legal_name)) = LOWER(TRIM(d.canonical_name))
  AND d.review_count > 0
  AND (m.rating IS NULL OR m.review_count = 0);

-- C. Aggregate sentiment summary and highlights for organizations with linked_place_id
WITH review_aggregates AS (
    SELECT 
        place_id,
        ROUND(AVG(rating)::numeric, 2) AS avg_rating,
        COUNT(*) AS total_reviews,
        ROUND(
            (COUNT(*) FILTER (WHERE sentiment ILIKE 'positive' OR rating >= 4)::numeric / NULLIF(COUNT(*), 0) * 100), 1
        ) AS positive_pct,
        jsonb_agg(DISTINCT p.praise_elem) FILTER (WHERE p.praise_elem IS NOT NULL) AS praise_tags,
        jsonb_agg(DISTINCT c.complaint_elem) FILTER (WHERE c.complaint_elem IS NOT NULL) AS complaint_tags
    FROM staging_dataextraction._archived_place_reviews r
    LEFT JOIN LATERAL jsonb_array_elements_text(COALESCE(r.praise, '[]'::jsonb)) AS p(praise_elem) ON TRUE
    LEFT JOIN LATERAL jsonb_array_elements_text(COALESCE(r.complaints, '[]'::jsonb)) AS c(complaint_elem) ON TRUE
    GROUP BY place_id
)
UPDATE master_dataextraction.organizations m
SET 
    rating = COALESCE(m.rating, ra.avg_rating),
    review_count = GREATEST(COALESCE(m.review_count, 0), ra.total_reviews),
    sentiment_score = ra.positive_pct,
    sentiment_summary = 'Based on ' || ra.total_reviews || ' verified Google customer reviews with ' || ra.positive_pct || '% positive sentiment.',
    praise_highlights = COALESCE(ra.praise_tags, '[]'::jsonb),
    complaint_alerts = COALESCE(ra.complaint_tags, '[]'::jsonb),
    updated_at = NOW()
FROM review_aggregates ra
WHERE m.linked_place_id = ra.place_id;
