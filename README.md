# DataExtraction — Enterprise Data Extraction Platform

> **Production-grade monorepo** consolidating multi-source data scraping, Temporal durable orchestration, and AI agent-driven pipeline management.

[![CI Backend](https://github.com/your-org/DataExtraction/actions/workflows/ci-backend.yml/badge.svg)](https://github.com/your-org/DataExtraction/actions)
[![CI Frontend](https://github.com/your-org/DataExtraction/actions/workflows/ci-frontend.yml/badge.svg)](https://github.com/your-org/DataExtraction/actions)
[![Security](https://github.com/your-org/DataExtraction/actions/workflows/ci-security.yml/badge.svg)](https://github.com/your-org/DataExtraction/actions)

---

## Overview

DataExtraction is a unified enterprise platform for large-scale business data collection across:

- **Federal Registries** — CMS NPI, SEC EDGAR, FDIC, USASpending, ProPublica, SAM.gov
- **Google Maps** — Local business discovery via 4-quadrant spatial tiling (zero external API cost)
- **OpenStreetMap** — Geographic state-level extraction with circuit-breaker resilience
- **Lead Enrichment** — Normalization, deduplication, contact validation, and lead building

All scrapers operate **unchanged** from their original implementations. Temporal Workflows and AI Agents form the orchestration and intelligence layer on top.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     DataExtraction Platform                       │
│                                                                  │
│  ┌─────────────┐    ┌──────────────────────────────────────────┐│
│  │  Next.js 15  │    │           Temporal Server                ││
│  │  Dashboard   │    │  ┌────────────┐  ┌────────────────────┐ ││
│  │             │◄───►│  │  Workflows  │  │    Schedules       │ ││
│  │  /pipelines │    │  │  federal   │  │  daily/weekly/     │ ││
│  │  /agents    │    │  │  gmaps     │  │  monthly           │ ││
│  │  /schedules │    │  │  osm       │  └────────────────────┘ ││
│  └──────┬──────┘    │  │  master    │                          ││
│         │           │  └────────────┘                          ││
│  ┌──────▼──────┐    └───────────────┬──────────────────────────┘│
│  │  FastAPI    │                    │                            │
│  │  Backend    │    ┌───────────────▼──────────────────────────┐│
│  │  /api/v1    │    │            Temporal Workers               ││
│  └──────┬──────┘    │  federal-worker │ gmaps-worker           ││
│         │           │  osm-worker     │ pipeline-worker         ││
│  ┌──────▼──────┐    └───────────────┬──────────────────────────┘│
│  │ PostgreSQL  │                    │                            │
│  │ PostGIS     │◄───────────────────┤                            │
│  └─────────────┘    ┌──────────────▼──────────────────────────┐ │
│                     │         Scrapers (Unchanged)              │ │
│                     │  federal/ │ google_maps/ │ open_map/      │ │
│                     └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## Monorepo Structure

```
DataExtraction/
├── packages/
│   ├── scrapers/
│   │   ├── federal/          # 6 federal registry scrapers (UNTOUCHED)
│   │   ├── google_maps/      # gmaps-scraper complete project (UNTOUCHED)
│   │   └── open_map/         # OSM engine (UNTOUCHED)
│   ├── pipeline/             # Data transformation (UNTOUCHED)
│   ├── temporal/             # NEW: Durable workflow orchestration
│   │   ├── activities/       # Thin wrappers around existing scrapers
│   │   ├── workflows/        # FederalIngestion, GMaps, OSM, Master, DLQ
│   │   ├── schedules/        # Daily/weekly/monthly cron schedules
│   │   └── workers/          # Worker process launchers
│   ├── agents/               # NEW: AI agent framework
│   ├── api/                  # FastAPI backend (extended)
│   ├── infrastructure/       # Shared DB, config, logging, metrics
│   └── frontend/             # Next.js 15 dashboard (extended)
├── infra/                    # Docker, docker-compose, nginx
├── config/                   # Temporal, workers, schedules, agents config
├── scripts/                  # Migration, DB, ops scripts
├── tests/                    # Unified test suite (353 tests)
└── docs/                     # ADRs, architecture, operations runbook
```

---

## Quick Start (Local Development)

### Prerequisites
- Docker Desktop 4.x+
- Python 3.12+
- Node.js 20+
- PowerShell 7+

### Start Full Stack

```powershell
# Copy and configure environment
Copy-Item .env.example .env
# Edit .env — set POSTGRES_PASSWORD, JWT_SECRET_KEY

# Start everything (Temporal + PostgreSQL + API + Workers + Frontend)
.\manage.ps1 start

# Temporal Web UI → http://localhost:8233
# API → http://localhost:8000/api/docs
# Dashboard → http://localhost:3000
```

### Start Temporal Only (for development)

```powershell
docker compose -f infra/docker-compose.temporal.yml up -d
```

### Run Tests

```powershell
.\manage.ps1 test              # All 353 tests
.\manage.ps1 test:backend      # 122 backend unit tests
.\manage.ps1 test:gmaps        # 100 gmaps-scraper tests
.\manage.ps1 test:activities   # Temporal activity tests
```

---

## Data Sources

| Source | Type | Scraper | Schedule |
|:-------|:-----|:--------|:---------|
| CMS NPI | Federal registry | `fetch_cms_npi.py` | Daily (incremental) |
| SEC EDGAR | Financial filings | `fetch_sec_edgar.py` | Daily (incremental) |
| FDIC | Bank registry | `fetch_fdic.py` | Daily (incremental) |
| USASpending | Federal contracts | `fetch_usaspending.py` | Daily (incremental) |
| ProPublica | Nonprofit data | `fetch_propublica.py` | Daily (incremental) |
| SAM.gov | Government contractors | `fetch_sam_gov.py` | Daily (incremental) |
| Google Maps | Local businesses | `gmaps_scraper/` | Weekly |
| OpenStreetMap | Geographic data | `open_map/` | Monthly |

---

## Temporal Workflows

| Workflow | Purpose | Task Queue |
|:---------|:--------|:-----------|
| `FederalIngestionWorkflow` | Runs all 6 federal scrapers sequentially | `federal-ingestion` |
| `GMapsExtractionWorkflow` | Runs gmaps 3-phase pipeline (collect → verify → crawl) | `gmaps-extraction` |
| `OSMStateWorkflow` | Runs OSM quadtree extraction per state | `osm-extraction` |
| `LeadEnrichmentWorkflow` | Normalize → dedup → validate → build leads | `data-pipeline` |
| `DLQReplayWorkflow` | Retries dead-letter queue records in batches | `storage-ops` |
| `MasterOrchestrationWorkflow` | Top-level Saga coordinating all above | `federal-ingestion` |

All workflows support **Signal** (pause/resume/cancel) and **Query** (live status) operations via the API.

---

## AI Agents

| Agent | Role | Cycle |
|:------|:-----|:------|
| `DataQualityAgent` | Monitors DLQ, triggers auto-replay or alerts | 5 min |
| `PipelineCoordinatorAgent` | Auto-chains downstream workflows on completion | 5 min |
| `ResourceManagerAgent` | Throttles workers when DB pool > 85% | 5 min |
| `FederalExtractionAgent` | Decides incremental vs full refresh per source | On demand |
| `AlertAgent` | Emits Sentry/Slack alerts on failures | Event-driven |

---

## Contributing

See [docs/development/getting-started.md](docs/development/getting-started.md).

Key rules:
1. **Never modify scraper business logic** — only activity wrapper files may change
2. All PRs require passing all 353 tests
3. New scrapers must be added as Temporal Activities with corresponding tests

---

## License

Internal proprietary software. All rights reserved.
