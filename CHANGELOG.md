# Changelog

All notable changes to DataExtraction are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

---

## [Unreleased]

### Phase 1 — Monorepo Foundation (In Progress)
- Created DataExtraction monorepo from OneExtraction + gmaps-scraper
- Defined complete `packages/` directory structure
- Initialized git repository with `main` branch
- Created `.gitignore`, `README.md`, `CHANGELOG.md`
- Writing Architecture Decision Records (ADR-001 through ADR-005)
- Writing `docker-compose.yml` with 7-container stack
- Writing `.env.example` consolidated environment template

### Phase 2 — File Migration (Planned)
- Copy all federal scrapers to `packages/scrapers/federal/` (unchanged)
- Copy gmaps-scraper complete project to `packages/scrapers/google_maps/` (unchanged)
- Copy openmap_engine to `packages/scrapers/open_map/` (unchanged)
- Copy pipeline modules to `packages/pipeline/` (unchanged)
- Copy infrastructure modules to `packages/infrastructure/` (unchanged)
- Copy API routers to `packages/api/routers/` (unchanged)
- Gate: 253 tests (122 backend + 100 gmaps + 31 OSM) must pass 100%

### Phase 3 — Temporal Orchestration (Planned)
- `packages/temporal/client.py` — Temporal client factory
- `packages/temporal/activities/` — Thin wrappers for all scrapers
- `packages/temporal/workflows/` — 6 workflow definitions
- `packages/temporal/schedules/` — Daily/weekly/monthly cron schedules
- `packages/temporal/workers/` — 4 worker process launchers
- `packages/api/routers/pipeline_router.py` — Workflow control API

### Phase 4 — Agent Framework (Planned)
- `packages/agents/base_agent.py` — Abstract agent base class
- `packages/agents/quality_agents/data_quality_agent.py`
- `packages/agents/orchestration_agents/pipeline_coordinator.py`
- `packages/agents/orchestration_agents/resource_manager_agent.py`
- Frontend: `pipelines/`, `agents/`, `schedules/` dashboard pages

### Phase 5 — Production Hardening (Planned)
- Prometheus metrics taxonomy (20+ metric families)
- Structured logging extension for Temporal activities
- Security hardening, Docker production images
- Full 353-test suite, GitHub Actions CI/CD
- Operations runbook, deployment guide

---

## Migration Origin

This repository consolidates:
- **OneExtraction** (`d:\Data Scraping Project POC\OneExtraction\`) — Primary backend
- **gmaps-scraper** (`d:\Data Scraping Project POC\OneExtraction\gmaps-scraper\gmaps-scraper\`) — Google Maps scraping engine

All scraper business logic is immutable. Temporal and Agents are additive orchestration layers only.
