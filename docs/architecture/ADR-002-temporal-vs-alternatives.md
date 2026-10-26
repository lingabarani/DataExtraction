# ADR-002: Temporal as Orchestration Engine

**Status:** Accepted
**Date:** October 2026
**Deciders:** Platform Engineering

---

## Context

The existing `pipeline_orchestrator.py` in OneExtraction is a monolithic Python script with:
- No crash recovery (restart loses all progress)
- No visibility into running state
- Manual retry logic per-source
- No scheduling support (runs on-demand only)
- No per-source isolation (one failure can halt all sources)

We need a production-grade orchestration layer that provides: durability, visibility, scheduling, retries, and isolation — without rewriting any scraper.

## Decision

**Temporal Workflows as the orchestration layer.**

Temporal replaces `pipeline_orchestrator.py`. All scrapers become Temporal Activities (thin subprocess/module wrappers). Workflows define the execution graph.

```
Before: pipeline_orchestrator.py → directly calls fetch_*.py
After:  Temporal Workflow → executes Activity → subprocess calls fetch_*.py (unchanged)
```

## Why Temporal Over Alternatives

| Capability | Celery + Redis | Apache Airflow | Prefect | **Temporal** |
|:-----------|:--------------|:---------------|:--------|:-------------|
| Crash recovery (replay from failure) | ❌ No | ✅ Partial | ✅ Partial | ✅ **Full** |
| Workflow history | ❌ No | ✅ Partial | ✅ Partial | ✅ **Complete** |
| Native Python SDK | ✅ Yes | ✅ Yes | ✅ Yes | ✅ **Yes** |
| Signals (live control) | ❌ No | ❌ No | ❌ Limited | ✅ **Yes** |
| Queries (live state inspection) | ❌ No | ❌ No | ❌ Limited | ✅ **Yes** |
| Child workflows | ❌ No | ❌ No | ✅ Yes | ✅ **Yes** |
| Dynamic workflow graphs | ❌ No | ❌ DAG only | ✅ Yes | ✅ **Yes** |
| Self-hosted | ✅ Redis | ✅ Postgres | ✅ Postgres | ✅ **Postgres** |
| Temporal Cloud option | ❌ No | ❌ No | ✅ Yes | ✅ **Yes** |

**Why not Celery:** Celery has no built-in workflow history. A worker crash means the task must be replicated from scratch. There is no concept of Signal (live control) or Query (live inspection). Retry state is not durable across crashes.

**Why not Airflow:** Airflow is DAG-first — the execution graph is defined statically at DAG authoring time. DataExtraction needs *dynamic* workflows (e.g., spawn one child workflow per US state, where the list is determined at runtime). Airflow's overhead (scheduler, web server, worker) is also heavier than Temporal for scraper-granularity work units.

## Temporal Core Concepts in Use

| Concept | Use in DataExtraction |
|:--------|:----------------------|
| **Workflow** | `FederalIngestionWorkflow`, `GMapsExtractionWorkflow`, etc. — durable state machines |
| **Activity** | Thin wrappers around each scraper — subprocess calls or module imports |
| **Worker** | 4 worker processes — one per task queue |
| **Task Queue** | `federal-ingestion`, `gmaps-extraction`, `osm-extraction`, `data-pipeline` |
| **Signal** | `pause()`, `resume()` — sent from API to running workflow |
| **Query** | `get_status()` — read live workflow state without modifying it |
| **Schedule** | Cron-based automatic workflow triggering |
| **RetryPolicy** | Per-activity exponential backoff with configurable max attempts |
| **Child Workflow** | Master workflow spawns federal/gmaps/osm as independent child runs |

## Consequences

- **Positive:** All scraper runs are now durable — crash recovery is automatic
- **Positive:** Full execution history in Temporal Web UI (port 8233)
- **Positive:** Pause/resume/cancel any pipeline run via API without data loss
- **Positive:** Per-source error isolation — one failed federal scraper doesn't halt others
- **Negative:** Temporal Server must be deployed and maintained (mitigated: Docker or Temporal Cloud)
- **Negative:** Learning curve for Temporal Python SDK (mitigated: start with DLQReplayWorkflow)
