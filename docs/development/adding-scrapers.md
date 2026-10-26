# Adding New Scrapers to DataExtraction

## Scraper Integration Protocol

To integrate a new data source into the DataExtraction monorepo, follow the **Thin Activity Wrapper** pattern:

### Step 1: Place Scraper in `packages/scrapers/`
Create a new directory or module under `packages/scrapers/<category>/`:
```
packages/scrapers/
├── federal/
├── google_maps/
├── open_map/
└── custom_source/
    └── fetch_custom.py
```
Ensure the scraper can execute standalone via CLI (e.g. `python fetch_custom.py --limit 1000`).

### Step 2: Create Activity Wrapper
Add an activity function in `packages/temporal/activities/`:
```python
from temporalio import activity
import subprocess, sys
from pathlib import Path

SCRAPER_PATH = Path(__file__).resolve().parents[2] / "scrapers" / "custom_source" / "fetch_custom.py"

@activity.defn(name="run_custom_source")
async def run_custom_source_activity(args: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(SCRAPER_PATH), "--limit", str(args.get("limit", 1000))],
        capture_output=True, text=True, cwd=str(SCRAPER_PATH.parent), timeout=3600
    )
    if result.returncode != 0:
        raise activity.ActivityError(f"Custom scraper failed: {result.stderr[-500:]}")
    return {"source": "CUSTOM_SOURCE", "count": 1000}
```

### Step 3: Register in Worker & Workflow
1. Add the activity to the corresponding worker in `packages/temporal/workers/`.
2. Add the activity call to the relevant workflow definition.
3. Configure rate limits in `config/rate_limits.yaml`.
