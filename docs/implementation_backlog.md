# Implementation Backlog: Google Maps Engine Integration

**Date**: November 1, 2026  
**Auditor**: Principal Software Architect & Staff Engineer  
**Target Repository**: `DataExtraction` (`OneExtraction`)  

---

## 1. Backlog Overview

| Priority | Task ID | Title | Complexity | Risk |
|---|---|---|---|---|
| **P0** | GMAP-001 | Sync Authoritative Scraper Package Core Files | Medium | Low |
| **P0** | GMAP-002 | Integrate Deduplication Clustering (`dedup.py`) | Medium | Low |
| **P0** | GMAP-003 | Refactor Hollow Temporal Collection & Crawl Activities | High | Medium |
| **P0** | GMAP-004 | Implement Concrete `GMapsScraper.scrape()` Wrapper | Low | Low |
| **P1** | GMAP-005 | Migrate Missing Automated Test Suites | Medium | Low |
| **P1** | GMAP-006 | Upgrade Database Schema with `raw_places` & Stale Lease Recovery | Medium | Low |
| **P1** | GMAP-007 | Expose Multi-Category Worker Concurrency via FastAPI Gateway | Medium | Low |
| **P2** | GMAP-008 | Enable Real-Time SSE & Terminal Live Streaming UI | Medium | Low |
| **P2** | GMAP-009 | Build Postgres Warehouse Auto-Sync Worker | High | Medium |

---

## 2. P0 - Critical Tasks (Must Be Completed in Next Sprint)

### Task GMAP-001: Sync Authoritative Scraper Package Core Files
- **Objective**: Overwrite outdated core engine files in `packages/scrapers/google_maps/src/gmaps_scraper/` with the authoritative versions from `G-Map-Scrapper-main`.
- **Files Impacted**:
  - `packages/scrapers/google_maps/src/gmaps_scraper/http.py` (336 lines)
  - `packages/scrapers/google_maps/src/gmaps_scraper/config.py` (96 lines)
  - `packages/scrapers/google_maps/src/gmaps_scraper/db.py` (3,602 lines)
  - `packages/scrapers/google_maps/src/gmaps_scraper/export.py` (803 lines)
  - `packages/scrapers/google_maps/src/gmaps_scraper/orchestrator.py` (1,671 lines)
  - `packages/scrapers/google_maps/src/gmaps_scraper/cli.py` (2,121 lines)
- **Dependencies**: None.
- **Risk Level**: Low (Source is proven with 214 passing cleanroom tests).
- **Complexity**: Medium.
- **Acceptance Criteria**:
  1. `http.py` includes `IdentityRotator` and `_BLOCK_SIGNALS`.
  2. `db.py` provides all 76 database methods including `insert_raw_places_batch()`.
  3. `orchestrator.py` supports `category_workers` and unlimited `collection_limit=None`.
  4. All imports within `gmaps_scraper` resolve cleanly.

---

### Task GMAP-002: Integrate Deduplication Clustering (`dedup.py`)
- **Objective**: Add `dedup.py` from `G-Map-Scrapper-main` to `packages/scrapers/google_maps/src/gmaps_scraper/`.
- **Files Impacted**:
  - `packages/scrapers/google_maps/src/gmaps_scraper/dedup.py` (NEW)
- **Dependencies**: GMAP-001 (`db.py` and `models.py`).
- **Risk Level**: Low.
- **Complexity**: Medium.
- **Acceptance Criteria**:
  1. `dedup.py` functions `normalize_business_name()`, `normalize_url()`, and `merge_cluster_records()` unit tests pass.
  2. Running cluster deduplication merges multi-category discovery records into canonical `places` without data corruption.

---

### Task GMAP-003: Refactor Hollow Temporal Collection & Crawl Activities
- **Objective**: Replace the planning-only stubs in `packages/temporal/activities/gmaps_activities.py` with actual execution calls to `PipelineOrchestrator`, `WebsiteDiscoveryService`, and website crawler.
- **Files Impacted**:
  - `packages/temporal/activities/gmaps_activities.py`
  - `packages/temporal/workflows/gmaps_extraction_workflow.py`
- **Dependencies**: GMAP-001, GMAP-002.
- **Risk Level**: Medium (Async execution within Temporal activity loop).
- **Complexity**: High.
- **Acceptance Criteria**:
  1. `run_gmaps_collection_activity` invokes `orchestrator.run_collection_tasks()` or `run_pipeline()`.
  2. Activity sends periodic heartbeats (`activity.heartbeat(...)`) every 10 seconds to prevent Temporal activity timeouts.
  3. Output dictionary returns actual count of unique places collected and saved to SQLite/Postgres.
  4. Cancellation signals sent to Temporal gracefully cancel active category workers.

---

### Task GMAP-004: Implement Concrete `GMapsScraper.scrape()` Wrapper
- **Objective**: Convert `packages/scrapers/google_maps/gmaps_scraper.py` from a return-mock stub into a functional invocation of `PipelineOrchestrator`.
- **Files Impacted**:
  - `packages/scrapers/google_maps/gmaps_scraper.py`
- **Dependencies**: GMAP-001.
- **Risk Level**: Low.
- **Complexity**: Low.
- **Acceptance Criteria**:
  1. Calling `GMapsScraper().scrape(region="US-CA", vertical="healthcare", limit=20)` collects 20 records and returns real summary metadata.
  2. Adheres to `BaseScraper` contract (respects circuit breaker and rate limits).

---

## 3. P1 - Important Tasks

### Task GMAP-005: Migrate Missing Automated Test Suites
- **Objective**: Copy the 5 missing test suites from `G-Map-Scrapper-main/tests` to `tests/unit/gmaps/`.
- **Files Impacted**:
  - `tests/unit/gmaps/test_collection_limit_removal.py`
  - `tests/unit/gmaps/test_date_wise_category_exports.py`
  - `tests/unit/gmaps/test_parallel_category_scraping.py`
  - `tests/unit/gmaps/test_raw_collection_and_dedup.py`
  - `tests/unit/gmaps/test_terminal_progress.py`
- **Dependencies**: GMAP-001, GMAP-002.
- **Risk Level**: Low.
- **Complexity**: Medium.
- **Acceptance Criteria**:
  1. `pytest tests/unit/gmaps/` executes all 24 test suites.
  2. 100% of non-live unit tests pass.

---

### Task GMAP-006: Upgrade Database Schema with `raw_places` & Stale Lease Recovery
- **Objective**: Ensure that SQLite databases created in `DataExtraction` execute migration scripts to add `raw_places`, add composite indexes, and call `reset_stale_running_tiles()` on startup.
- **Files Impacted**:
  - `packages/scrapers/google_maps/src/gmaps_scraper/db.py`
- **Dependencies**: GMAP-001.
- **Risk Level**: Low.
- **Complexity**: Medium.
- **Acceptance Criteria**:
  1. Table `raw_places` is created automatically with composite index on `(cid, collected_at)`.
  2. When a process restarts, tiles in `running` status with heartbeat older than 5 minutes are reset to `pending`.

---

### Task GMAP-007: Expose Multi-Category Worker Concurrency via FastAPI Gateway
- **Objective**: Expose `category_workers`, `request_concurrency`, and `collection_limit` parameters in `packages/api/routers/extraction_router.py`.
- **Files Impacted**:
  - `packages/api/routers/extraction_router.py`
  - `packages/api/models/`
- **Dependencies**: GMAP-003.
- **Risk Level**: Low.
- **Complexity**: Medium.
- **Acceptance Criteria**:
  1. POST `/api/v1/extract/gmaps` accepts `category_workers` (1..10) and `request_concurrency`.
  2. Request payload validation enforces sensible limits (max 10 workers to prevent host saturation).

---

## 4. P2 - Enhancements

### Task GMAP-008: Enable Real-Time SSE & Terminal Live Streaming UI
- **Objective**: Copy updated `pipeline.html` and `runs.html` and connect the FastAPI SSE event stream to the frontend portal.
- **Files Impacted**:
  - `packages/scrapers/google_maps/src/gmaps_scraper/web/templates/pipeline.html`
  - `packages/scrapers/google_maps/src/gmaps_scraper/web/templates/runs.html`
- **Dependencies**: GMAP-001.
- **Risk Level**: Low.
- **Complexity**: Medium.
- **Acceptance Criteria**:
  1. Dashboard displays real-time animated counters for places collected, verified, and enriched.

---

### Task GMAP-009: Build Postgres Warehouse Auto-Sync Worker
- **Objective**: Build an asynchronous sync worker that copies canonical `places` and contact records from SQLite regional partitions into the centralized PostgreSQL database.
- **Files Impacted**:
  - `packages/temporal/activities/gmaps_activities.py`
  - `packages/storage/postgres_sync.py`
- **Dependencies**: GMAP-003.
- **Risk Level**: Medium.
- **Complexity**: High.
- **Acceptance Criteria**:
  1. On activity completion, records in SQLite partition are upserted into PostgreSQL `companies` and `leads` tables.

