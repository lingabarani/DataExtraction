# Repository Comparison: G-Map-Scrapper vs. OneExtraction (DataExtraction)

**Date**: November 1, 2026  
**Auditor**: Principal Software Architect & Staff Engineer  
**Focus**: Google Maps Scraping & Geospatial Extraction Capabilities  

---

## 1. Executive Structural Comparison

| Dimension | G-Map-Scrapper-main (`G-Map-Scrapper`) | DataExtraction (`OneExtraction`) | Comparative Assessment |
|---|---|---|---|
| **Primary Focus** | Dedicated, high-throughput Google Maps internal RPC & Geospatial Scraping Engine with Web Crawling & Enrichment | Multi-source Enterprise Data Extraction Platform (LinkedIn, Glassdoor, G-Maps, Social, Enrichment, Temporal, Agents) | `G-Map-Scrapper` is a specialized, deep vertical engine; `OneExtraction` is a distributed monorepo enterprise platform. |
| **Monorepo Layout** | Standalone Single-Package Application (`src/gmaps_scraper/`) | Monorepo layout (`packages/scrapers/`, `packages/temporal/`, `packages/agents/`, `packages/api/`) | `OneExtraction` has target package structure at `packages/scrapers/google_maps/`. |
| **Engine Source Files** | 67 Python and HTML template files in package | 66 files in `packages/scrapers/google_maps/src/gmaps_scraper/` (Outdated snapshot) | Target is missing `dedup.py` and has older versions of 8 critical files. |
| **Orchestration** | Standalone AsyncIO + Multi-Worker Orchestrator with ThreadPool & Semaphores | Temporal IO Distributed Workflow Engine (`Workflow`, `Activity`, `Worker`) + Standalone Orchestrator | Target has Temporal scaffolding, but activities currently call planning stubs instead of execution methods. |
| **Google Maps API Method** | Reverse-engineered Google Maps Internal Protobuf/RPC endpoints (`search_rpc`, `place_details_rpc`, `reviews_rpc`) | Same Protobuf/RPC endpoints in embedded package, but wrapped in uninvoked wrappers | Both share the RPC parser core, but `G-Map-Scrapper` has active anti-bot and identity rotation. |
| **Anti-Bot & Proxying** | Identity rotation (`IdentityRotator`), User-Agent pool, CAPTCHA heuristic detection (`_BLOCK_SIGNALS`), jittered backoff | Basic HTTP client; identity rotation and CAPTCHA detection missing in target package snapshot | `G-Map-Scrapper` has far superior resilience against Google rate limiting and soft blocks. |
| **Deduplication** | Two-tier: Staging `raw_places` table + Cluster Deduplication Engine (`dedup.py`) resolving into canonical `places` | Single-tier direct upsert; missing `raw_places` staging table and `dedup.py` | `G-Map-Scrapper` guarantees zero loss of raw multi-category encounters while maintaining canonical purity. |
| **Data Storage** | SQLite with WAL mode, FTS5 full-text search, spatial bounding box indexing | SQLite in package + Centralized PostgreSQL / SQLAlchemy models in target platform | Target needs bridging between SQLite scraper state and platform PostgreSQL warehouse. |
| **Monitoring & Telemetry** | Rich Terminal Live tables, SSE web streaming, WebSocket event stream, Prometheus metrics | Prometheus metrics, OpenTelemetry, Logfire, Grafana, Temporal Heartbeats | Target platform has superior enterprise observability; scraper package has superior local terminal/feed UX. |
| **Test Suite** | 24 test suites (214 collected test cases), cleanroom acceptance tests | 19 test suites in `tests/unit/gmaps/`; 5 critical test suites omitted during initial copy | Target missing tests for collection limits, parallel category scraping, raw deduplication, terminal progress. |

---

## 2. Deep Module-by-Module Architectural Comparison

### 2.1. Module Structure & Packaging

```
G-Map-Scrapper-main/
├── config/
│   ├── countries.yaml              # US & MX country-level geographic boundaries
│   ├── default.yaml                # Core defaults (concurrency=10, per_host_rate=8.0)
│   ├── geo_spans.yaml              # Natural language bounding box spans
│   ├── pipeline2_regions.yaml      # Multi-state definitions
│   └── verticals.yaml              # 10 core business verticals & query taxonomies
├── src/gmaps_scraper/
│   ├── checkpoint.py               # JSON/SQLite execution state tracking
│   ├── cli.py                      # Typer CLI with Rich Live monitoring (2,121 lines)
│   ├── config.py                   # Pydantic BaseSettings with identity rotation (96 lines)
│   ├── db.py                       # SQLite Engine with raw_places & WAL (3,602 lines)
│   ├── dedup.py                    # Cluster Deduplication & Canonical Merging (260 lines) [MISSING IN TARGET]
│   ├── details.py                  # Place details RPC fetcher
│   ├── export.py                   # Date-wise, category-wise, live streaming export (803 lines)
│   ├── fallback_browser.py         # Playwright headless browser fallback
│   ├── http.py                     # HTTP client with anti-bot & identity rotation (336 lines)
│   ├── jobs.py                     # Background job manager
│   ├── logging_setup.py            # Structured logging
│   ├── models.py                   # Pydantic models for Place, Review, Contact, etc.
│   ├── orchestrator.py             # Multi-category parallel orchestrator (1,671 lines)
│   ├── parser_state.py             # Protobuf parsing state machine
│   ├── photos.py                   # Photo downloader & caching
│   ├── reviews.py                  # Reviews pagination & sentiment extraction
│   ├── scope.py                    # Regional & category task resolution
│   ├── search.py                   # Internal Google search RPC execution
│   ├── taxonomy.py                 # Multi-tier vertical categorization & business dimensions
│   ├── tiling.py                   # Quadrant recursive spatial subdivision
│   ├── core/                       # RPC clients, Protobuf parsers, response decoders
│   ├── geo/                        # Boundaries, coordinates, spatial indexing, quadtrees
│   ├── incremental/                # Delta diffing, entity comparison, contact updates
│   ├── storage/                    # Data synchronization & multi-database management
│   ├── web/                        # FastAPI dashboard, templates, SSE/WebSocket endpoints
│   └── website/                    # Crawler, discovery, SSRF protection, email/phone extractor
└── tests/                          # 24 test suites, 214 test cases
```

```
DataExtraction/ (OneExtraction)
├── packages/
│   ├── scrapers/
│   │   ├── base_scraper.py         # Abstract base scraper (rate limiting, circuit breaker, budget)
│   │   ├── google_maps/
│   │   │   ├── gmaps_scraper.py    # Wrapper inheriting BaseScraper (CURRENTLY A STUB)
│   │   │   ├── config/             # YAML configs (identical to G-Map-Scrapper)
│   │   │   └── src/gmaps_scraper/  # EMBEDDED ENGINE (66 files, older snapshot, missing dedup.py)
│   ├── temporal/
│   │   ├── activities/
│   │   │   └── gmaps_activities.py # Temporal activities (CURRENTLY CALLS PLAN_PIPELINE ONLY)
│   │   ├── workflows/
│   │   │   ├── gmaps_extraction_workflow.py # Temporal workflow definition
│   │   │   └── w2_geospatial_workflow.py    # Pipeline 2 orchestrator
│   │   └── workers/
│   │       ├── gmaps_worker.py     # Temporal worker listening on gmaps queue
│   │       └── worker_geospatial.py
│   ├── agents/                     # AI Coordinator, Quality Agent, Enrichment Agent
│   └── api/                        # FastAPI enterprise gateway routers
└── tests/
    └── unit/gmaps/                 # 19 test suites (5 missing compared to G-Map-Scrapper)
```

---

## 3. Core Architectural Subsystems

### 3.1. Scraping Engine & HTTP Layer
- **G-Map-Scrapper**:
  - `HttpClient` features an automated `IdentityRotator` that cycles browser-grade headers, user-agents, accept-languages, and client fingerprints.
  - Detects Google anti-bot soft-blocks and CAPTCHA redirects via `_BLOCK_SIGNALS` (`"sorry/index"`, `"recaptcha"`, `"unusual traffic"`).
  - Implements exponential backoff with jitter and retry handling up to 5 retries.
  - Rate limiting defaults to 8.0 req/sec with auto-throttling.
- **OneExtraction Target**:
  - `packages/scrapers/google_maps/src/gmaps_scraper/http.py` is an earlier 185-line version.
  - Lacks `_BLOCK_SIGNALS` detection, user agent rotation, and dynamic headers.
  - Will be blocked by Google much faster during high-concurrency quadrant scans.

### 3.2. Deduplication & Data Integrity
- **G-Map-Scrapper**:
  - Operates a two-stage deduplication pipeline:
    1. Raw search discoveries are saved immediately to `raw_places` table (preserving every raw sighting, timestamp, and query category).
    2. `dedup.py` performs cluster deduplication across CIDs, merging records by longest normalized name, best phone (preferring E.164), first valid coordinates, and aggregating multi-category memberships into canonical `places`.
- **OneExtraction Target**:
  - Lacks `dedup.py` entirely.
  - Direct upsert into `places` without raw staging or multi-attribute cluster merging.

### 3.3. Orchestration & Concurrency Model
- **G-Map-Scrapper**:
  - `orchestrator.py` (1,671 lines) supports `category_workers` (parallel multi-category workers per state) with a shared global semaphore `request_concurrency`.
  - Supports `collection_only` mode for high-speed raw extraction.
  - Supports unlimited collection (default limit is `None`, allowing quadrant tiling to exhaust all tiles).
  - Emits real-time SSE events (`event_bus`) for live UI streaming.
- **OneExtraction Target**:
  - `orchestrator.py` (1,068 lines) is strictly sequential per category.
  - Hardcodes `collection_limit=50`.
  - Lacks live event streaming and category concurrency.

### 3.4. Temporal Workflow Integration
- **G-Map-Scrapper**:
  - Standalone process runner. No Temporal dependencies.
- **OneExtraction Target**:
  - Contains Temporal definitions (`GMapsExtractionWorkflow`, `run_gmaps_collection_activity`, etc.).
  - **Critical Flaw Found**: `run_gmaps_collection_activity` only calls `orchestrator.plan_pipeline(pipe_cfg)`! It never calls `run_pipeline()` or `run_collection_tasks()`.
  - As a result, triggering the Temporal workflow in OneExtraction returns tasks planned, but collects zero actual Google Maps records!

---

## 4. Configuration Management

| Parameter | G-Map-Scrapper Default | OneExtraction Scraper Default | Recommended Production Value |
|---|---|---|---|
| `concurrency` | 10 | 5 | 10 |
| `category_workers` | 10 (parallel across categories) | 1 (sequential) | 5-10 depending on proxy pool |
| `request_concurrency` | 10 | Unset / 5 | 8-12 |
| `per_host_rate` | 8.0 req/sec | 2.0 req/sec | 5.0 - 8.0 req/sec |
| `max_retries` | 5 | 3 | 5 |
| `collection_limit` | `None` (unlimited exhaustive) | 50 (truncated) | Configurable (`None` for full runs) |
| `rotate_identity_on_block`| `True` | Not supported | `True` |

---

## 5. Storage & Export Capabilities

- **G-Map-Scrapper**:
  - Partitioned SQLite databases per region/state (`databases/US/California_CA.sqlite`, etc.) in addition to global `gmaps.sqlite`.
  - Full-Text Search (FTS5) virtual tables for sub-millisecond keyword lookup.
  - Live periodic export flushing (`export_every_n_records=500`, `export_interval_seconds=30.0`).
  - Hierarchical date-stamped exports (`exports/YYYY-MM-DD/US/California_CA/category.csv`).
- **OneExtraction Target**:
  - Retains the same file-based SQLite database layout within `packages/scrapers/google_maps/data/`.
  - Lacks live periodic streaming flush (`export_live_raw_places`).
  - Lacks database methods for raw places count and stale lease resets.

---

## 6. Conclusion & Verdict

`G-Map-Scrapper-main` is not merely an external repository; it is the **authoritative, advanced evolution** of the Google Maps scraping engine that was only partially and incompletely vendored into `OneExtraction`.

Integrating the enhanced components from `G-Map-Scrapper-main` into `OneExtraction` is **strictly mandatory** to achieve production-grade Google Maps extraction capabilities and resolve the hollow Temporal activity stubs.

