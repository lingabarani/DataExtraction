# ADR-005: Google Maps Platform Integration Strategy

**Status:** Accepted
**Date:** October 2026
**Deciders:** Platform Engineering, Finance

---

## Context

The platform has two existing sources for Google Maps data:
1. **gmaps-scraper** — local, zero external API cost, uses direct Maps protobuf endpoints
2. **openmap_engine** — OSM/OpenStreetMap for geographic context

A question arose: should we also integrate the **Google Maps Platform (GMP) APIs** (Places API New, Geocoding API, etc.) into the pipeline?

## Decision

**Google Maps Platform APIs are used ONLY for lead enrichment — not for primary discovery.**

```
Primary Discovery (zero cost):
  gmaps-scraper → local protobuf scraping (existing, unchanged)
  openmap_engine → OSM state extraction (existing, unchanged)

Enrichment Only (optional, cost-controlled):
  Google Places API (New) → fill in missing phone/website for discovered leads
```

### When GMP Enrichment Triggers

A lead is eligible for GMP enrichment ONLY if ALL of these are true:
1. Lead was discovered via gmaps-scraper or OSM (not via federal scraper)
2. Lead is missing `phone` OR `website`
3. GMP enrichment is enabled (`GOOGLE_MAPS_ENRICHMENT_ENABLED=true`)
4. Daily spend budget has not been reached (`GOOGLE_MAPS_DAILY_BUDGET_USD`)
5. Lead's `place_id` has no cached result younger than `GOOGLE_MAPS_CACHE_TTL_DAYS`

This means GMP is **off by default** and never runs automatically without explicit configuration.

### GMP Cost Controls

| Control | Implementation |
|:--------|:--------------|
| Field masks | Request only: `displayName,nationalPhoneNumber,websiteUri` — ~$0.003/call |
| Daily budget cap | `GOOGLE_MAPS_DAILY_BUDGET_USD=50.0` — ResourceManagerAgent enforces hard stop |
| Result caching | `place_id` → enrichment result cached in PostgreSQL for 30 days |
| Enabled flag | `GOOGLE_MAPS_ENRICHMENT_ENABLED=false` — default OFF in all environments |
| Temporal activity | Budget check runs as pre-condition activity; workflow aborts if budget exceeded |

### GMP Field Mask (Cheapest Possible Request)

```python
# packages/temporal/activities/gmaps_enrichment_activity.py
fields = "places.displayName,places.nationalPhoneNumber,places.websiteUri"
# Cost: Basic Data SKU ≈ $0.003/request
# NOT requested: photos, reviews, hours, atmosphereData (would 10× the cost)
```

### Routing Architecture

```
GMapsExtractionWorkflow
  └── run_gmaps_collection_activity      (local scraper, $0 cost)
  └── run_gmaps_website_verification_activity (local, $0 cost)
  └── check_enrichment_budget_activity   (reads budget remaining)
      └── [IF budget > 0 AND enabled]
          └── run_gmp_enrichment_activity  (GMP API call, ~$0.003/lead)
```

### Why Not Use GMP as Primary Discovery

| Factor | GMP Primary | gmaps-scraper Primary |
|:-------|:------------|:----------------------|
| Cost per 1M records | ~$3,000 | $0 |
| Daily quota limits | Yes (Maps API quotas) | No external quota |
| Geographic coverage | GMP limits | Configurable via tile grid |
| Rate limits | Yes | Self-controlled |
| Existing implementation | None | ✅ Complete, tested (100 tests) |

## Consequences

- **Positive:** Primary discovery remains zero API cost
- **Positive:** GMP enrichment provides a high-quality fallback for missing contact data
- **Positive:** Hard budget cap and off-by-default flag prevent accidental large charges
- **Negative:** GMP enrichment adds latency to the pipeline for affected leads
- **Mitigation:** Enrichment runs as a parallel optional stage — it doesn't block lead delivery
