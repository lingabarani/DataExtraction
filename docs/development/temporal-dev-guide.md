# Temporal Orchestration Developer Guide

## Architecture
DataExtraction uses Temporal IO for durable, distributed, and fault-tolerant execution. Scrapers and pipelines run as **Activities** orchestrated by parent **Workflows**.

### Key Rules
1. **Scrapers Are Untouched**: Scraper files in `packages/scrapers/` are never rewritten. Activities wrap them via `subprocess.run` or `sys.path` injection.
2. **Task Queue Isolation**: Workflows dispatch activities to dedicated queues matching worker pools:
   - `federal-ingestion`: Concurrency 3
   - `gmaps-extraction`: Concurrency 5
   - `osm-extraction`: Concurrency 4
   - `data-pipeline`: Concurrency 8
   - `storage-ops`: Concurrency 10
3. **Deterministic Workflows**: No `time.sleep()`, non-deterministic `uuid()`, or direct network I/O inside workflow code — use `workflow.sleep()`, `workflow.execute_activity()`, or queries.

---

## Workflow Reference

### 1. MasterOrchestrationWorkflow
Coordinates end-to-end extraction saga:
```
MasterOrchestrationWorkflow
  ├── Step 1: FederalIngestionWorkflow (Sequential, isolated error handling)
  ├── Step 2: GMapsExtractionWorkflow ∥ OSMStateWorkflow (Parallel extraction)
  └── Step 3: LeadEnrichmentWorkflow (Normalizer, Deduplicator, Contact Validator)
```

### 2. Signals & Queries
Workflows expose real-time interaction hooks:
- **`@workflow.signal pause()`**: Pauses execution before the next activity step.
- **`@workflow.signal resume()`**: Unblocks paused workflow.
- **`@workflow.query get_status()`**: Returns current execution phase, completed sources, and metrics without altering history.

---

## Local Development & Testing
Run Temporal activities and workflows in integration tests:
```powershell
.\manage.ps1 test:agents
```
To register automated cron schedules on a running Temporal server:
```python
from packages.temporal.client import get_temporal_client
from packages.temporal.schedules.register_schedules import register_all_schedules

client = await get_temporal_client()
await register_all_schedules(client)
```
