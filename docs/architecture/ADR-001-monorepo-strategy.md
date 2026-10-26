# ADR-001: Monorepo Strategy

**Status:** Accepted
**Date:** October 2026
**Deciders:** Platform Engineering

---

## Context

The DataExtraction platform consolidates three independently developed projects:
1. **OneExtraction** — FastAPI backend, 6 federal scrapers, pipeline modules
2. **gmaps-scraper** — Google Maps local scraping engine
3. **Next.js Frontend** — Dashboard UI

These three share: PostgreSQL as the primary data store, configuration patterns (python-dotenv, pydantic-settings), structured logging conventions, and the same deployment environment.

## Decision

**Single monorepo with `packages/` layout.**

All packages live in one git repository under `DataExtraction/packages/`:
```
packages/
  scrapers/    # All scrapers (federal, google_maps, open_map)
  pipeline/    # Data transformation
  temporal/    # Orchestration layer (new)
  agents/      # AI agent framework (new)
  api/         # FastAPI backend
  infrastructure/ # Shared utilities
  frontend/    # Next.js
```

## Alternatives Considered

| Option | Pros | Cons | Verdict |
|:-------|:-----|:-----|:--------|
| **Monorepo** | Unified CI, shared tooling, single deploy, atomic commits across layers | Larger repo size | ✅ **Chosen** |
| **3 separate repos** | Independent versioning | Dependency hell across repos, 3× CI overhead, no atomic cross-layer changes | ❌ Rejected |
| **2 repos (backend + frontend)** | Moderate isolation | Still splits temporal/agents across repos, complex cross-repo Temporal SDK version pinning | ❌ Rejected |

## Consequences

- **Positive:** Single CI/CD pipeline, shared `.env`, unified `docker-compose.yml`, atomic cross-package commits
- **Positive:** Temporal activities and scrapers co-located — no cross-repo version drift
- **Negative:** Import paths must be restructured (Phase 2 migration)
- **Mitigation:** `sys.path` injection in activity wrappers ensures scrapers are NEVER modified
