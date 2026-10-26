# ADR-003: Scraper Preservation Guarantee

**Status:** Accepted
**Date:** October 2026
**Deciders:** Platform Engineering, Business Stakeholders

---

## Context

All scrapers in the OneExtraction and gmaps-scraper projects are **completed, production-tested units** with:
- Validated business logic and field extraction rules
- Passing test suites (100 gmaps, 122 backend, 31 OSM = 253 total)
- Known, stable behavior in production environments
- Hardened rate limiting, retry logic, and error handling

Rewriting any scraper introduces regression risk with zero business value. The only requirement is to make them **orchestratable**.

## Decision

**All scraper business logic is IMMUTABLE. Activities are thin subprocess/module wrappers only.**

### Implementation Rules

1. **Zero content modification** — scraper files (`fetch_*.py`, `gmaps_scraper/`, `openmap_engine/`) are NEVER edited
2. **Path bridging via `sys.path`** — activity wrappers inject the scraper directory into Python's module search path; scrapers import their own dependencies exactly as before
3. **Subprocess for independent scrapers** — federal scrapers (`fetch_*.py`) run as managed subprocesses; this guarantees complete isolation (separate Python process, separate memory space)
4. **Module import for co-located scrapers** — gmaps and OSM modules are imported directly (same process) since they have no process-level conflicts
5. **Original tests must continue to pass at the new file paths** — Phase 2 gate is 253/253 tests green

### Activity Wrapper Pattern

```python
# Federal scraper activity (subprocess pattern)
@activity.defn(name="run_cms_npi")
async def run_cms_npi_activity(args: dict) -> dict:
    SCRAPERS_DIR = Path(__file__).parent.parent.parent / "scrapers" / "federal"
    result = subprocess.run(
        [sys.executable, str(SCRAPERS_DIR / "fetch_cms_npi.py"),
         "--limit", str(args.get("limit", 50000))],
        capture_output=True, text=True, cwd=str(SCRAPERS_DIR),
        timeout=3600,
    )
    # fetch_cms_npi.py is NEVER touched — runs exactly as written
    return {"exit_code": result.returncode, "stdout_tail": result.stdout[-2000:]}

# GMaps scraper activity (module import pattern)
@activity.defn(name="run_gmaps_collection")
async def run_gmaps_collection_activity(region: str, category: str) -> dict:
    sys.path.insert(0, str(Path(__file__).parent.parent.parent /
                          "scrapers" / "google_maps" / "src"))
    from gmaps_scraper import orchestrator  # Original module, zero modification
    result = orchestrator.collect_region(region, category, {})
    return {"collected": result.count}
```

## Enforcement

This guarantee is enforced via:
1. **Phase 2 test gate** — 253 tests must pass 100% before Phase 3 begins
2. **CODEOWNERS** — scraper directories owned by a protected reviewer group; no PR merges without explicit approval
3. **CI diff check** — CI fails if any file in `packages/scrapers/` differs from its corresponding source file in the original OneExtraction repo

## Consequences

- **Positive:** Zero regression risk on any existing scraper behavior
- **Positive:** All 253 existing tests remain authoritative and continue to run unmodified
- **Positive:** Original scraper directories remain usable standalone (importable, runnable)
- **Negative:** Activity wrappers must handle differing return formats per scraper (no standardized interface)
- **Mitigation:** Activity return type is `dict` — each activity documents its specific return schema
