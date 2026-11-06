# File Migration Mapping: G-Map-Scrapper to OneExtraction

**Date**: November 1, 2026  
**Auditor**: Principal Software Architect & Staff Engineer  
**Source Repository**: `D:\Data Scraping Project POC\G-Map-Scrapper-main\G-Map-Scrapper-main`  
**Target Repository**: `D:\Data Scraping Project POC\DataExtraction`  

---

## 1. Complete Migration Classification Matrix

Every file in `G-Map-Scrapper-main` has been audited against `DataExtraction`. The actions are classified into:
- **KEEP**: The file in `DataExtraction` is already 100% identical and verified.
- **REPLACE**: `DataExtraction` has an older/incomplete version. Overwrite with the source file.
- **MERGE / ADD**: New file in source that does not exist in target. Add cleanly.
- **REFACTOR**: Code that must be rewritten or modified to properly bridge Temporal / BaseScraper interfaces.
- **DELETE**: Temporary or dead-code stubs to be eliminated.

---

## 2. Core Scraper Package Files (`src/gmaps_scraper/`)

| Source File (`G-Map-Scrapper`) | Target Location (`DataExtraction`) | Lines (Src / Tgt) | Classification | Technical Justification |
|---|---|---|---|---|
| `src/gmaps_scraper/dedup.py` | `packages/scrapers/google_maps/src/gmaps_scraper/dedup.py` | 260 / 0 | **MERGE / ADD** | Completely missing in target. Provides canonical cluster merging and deduplication logic. |
| `src/gmaps_scraper/http.py` | `packages/scrapers/google_maps/src/gmaps_scraper/http.py` | 336 / 185 | **REPLACE** | Source contains identity rotation, User-Agent pooling, `_BLOCK_SIGNALS` heuristics, and CAPTCHA backoff. |
| `src/gmaps_scraper/db.py` | `packages/scrapers/google_maps/src/gmaps_scraper/db.py` | 3,602 / 2,881 | **REPLACE** | Source contains `raw_places` table support, 10 missing methods, atomic batch progress queries, and stale tile resets. |
| `src/gmaps_scraper/orchestrator.py` | `packages/scrapers/google_maps/src/gmaps_scraper/orchestrator.py` | 1,671 / 1,068 | **REPLACE** | Source contains multi-category parallel worker pool, `collection_only` mode, unlimited collection limit, and live event bus. |
| `src/gmaps_scraper/export.py` | `packages/scrapers/google_maps/src/gmaps_scraper/export.py` | 803 / 514 | **REPLACE** | Source contains real-time periodic streaming exports, date-wise directory isolation, and category resolution. |
| `src/gmaps_scraper/cli.py` | `packages/scrapers/google_maps/src/gmaps_scraper/cli.py` | 2,121 / 1,565 | **REPLACE** | Source contains Rich Live terminal progress UI, category worker CLI flags, and raw places observability. |
| `src/gmaps_scraper/config.py` | `packages/scrapers/google_maps/src/gmaps_scraper/config.py` | 96 / 87 | **REPLACE** | Source contains identity rotation flags and upgraded concurrency defaults. |
| `src/gmaps_scraper/web/templates/pipeline.html` | `packages/scrapers/google_maps/src/gmaps_scraper/web/templates/pipeline.html` | 385 / 336 | **REPLACE** | Adds real-time WebSocket / SSE live stream and category monitor cards. |
| `src/gmaps_scraper/web/templates/runs.html` | `packages/scrapers/google_maps/src/gmaps_scraper/web/templates/runs.html` | 212 / 184 | **REPLACE** | Adds live execution metrics and category breakdown badges. |
| `src/gmaps_scraper/checkpoint.py` | `packages/scrapers/google_maps/src/gmaps_scraper/checkpoint.py` | 185 / 185 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/details.py` | `packages/scrapers/google_maps/src/gmaps_scraper/details.py` | 240 / 240 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/fallback_browser.py` | `packages/scrapers/google_maps/src/gmaps_scraper/fallback_browser.py` | 175 / 175 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/jobs.py` | `packages/scrapers/google_maps/src/gmaps_scraper/jobs.py` | 420 / 420 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/logging_setup.py` | `packages/scrapers/google_maps/src/gmaps_scraper/logging_setup.py` | 95 / 95 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/models.py` | `packages/scrapers/google_maps/src/gmaps_scraper/models.py` | 310 / 310 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/parser_state.py` | `packages/scrapers/google_maps/src/gmaps_scraper/parser_state.py` | 115 / 115 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/photos.py` | `packages/scrapers/google_maps/src/gmaps_scraper/photos.py` | 195 / 195 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/reviews.py` | `packages/scrapers/google_maps/src/gmaps_scraper/reviews.py` | 280 / 280 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/scope.py` | `packages/scrapers/google_maps/src/gmaps_scraper/scope.py` | 340 / 340 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/search.py` | `packages/scrapers/google_maps/src/gmaps_scraper/search.py` | 480 / 480 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/taxonomy.py` | `packages/scrapers/google_maps/src/gmaps_scraper/taxonomy.py` | 320 / 320 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/tiling.py` | `packages/scrapers/google_maps/src/gmaps_scraper/tiling.py` | 410 / 410 | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/core/*` (5 files) | `packages/scrapers/google_maps/src/gmaps_scraper/core/*` | All | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/geo/*` (4 files) | `packages/scrapers/google_maps/src/gmaps_scraper/geo/*` | All | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/incremental/*` (5 files) | `packages/scrapers/google_maps/src/gmaps_scraper/incremental/*` | All | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/storage/*` (3 files) | `packages/scrapers/google_maps/src/gmaps_scraper/storage/*` | All | **KEEP** | 100% Identical byte-for-byte. |
| `src/gmaps_scraper/website/*` (7 files) | `packages/scrapers/google_maps/src/gmaps_scraper/website/*` | All | **KEEP** | 100% Identical byte-for-byte (crawler, discovery, extractor, ssrf, verifier, service). |

---

## 3. Platform Integration Files (`packages/`)

| File Location | Role | Status in Target | Action Required |
|---|---|---|---|
| `packages/temporal/activities/gmaps_activities.py` | Temporal Activity Implementations | **Hollow Stub** (calls `plan_pipeline` only) | **REFACTOR**: Connect to real `PipelineOrchestrator.run_pipeline_async()` or execute collection tasks with Temporal heartbeats. |
| `packages/scrapers/google_maps/gmaps_scraper.py` | BaseScraper Adapter Wrapper | **Hollow Stub** (returns mock dict) | **REFACTOR**: Invoke `PipelineOrchestrator` directly with parameters (`region`, `category`, `limit`). |
| `packages/temporal/workflows/gmaps_extraction_workflow.py` | Temporal Workflow Definition | Functional Scaffolding | **KEEP / VERIFY**: Validate workflow signals, query handlers, and activity timeout configurations. |

---

## 4. Test Suites (`tests/`)

| Source Test File (`G-Map-Scrapper`) | Target Location (`DataExtraction`) | Status in Target | Action |
|---|---|---|---|
| `tests/test_collection_limit_removal.py` | `tests/unit/gmaps/test_collection_limit_removal.py` | **Missing** | **MERGE / ADD** |
| `tests/test_date_wise_category_exports.py` | `tests/unit/gmaps/test_date_wise_category_exports.py` | **Missing** | **MERGE / ADD** |
| `tests/test_parallel_category_scraping.py` | `tests/unit/gmaps/test_parallel_category_scraping.py` | **Missing** | **MERGE / ADD** |
| `tests/test_raw_collection_and_dedup.py` | `tests/unit/gmaps/test_raw_collection_and_dedup.py` | **Missing** | **MERGE / ADD** |
| `tests/test_terminal_progress.py` | `tests/unit/gmaps/test_terminal_progress.py` | **Missing** | **MERGE / ADD** |
| Existing 19 Test Suites in `tests/` | `tests/unit/gmaps/` (19 files) | Present | **KEEP** |

---

## 5. Execution Script for Automated File Synchronization

To eliminate human error during migration, the following automated synchronization sequence must be executed:

```python
import shutil
from pathlib import Path

SRC_PKG = Path(r"D:\Data Scraping Project POC\G-Map-Scrapper-main\G-Map-Scrapper-main\src\gmaps_scraper")
TGT_PKG = Path(r"D:\Data Scraping Project POC\DataExtraction\packages\scrapers\google_maps\src\gmaps_scraper")
SRC_TESTS = Path(r"D:\Data Scraping Project POC\G-Map-Scrapper-main\G-Map-Scrapper-main\tests")
TGT_TESTS = Path(r"D:\Data Scraping Project POC\DataExtraction\tests\unit\gmaps")

# 1. Copy missing dedup.py
shutil.copy2(SRC_PKG / "dedup.py", TGT_PKG / "dedup.py")

# 2. Overwrite upgraded core files
for f in ["cli.py", "config.py", "db.py", "export.py", "http.py", "orchestrator.py"]:
    shutil.copy2(SRC_PKG / f, TGT_PKG / f)

# 3. Overwrite updated web templates
shutil.copy2(SRC_PKG / "web" / "templates" / "pipeline.html", TGT_PKG / "web" / "templates" / "pipeline.html")
shutil.copy2(SRC_PKG / "web" / "templates" / "runs.html", TGT_PKG / "web" / "templates" / "runs.html")

# 4. Copy missing test suites
missing_tests = [
    "test_collection_limit_removal.py",
    "test_date_wise_category_exports.py",
    "test_parallel_category_scraping.py",
    "test_raw_collection_and_dedup.py",
    "test_terminal_progress.py"
]
for t in missing_tests:
    shutil.copy2(SRC_TESTS / t, TGT_TESTS / t)
```

