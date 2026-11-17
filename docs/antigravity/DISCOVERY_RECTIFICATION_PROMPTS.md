# Discovery Engine: rectification prompts

Two prompts for Antigravity, each in a fresh session, in this order:

1. **Prompt R1: fix** (below)
2. **Prompt R2: independent verification** (below)

Background: an audit of the code written from `LINKEDIN_INTEGRATION_PLAN_AND_PROMPTS.md` found the issues listed in
section "Audit findings" inside Prompt R1. Fix all of them. Do not add features that are not listed.

---

# PROMPT R1: FIX

---

## Role
Senior backend and full-stack engineer working in
`C:\Users\OneData\Downloads\Data_Extraction\New_Extraction\DataExtraction` (the "main repo").
The folder `C:\Users\OneData\Downloads\LinkedIN` is read-only: never modify it and never copy `.venv`, `venv`, `*.db`,
`data/cookies.json` or exports from it. Use the GRAVITAS skill in `.agents/skills/gravitas/`.
Report only what you observed by running commands in this session.

## Goal
Make the Discovery Engine truthful, complete and wired together. After this work, a search such as
`elderly care, home care in Charlotte metro area` must return only data that was actually fetched from a real source in that run
(or read from the database from an earlier real fetch), every fact must carry its true source, and anything that
cannot be fetched must be reported as `unavailable`, `empty` or `blocked`, never filled in.

## Non-negotiable rules
1. **No fabricated data in production code.** No hard-coded business names, phone numbers, license numbers, administrators,
   ratings or addresses in any module under `packages/`, `scripts/` (except clearly named test fixtures under `tests/`).
   A source that cannot reach its real data source returns status `unavailable` with a reason and zero records.
2. **No false claims in output.** Summary text must be generated only from the records actually returned. The words "verified",
   "licensed", "Medicare" or "official" may appear only for records whose own source supports them.
3. **No secrets in the repo.** Never print or log keys or cookies. Use the key vault (`packages/infrastructure/key_vault/`);
   the stored record's value attribute is `.value`.
4. **LinkedIn policy unchanged:** public pages only by default, `LINKEDIN_AUTH_ENABLED=false`, any 999/429/401/403/login wall
   stops that source for the run and reports `blocked`. No evasion.
5. Honour robots.txt and SSRF checks for every third-party page fetch, TLS verification on everywhere.
6. Enforce `kg_audit.suppression_lists` on every write and every returned result.
7. Parameterized SQL only. Migrations idempotent. Windows PowerShell commands. New dependencies go in `requirements.txt`.
8. Do not touch the existing 176 tests under `tests/unit/ai_stack` except to keep them passing. Do not run DB tests against the
   real `dataextraction` database; use a database whose name contains `test` (the `.env` file overrides shell variables, so
   change `POSTGRES_DB` in a temporary copy or pass a different `--env` file; restore it afterwards).

## Audit findings to fix (verified by reading the code and running it)
| # | Finding | Where |
|---|---|---|
| F1 | **Fabricated "official" data.** `CHARLOTTE_CMS_REFERENCE` (5 invented agencies) and `NC_DHSR_CHARLOTTE_REGISTRY` (5 invented facilities with invented administrators, license numbers, phones) are returned as `verified=True`, confidence 0.98-0.99, with real government URLs as sources. Searching "plumbers in Charlotte NC" returns them. | `packages/discovery/sources/cms_care_compare.py`, `state_registry.py`, `scripts/bench/demo_query.py` |
| F2 | CMS live call fetches one unfiltered page (`limit=25`, no condition), filters on field names that do not exist, then falls back to the fake list. NC adapter has no live fetch. Dataset id is hard-coded and was never verified. | same |
| F3 | Geography is a single hard-coded Charlotte dict (8 counties, only York for SC), not Census-based. Any unknown place falls back to Charlotte / NC. Austin, TX returns 0. | `packages/discovery/geo.py`, defaults in `google_maps.py`, `web_search.py`, `planner.py` |
| F4 | Categories hard-coded: web search labels every hit "Elderly Care Provider" or "Elderly Care Service". Summary says "verified organizations ... integrated state licensing, Medicare quality ratings" regardless of content. | `web_search.py`, `answer.py` |
| F5 | Sources are not wired: `LinkedInPublicSource` reads `intent.filters["linkedin_urls"]` which nothing sets; `WebsiteCrawlSource` is not in the default source list; web search output never reaches the crawler or LinkedIn; Google Maps source does one request and never runs the deep place pipeline. | `orchestrator.py`, `sources/*` |
| F6 | Nothing is persisted. The orchestrator writes no rows. `persist_discovery_results_activity` inserts into non-existent columns (`address`) and swallows the error. `search_runs`, `search_results`, `facts`, `organizations`, `people` are never written. Sessions live in an in-memory dict. | `orchestrator.py`, `discovery_activities.py`, `discovery_router.py` |
| F7 | SSE is not streaming results: only `source_done` status events, then one final `answer`. No `source_started`, no per-result events. | `orchestrator.py`, frontend `api.ts`, `search/page.tsx` |
| F8 | Vault key bug: `key_rec.key_value` / `record.key_value` do not exist (attribute is `.value`); the AttributeError is swallowed so dashboard keys are never used. `web_search._get_vault_key` ignores its argument and always asks provider `search`. Planner calls Groq directly with `llama-3.1-8b-instant` and a 2 s timeout instead of `get_llm()`. | `planner.py`, `web_search.py` |
| F9 | Router has no authentication; `/sources/status` open. No organization/person detail endpoints, no export. | `discovery_router.py` |
| F10 | Suppression applied only in `local_db.py` and the resolver, not on persistence or other adapters. SSRF/robots checks only in `website_crawl.py`. | `packages/discovery/**` |
| F11 | Speed layer unused: `cache.py` and `ratelimit.py` are not imported by any source; no coalescing; no Prometheus metrics. Benchmark `after.json` is slower than `baseline.json` for gmaps_deep_place (0.79 s to 1.43 s) and db_upsert, and benchmarks use mocks only. | `packages/discovery/cache.py`, `ratelimit.py`, `scripts/bench/*` |
| F12 | `DiscoverySearchWorkflow` and its activities are not registered on any worker and not in the planner `ALLOWLIST`. | `packages/temporal/workers/worker_geospatial.py`, `autonomy_planner.py` |
| F13 | 73 ruff E9/F errors (unused imports) in new code. Import script classifies 150 of 198 people as `manual_seed`: check the rule against the evidence (the LinkedIn cookie was the placeholder `test_token`, so `linkedin_scrape` rows were never really scraped). | `ruff --isolated --select E9,F packages/discovery packages/scrapers/linkedin packages/leadintel scripts tests/unit/discovery` |
| F14 | `scripts/bench/demo_query.py` demonstrates the engine using only the two fake sources. | `scripts/bench/demo_query.py` |

## Phase 0: recon and safety net (read-only first)
1. Read every file named in the table. Reproduce F1 and F3 with a short script and paste the output (for example the plumbers query and the Austin query).
2. Record the baseline: `pytest tests/unit/discovery tests/unit/ai_stack -q` (using a test database), `ruff --isolated --select E9,F` count, `npm run typecheck`.
3. Add the guard test now so it fails before the fix and passes after: `tests/unit/discovery/test_no_fabricated_data.py`:
   * scan `packages/` and `scripts/` Python files (AST) for module-level lists/dicts that contain 3 or more entries with keys like `phone`, `administrator`, `license_number`, `facility_name`, `provider_name`; fail if found;
   * fail if any source module contains the strings `CHARLOTTE_CMS_REFERENCE`, `NC_DHSR_CHARLOTTE_REGISTRY` or a US phone number literal matching `\(\d{3}\) \d{3}-\d{4}`;
   * run each source adapter with all network calls blocked (monkeypatch `httpx.AsyncClient` to raise) and assert it returns zero organizations and status in `{unavailable, error, empty, blocked}`.
4. Output a short plan with exact files to change.

## Phase 1: remove fabricated data (F1, F14)
* Delete both hard-coded datasets and every reference to them. Fixtures with sample rows belong in `tests/fixtures/discovery/` and are loaded only by tests through a mock transport.
* Add `SourceStatus.status = "unavailable"` (document it) for "the real source could not be reached or parsed".
* Rewrite `scripts/bench/demo_query.py` so it runs the real orchestrator with real sources and prints per-source status honestly; it must not construct records itself.

## Phase 2: real official sources (F2)
**CMS (cms_care_compare.py)**
* Look up the current dataset ids and field names on the official site (https://data.cms.gov/provider-data/ , topic Home Health Services, plus Hospice and Nursing Homes) and record the page URL and retrieval date in the module docstring and in `docs/operations/discovery.md`. Do not rely on memory for ids or field names.
* Query the provider-data datastore API with proper filters: state, and city/county/ZIP list derived from the resolved geography (Phase 3). Page through results (`limit`/`offset`) until exhausted or the budget ends. Use a shared `httpx.AsyncClient` with HTTP/2 and the rate limit from `config/rate_limits.yaml`.
* Map fields: provider name, address, phone, ownership type, star ratings, CCN, certification date, services flags. Keep the raw record as a fact with the dataset id and the record URL. Confidence 0.95 only for fields that came from the response.
* Cache each response in `discovery_cache` (TTL 24 h).
* If the API is unreachable or the schema changed: status `unavailable` with the HTTP status or exception name, zero records.

**NC registry (state_registry.py)**
* Find the official NC DHSR publication of licensed facilities/agencies (https://info.ncdhhs.gov/dhsr/ and the Home Care Agencies, Adult Care Homes, Nursing Homes listings). Choose the machine-readable download (CSV/XLS/PDF) or documented endpoint. Implement downloader and parser for the published format, cache the file under `data/registry/nc/` with its retrieval date and hash, refresh when older than 7 days.
* Named administrators are included only if the published file contains them.
* If no machine-readable official source exists for a category, report `unavailable` for that category with the URL that was checked. Do not scrape pages in a way the site forbids (robots.txt) and do not invent data.
* Make the adapter registry pluggable: `STATE_ADAPTERS = {"NC": NcDhsrAdapter}`; other states return `unavailable: no adapter for XX`.

Add tests with small recorded fixtures (a few real-format rows with obviously fake names such as `TEST AGENCY ONE`) behind a mock transport.

## Phase 3: geography and category truthfulness (F3, F4)
* `geo.py`: download the Census CBSA-to-county delineation file and the Census Gazetteer (places, counties, ZIPs) once into `data/geo/` (checksum + retrieval date + URL recorded in `data/geo/SOURCES.md`); write a loader that resolves free text ("Charlotte metro area", "Austin, TX", "Wake County NC", ZIP code) to: type, name, state(s), counties (with state), principal cities, centroid, bounding box, ZIP list. Metro phrases use the CBSA. Charlotte-Concord-Gastonia (CBSA 16740) must come out of the data file with all its NC and SC counties.
* No default location. If the location cannot be resolved the response asks for one (`needs_location: true`) instead of guessing Charlotte or NC.
* Category: derive from the planner's `SearchIntent.categories` (LLM or rules). Web-search and other adapters must use the intent's category for labels and must never hard-code "Elderly Care". The CATEGORY_KEYWORDS rules stay as the fallback but unknown queries use the query text as the category.
* `answer.py`: replace the boilerplate sentence with text built from counts and flags actually present, for example: `Found 12 organizations (CMS: 4, NC registry: 3, Google Maps: 9, web: 5; 2 merged duplicates)`. Mention CMS/licensing only when at least one card has that data. Add `source_breakdown` to the answer.

## Phase 4: planner and keys (F8)
* `planner.py`: use `get_llm()` with the Pydantic `SearchIntent`-like schema (`categories`, `synonyms`, `location_phrase`, `want`), `purpose="discovery_planner"`, normal timeouts, keep the cache and the rule-based fallback. Remove the direct Groq HTTP call and the hard-coded model.
* Fix every `.key_value` to `.value`. `web_search._get_vault_key` must request the provider it is asked for: store Brave and Tavily keys under providers `brave` and `tavily` (extend the key vault `Provider` literal in `secrets_router.py` and the UI dropdown) and read them with `get_active_key("brave")` / `("tavily")`. Keep `linkedin` and `search` providers. Add tests proving a key stored in the vault is the one used.

## Phase 5: wire the pipeline (F5)
Rework `orchestrator.py` into stages that pass data forward, still streaming:
1. **Stage A (parallel):** local DB, CMS, state registry, Google Maps, web search. Each emits events as soon as it has records.
2. **Stage B (as Stage A results arrive):** for every organization with a website, run `WebsiteCrawlSource` (SSRF + robots, bounded concurrency, per-host rate limit); for every LinkedIn URL found by web search, run `LinkedInPublicSource` with those URLs (set `intent.filters["linkedin_urls"]` or, better, pass them as an explicit argument); enrichment for emails and phones.
3. **Stage C:** resolve, rank, compose.
* Google Maps adapter: use the real city grid from the resolved geography (centroid per principal city, not Charlotte defaults), the intent's category query, paginate, honour block detection from `gmaps_scraper.http._is_blocked_response`, and queue found places into `run_deep_extraction` in the background (do not block the interactive answer; show "details loading" and update through an SSE `update` event). A CAPTCHA/consent wall returns `blocked`.
* Web search: results that are directories or aggregators (yelp.com, caring.com, seniorly.com, agingcare.com, facebook.com, etc., list in config) are kept as `sources` on the matching organization, not shown as separate organizations. Candidate organization sites are accepted only if the page title/snippet matches the category terms.
* Add `WebsiteCrawlSource` to the default list and make Stage B conditional on its inputs.
* Per-source timeout is enforced with `asyncio.wait_for`, not only by checking `budget.is_expired()` between yields; a hanging source reports `timeout` and the others continue.

## Phase 6: persistence and detail APIs (F6, F9, F10)
* After resolution, write in one transaction per search with `execute_values`: `discovery_dataextraction.organizations` (use the actual columns: `address_street`, `address_city`, `address_state`, `address_postal_code`, ...), `people`, `facts` (unique key already in the schema), `search_runs` (query, parsed intent, timings, per-source status), `search_results` (rank, score). Upsert on a stable key (normalized name + postal code or phone or domain) so repeated searches update rows instead of duplicating them. Fix or replace `persist_discovery_results_activity` accordingly and make the interactive path call the same persistence function.
* Suppression: apply to people and to person-type emails/phones before insert and before output, for every source (central function in `packages/discovery/suppression.py` using `kg_audit.suppression_lists`).
* Replace the in-memory `_active_searches` with `search_runs` rows (keep a small in-process map only for live SSE queues). A restarted server must still return a finished search by id.
* API (`discovery_router.py`): require authentication like the other routers (`get_current_user`; `require_admin` for source enable/disable and `/sources/status` details). Add `GET /organizations/{id}`, `GET /people/{id}` (all facts with source, URL, retrieved_at), `POST /search/{id}/export?format=csv|jsonl` (streaming), `GET /searches?limit=` for history.
* Validate input: query length 1-300, `budget_seconds` 5-120, filters whitelist.

## Phase 7: streaming (F7)
* Events in order: `plan`, `source_started` (per source), `result` (batches of organizations/people as each source returns, already normalized and with `source`), `source_done` (status, count, elapsed), `update` (late enrichment or deep-place details for an existing card), `entities_resolved`, `answer`, `done`. Keep event names stable and documented.
* Frontend `search/page.tsx` and components: render cards incrementally from `result` events, merge duplicates client-side by `org_id` after `entities_resolved`, show per-source chips with live state (running, ok, empty, blocked, timeout, unavailable) and elapsed time, show the resolved geography and the unresolved-location prompt, label email types, "unverified" markers, links to sources, export button. Fall back to polling `GET /search/{id}` if SSE fails. No secrets in client code.

## Phase 8: speed layer (F11)
* All HTTP-based sources get their client from one factory (`packages/discovery/http.py`): shared `httpx.AsyncClient` per host group with HTTP/2, keep-alive, connection limits, and the per-host `AsyncTokenBucket` from `ratelimit.py` configured from `config/rate_limits.yaml`.
* Use `cache.py` for CMS, registry files, geo lookups, web-search results (TTL 1 h), crawled pages (ETag/Last-Modified/content hash, TTL 24 h) with in-flight coalescing. Add tests: N identical concurrent calls make one fetch; second search within TTL makes zero network calls to cached sources.
* Add Prometheus metrics (histogram per source latency, counters for results/errors/blocks/cache hits) through the existing `packages/infrastructure/metrics.py`.
* Benchmarks: make `scripts/bench/bench_sources.py` run against a local test server that adds realistic latency (50-300 ms) so concurrency effects are visible; regenerate `baseline.json` from `git stash`-free baseline numbers (measure the pre-change code via a temporary worktree) and `after.json`. The after results must be at least as good as the baseline for every measure, or the regression must be explained and fixed. State clearly that real-world speed is bounded by third-party rate limits and was not measured live.

## Phase 9: Temporal and planner (F12)
* Register `DiscoverySearchWorkflow` and its activities on the geospatial worker (`worker_geospatial.py`), fix the activities to use the shared persistence function, and add `DiscoverySearchWorkflow` to `ALLOWLIST` in `autonomy_planner.py` with validated parameters (`query` regex-limited length, `budget_seconds` 5-120, filters whitelist).
* Run it for real on a local Temporal dev server (`temporalio.testing.WorkflowEnvironment.start_local()`), with canned HTTP transports, and verify rows were written.

## Phase 10: cleanup (F13)
* `ruff check --isolated --select E9,F --fix` on the new packages, then confirm zero errors.
* Re-check the import script's `manual_seed` rule. Document the evidence used (for example: rows whose `source_url`/notes originate from `seed_tamilnadu_ceos.py` or `rectify_phones.py`, rows with the placeholder cookie era, rows without `raw_public`). Print counts for each rule. Only rows with real evidence of hand entry are `manual_seed`; scraped rows stay `legacy_import`. Keep emails `inferred` unless page evidence exists. Idempotent.
* Update `docs/operations/discovery.md`, README, `.env.example` (new keys: `SEARCH_PROVIDER`, provider names `brave`/`tavily`, cache TTLs, registry cache dir) and CI. Remove claims in docs that are not true (for example "verified" licensing for all results, speed numbers not measured).

## Tests to add or update (offline; no live calls in CI)
* The guard test from Phase 0.
* CMS and NC adapters: filters sent, pagination, field mapping, `unavailable` when blocked/unreachable, cache hit.
* Geo: Charlotte CBSA from the data file yields the NC and SC counties; "Austin, TX"; "Wake County NC"; ZIP; unresolved text returns `needs_location`.
* Planner: uses `get_llm()`; vault key is used; rules fallback; category passthrough.
* Orchestrator: stage wiring (website crawl receives sites from earlier stages; LinkedIn source receives URLs from web search), timeouts via `wait_for`, one failing source does not stop others, event order including `source_started` and `result`.
* Resolver and answer: summary built from data only; no CMS/licensing wording when absent; every citation id exists.
* Persistence: rows in all five tables, upsert idempotency, suppression, search retrievable after "restart" (new orchestrator instance).
* API: auth required (401/403), validation, detail endpoints, export streaming.
* Web search: aggregator results become `sources` not organizations; category label comes from the intent.
* Temporal: workflow run on local dev server writes rows; `ALLOWLIST` validation.
* Speed layer: coalescing, TTL, token-bucket timing, and metrics increments.

## Definition of done (show command output for every item)
1. Guard test passes; `Select-String -Pattern 'CHARLOTTE_CMS_REFERENCE|NC_DHSR_CHARLOTTE_REGISTRY|\(\d{3}\) \d{3}-\d{4}' -Path packages,scripts -Recurse` finds nothing in production code.
2. Running the "plumbers in Charlotte NC" and "dental clinics in Austin, TX" queries with all network blocked returns zero organizations and honest statuses, not eldercare agencies.
3. `ruff --isolated --select E9,F` clean on all new and touched files.
4. `pytest tests/unit/discovery tests/unit/ai_stack -q` passes against a test database; the pre-existing unit failures are unchanged (before/after counts from a baseline worktree).
5. `npm run typecheck` and `npm run build` pass in `frontend/`.
6. Local Temporal run executes `DiscoverySearchWorkflow` and shows the written rows.
7. Benchmark table before/after with no regression.
8. Secret scan over tracked and untracked files: no real keys, no cookies, no `verify=False`.
9. `git status` shows only intended files, nothing was written to the LinkedIN folder, and the real `dataextraction` database was not used by tests.
10. Live smoke (only if network is available; skip honestly if not): run the demo script once with `max_results=10` and paste per-source status. For CMS and NC registry, include 3 returned records and the URL of the real source page for each so a human can compare. A `blocked` or `unavailable` status is an acceptable result; fabricated records are not.

## Output format
Per phase: What changed (files), Evidence (verbatim trimmed command output), Not verified (and why). End with a table of F1-F14 with
status FIXED / PARTIAL / NOT FIXED and the evidence for each. `VERDICT: PASS` only if every F item is FIXED with evidence.
Never claim live behaviour of Google, CMS, NC, DuckDuckGo or LinkedIn unless you ran it live in this session.

---

# PROMPT R2: INDEPENDENT VERIFICATION

Use a **new session** that did not write the fix. Assume nothing works until output proves it. Use GRAVITAS. You may fix trivial defects; report anything larger.

## Step 1: fabricated data hunt (highest priority)
1. `Select-String -Path packages,scripts -Pattern '\(\d{3}\) \d{3}-\d{4}','license_number','administrator','CHARLOTTE_','_REFERENCE','_REGISTRY' -Recurse` and read every hit. Explain each; none may be business data in production code.
2. AST scan: no module-level list/dict with 3+ entries of business-like records anywhere under `packages/`.
3. Block all network (set `HTTPS_PROXY` to a dead address and monkeypatch `httpx`), run `"plumbers in Charlotte NC"`, `"dental clinics in Austin, TX"` and `"elderly care, home care in Charlotte metro area"` through the orchestrator. Every one must return zero organizations and statuses explaining why (`unavailable`/`error`/`empty`). Show the JSON.
4. Mutation: re-add a single fake record to CMS and to the registry adapter; the guard test must fail. Revert.

## Step 2: source truthfulness
* With a local mock server standing in for data.cms.gov, return 3 rows with fake names; confirm the adapter sends the state/city/ZIP filters and pages, maps fields exactly, and tags facts with the dataset id and URL. Return HTTP 500 and a changed schema; confirm `unavailable`.
* Same for the NC registry file parser with a small fixture file in the published format; wrong format yields `unavailable`.
* Open the code and check the dataset ids and field names against the official CMS provider-data site. Record the page you used and whether they match. If you have no network, say NOT VERIFIED.

## Step 3: geography and categories
* Load the Census data files; show the counties returned for "Charlotte metro area" (must include Mecklenburg, Union, Cabarrus, Gaston, Iredell, Lincoln, Rowan, Anson NC and York, Lancaster, Chester SC if present in the official delineation; compare with the file itself, not memory), for "Austin, TX", "Wake County NC", ZIP "28202", and an unresolvable phrase (must give `needs_location`, not Charlotte).
* Search a non-eldercare category (for example "roofing contractors in Raleigh NC") with mocked sources and confirm no result is labelled "Elderly Care".

## Step 4: wiring
With mock servers for Google Maps, DuckDuckGo, an organization website and public LinkedIn pages, show an event log proving: web search found a LinkedIn URL, the LinkedIn source received it, parsed ld+json and returned a record; the crawler received organization websites from Google/web results and returned phones/emails/people; directories were attached as sources, not shown as organizations; a hanging source timed out at its budget while others finished; a 999/429 response from LinkedIn stopped only that source.

## Step 5: persistence and API
* Run a search, restart the process (new orchestrator, new TestClient), fetch the search by id: still there. Show rows in `organizations`, `people`, `facts`, `search_runs`, `search_results`. Repeat the same search: row counts for organizations do not grow; `search_runs` grows by 1.
* Add a person to `kg_audit.suppression_lists`; confirm absence in all five tables, API JSON, SSE and exports.
* 401/403 without or with insufficient credentials on every discovery route; validation errors for bad query/budget; export CSV and JSONL stream correctly.
* Secrets: store a Groq key in the vault; confirm the planner and the web-search sources use it (`.value`), logs never contain it, and no code reads `.key_value`.

## Step 6: streaming and UI
Capture the SSE stream for a mocked search and show event order: `plan`, `source_started` x N, `result` before the slowest `source_done`, `entities_resolved`, `answer`, `done`. `npm run typecheck`, `npm run build`. Read `search/page.tsx` and confirm cards render from `result` events, chips show running/ok/empty/blocked/timeout/unavailable, email labels appear, and there are no secrets. If Playwright exists, run an offline smoke test with the API mocked.

## Step 7: speed layer and Temporal
* Coalescing: 20 concurrent identical calls cause 1 fetch. TTL: second search makes 0 network calls to cached sources.
* Token bucket: 5 req/s limit, 50 requests, takes about 10 s (assert within tolerance).
* `Select-String 'time\.sleep' packages/discovery packages/scrapers/linkedin` returns nothing in async paths.
* Re-run `scripts/bench/bench_sources.py`; compare with `baseline.json`; no regression. Check that the baseline was measured on the pre-change code.
* Start local Temporal (`WorkflowEnvironment.start_local()`), run the real geospatial worker module and `DiscoverySearchWorkflow`; show rows written. Confirm `ALLOWLIST` accepts the workflow only with valid parameters and rejects oversized or unknown ones.

## Step 8: cleanup and honesty
* `ruff --isolated --select E9,F` on all new code: zero errors. `python -m compileall packages -q`.
* Full `tests/unit` before/after comparison using a baseline `git worktree` (remove it afterwards): no new failures.
* Import script: dry-run output shows evidence-based provenance counts; apply twice with idempotent result against a test database.
* Read README and `docs/operations/discovery.md`; list every claim not backed by code or evidence.
* Secret scan (`gsk_`, `AKIA`, `li_at`, `JSESSIONID`, private keys) over tracked and untracked files; `Select-String 'verify\s*=\s*False' -Path packages -Recurse` finds nothing.

## Report
Table: requirement | PASS / FAIL / NOT VERIFIED | evidence. Defects by severity (fabrication, safety, correctness, missing feature, polish) with file and line.
`VERDICT: PASS` only with zero FAIL and zero NOT VERIFIED in Steps 1-5.
