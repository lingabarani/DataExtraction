# Gap Analysis: OneExtraction vs. G-Map-Scrapper

**Date**: November 1, 2026  
**Auditor**: Principal Software Architect & Staff Engineer  
**Objective**: Comprehensive Defect, Architecture, and Capability Gap Identification  

---

## 1. Executive Summary of Gaps

While `OneExtraction` contains a partial import of the Google Maps scraper inside `packages/scrapers/google_maps/`, this import represents an **early, incomplete snapshot**.

Critical production features present in `G-Map-Scrapper-main`—including anti-bot identity rotation, cluster deduplication, raw discovery staging, concurrent multi-category orchestration, and live streaming exports—are missing. Furthermore, the integration layer connecting Temporal workflows to the scraping engine is currently a hollow stub.

---

## 2. Detailed Gap Identification & Comparative Breakdown

### Gap 1: Hollow Temporal Activities (Critical Severity - P0)
- **Existing Implementation in OneExtraction**:
  - `packages/temporal/activities/gmaps_activities.py` defines `run_gmaps_collection_activity`.
  - In line 49-56, it instantiates `PipelineOrchestrator` and calls:
    ```python
    run_data = orchestrator.plan_pipeline(pipe_cfg)
    collected_count = run_data.get("tasks_total", 0)
    ```
  - It **never calls** `orchestrator.run_pipeline()` or `orchestrator.run_collection_tasks()`!
  - Similarly, `run_gmaps_website_verification_activity` and `run_gmaps_website_crawl_activity` merely query existing database count stats and return without executing any verification or crawl operations.
- **Implementation in G-Map-Scrapper**:
  - `PipelineOrchestrator.run_pipeline()` actively coordinates tasks across async worker pools, dispatches HTTP requests, writes records, updates progress, and flushes exports.
- **Architectural Risk**:
  - Workflows triggered via Temporal report `SUCCESS` immediately after scheduling zero-payload activities, extracting zero real data from Google Maps.
- **Recommendation**:
  - Rewrite `packages/temporal/activities/gmaps_activities.py` to invoke `orchestrator.run_pipeline_async()` or execute task queues with active heartbeat telemetry.

---

### Gap 2: Missing Cluster Deduplication Module (`dedup.py`) (High Severity - P0)
- **Existing Implementation in OneExtraction**:
  - `packages/scrapers/google_maps/src/gmaps_scraper/dedup.py` is **completely missing** (0 lines).
  - Target relies on standard SQLite `INSERT OR REPLACE INTO places` based on CID.
- **Implementation in G-Map-Scrapper**:
  - Contains `src/gmaps_scraper/dedup.py` (260 lines).
  - Provides `normalize_business_name()`, `normalize_url()`, and `merge_cluster_records()`.
  - Intelligently merges multi-category discovery events, selecting the longest verified business name, canonical address components, highest review counts, and combining category tags into unified multi-vertical sets.
- **Architectural Risk**:
  - Businesses found under multiple search categories overwrite previous attributes randomly, leading to data loss and inaccurate categorization.
- **Recommendation**:
  - Copy `dedup.py` directly into `packages/scrapers/google_maps/src/gmaps_scraper/dedup.py`.

---

### Gap 3: Missing Anti-Bot Protection & Identity Rotation (High Severity - P0)
- **Existing Implementation in OneExtraction**:
  - `http.py` is 185 lines. Uses static headers with basic retry logic.
- **Implementation in G-Map-Scrapper**:
  - `http.py` is 336 lines.
  - Implements `_BLOCK_SIGNALS` heuristics (`"sorry/index"`, `"recaptcha"`, `"unusual traffic"`, `"detected unusual"`).
  - Implements `IdentityRotator` to switch User-Agents, accept headers, and browser profiles dynamically upon soft-block or 429 status.
  - Employs jittered exponential backoff.
- **Architectural Risk**:
  - High-concurrency regional quadrant scans in OneExtraction will trigger Google CAPTCHA blocks within minutes, resulting in empty responses.
- **Recommendation**:
  - Replace `packages/scrapers/google_maps/src/gmaps_scraper/http.py` with the 336-line implementation from `G-Map-Scrapper`.

---

### Gap 4: Missing `raw_places` Staging & DB Methods (High Severity - P1)
- **Existing Implementation in OneExtraction**:
  - `db.py` contains 2,881 lines (66 methods).
  - Only writes directly to the canonical `places` table.
- **Implementation in G-Map-Scrapper**:
  - `db.py` contains 3,602 lines (76 methods).
  - 10 additional enterprise methods:
    1. `insert_raw_place()`
    2. `insert_raw_places_batch()`
    3. `get_raw_places()`
    4. `get_raw_places_count()`
    5. `get_places_count()`
    6. `get_collection_counts()`
    7. `reset_stale_running_tiles()`
    8. `reset_stale_inprogress_tasks()`
    9. `get_last_commit_timestamp()`
    10. `get_collection_progress_stats()`
  - Contains `raw_places` table for lossless staging and crash recovery (`reset_stale_running_tiles`).
- **Architectural Risk**:
  - Incomplete pipeline runs leave tiles stuck in `RUNNING` status indefinitely. Raw discoveries cannot be re-audited or re-clustered.
- **Recommendation**:
  - Replace `packages/scrapers/google_maps/src/gmaps_scraper/db.py` with the 3,602-line version.

---

### Gap 5: Artificial 50-Record Truncation & Lack of Parallel Category Workers (High Severity - P1)
- **Existing Implementation in OneExtraction**:
  - `orchestrator.py` hardcodes `collection_limit: int = 50`.
  - Runs business categories strictly sequentially.
- **Implementation in G-Map-Scrapper**:
  - `collection_limit` defaults to `None` (unlimited, exhaustive geographic discovery).
  - Features `category_workers` (parallel multi-category workers per state) with shared `request_concurrency` semaphore rate control.
  - Features `collection_only: bool` mode for high-throughput discovery without blocking on website crawl.
- **Architectural Risk**:
  - Scraping stops after 50 businesses per region, missing 99% of businesses in any given metropolitan area.
- **Recommendation**:
  - Replace `orchestrator.py` with the 1,671-line version from `G-Map-Scrapper`.

---

### Gap 6: Missing Real-Time Streaming Exports & Terminal Live UI (Medium Severity - P2)
- **Existing Implementation in OneExtraction**:
  - `export.py` only exports at the conclusion of a pipeline run. If a job crashes midway, unexported records remain trapped in SQLite.
  - `cli.py` has basic static console tables.
- **Implementation in G-Map-Scrapper**:
  - `export.py` features `export_live_raw_places()` and periodic flush worker (`export_every_n_records=500`, `export_interval_seconds=30.0`).
  - `cli.py` features Rich Live tables, real-time metrics per category worker, and color-coded progress bars.
  - `web/templates/pipeline.html` and `runs.html` include live SSE streaming visualizers.
- **Recommendation**:
  - Replace `export.py`, `cli.py`, and the web templates with the enhanced versions.

---

### Gap 7: Missing Automated Test Suites (Medium Severity - P1)
- **Existing Implementation in OneExtraction**:
  - 19 test suites in `tests/unit/gmaps/`.
- **Implementation in G-Map-Scrapper**:
  - 24 test suites in `tests/`.
  - 5 missing test files in target:
    1. `test_collection_limit_removal.py`
    2. `test_date_wise_category_exports.py`
    3. `test_parallel_category_scraping.py`
    4. `test_raw_collection_and_dedup.py`
    5. `test_terminal_progress.py`
- **Architectural Risk**:
  - Regressions in concurrency, deduplication, and export partitioning go undetected during CI/CD.
- **Recommendation**:
  - Migrate the 5 missing test suites into `tests/unit/gmaps/`.

---

## 3. Summary Gap Matrix

| Component | In G-Map-Scrapper | In OneExtraction | Gap Classification | Action |
|---|---|---|---|---|
| `dedup.py` | 260 lines | 0 lines | **Missing Component** | Copy File |
| `http.py` | 336 lines (Anti-bot + Rotation) | 185 lines (Basic) | **Outdated / Incomplete** | Replace File |
| `db.py` | 3,602 lines (10 extra methods, raw_places) | 2,881 lines | **Outdated / Incomplete** | Replace File |
| `export.py` | 803 lines (Live periodic flush) | 514 lines | **Outdated / Incomplete** | Replace File |
| `orchestrator.py`| 1,671 lines (Parallel workers, unlimited) | 1,068 lines | **Outdated / Incomplete** | Replace File |
| `cli.py` | 2,121 lines (Rich Live UI) | 1,565 lines | **Outdated / Incomplete** | Replace File |
| `config.py` | 96 lines (Identity rotation params) | 87 lines | **Outdated / Incomplete** | Replace File |
| `web templates` | Live SSE stream & category monitor | Basic static views | **Outdated / Incomplete** | Replace Files |
| `gmaps_activities.py`| N/A | Calls `plan_pipeline` only | **Hollow Stub Implementation** | Rewrite Activity |
| `gmaps_scraper.py` | N/A | Returns mock dict | **Hollow Stub Wrapper** | Implement Wrapper |
| Unit Tests | 24 suites (214 tests) | 19 suites | **5 Test Suites Missing** | Copy Test Files |

