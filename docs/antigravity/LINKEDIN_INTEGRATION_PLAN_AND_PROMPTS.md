# LinkedIN folder: analysis, integration plan and Antigravity prompts

Source analysed: `C:\Users\OneData\Downloads\LinkedIN` (read-only).
Target: `C:\Users\OneData\Downloads\Data_Extraction\New_Extraction\DataExtraction`.

Contents: 1. What the LinkedIN folder is. 2. Findings that change the plan. 3. Decisions and defaults.
4. Target design. 5. Phased plan. 6. Prompt A (build). 7. Prompt B (verify). 8. Prompt C (acceptance run).

---

## 1. What the LinkedIN folder contains

Two separate programs that do not share code or a database.

### A. `liscraper/` (CLI, synchronous, SQLite `data/liscraper.db`)
| File | Role |
|---|---|
| `http.py` | `curl_cffi` session with Chrome TLS impersonation, random pacing (2-7 s), hourly cap (120), retry/backoff, proxy rotation, circuit breaker on HTTP 999. Raises `Blocked`, `RateLimited`, `AuthExpired`, `Transient`. |
| `profile.py` | Parses public `application/ld+json` Person data, and the private Voyager API (positions, education, skills). |
| `company.py`, `contact.py` | Organization ld+json parser, Voyager contact info (fail-safe, never raises). |
| `search.py` | Voyager people/company search returning slugs. |
| `enrich.py` | Email candidate patterns (`first.last`, `flast`, ...) plus DNS MX check, confidence 0.9 / 0.6 / 0.3. |
| `auth.py` | Playwright login, stores `li_at` and `JSESSIONID` in `data/cookies.json`. |
| `db.py`, `export.py`, `cli.py` | WAL SQLite (`people`, `companies`, `queue`, `request_log`), streaming CSV/JSONL export, commands `auth/add/run/export/stats`. |
| `tests/` | 5 test files plus 4 real HTML fixtures (3 profiles, 1 company). |

### B. `backend/` + `frontend/` ("LeadIntel", Apollo-style lead platform)
* **Backend:** FastAPI + SQLAlchemy + Alembic, SQLite or Postgres (port 8102), ports 8100-8110.
  * Tables: `contacts`, `companies`, `contact_emails`, `contact_phones`, `professional_profiles`, `scraping_jobs`, `scraping_job_logs`.
  * Routers: leads, companies, emails, phones, scraping jobs, export, dashboard, settings.
  * Services: `search_discovery.py` (DuckDuckGo HTML, parses "Name - Title - Company | LinkedIn" snippets), `email_finder.py`, `phone_finder.py` (phonenumbers), `verification_engine.py` (syntax, disposable, role, MX, score), `lead_service.py` (dedup, enrich), async crawler with robots.txt, team-page parser.
  * Job types: `domain_crawl`, `lead_discovery`, `email_extractor`, `phone_extractor`, `company_enrichment`.
* **Frontend:** Vite + React 18 + Tailwind SPA with pages Dashboard, LeadDatabase, PeopleSearch, CompanySearch, EmailFinder, PhoneFinder, ScrapingJobs, Settings.
* `scratch/`: one-off scripts. `seed_tamilnadu_ceos.py` (98 KB of hand-typed leads), `rectify_phones.py` ("VERIFIED_CATALOG" of hand-typed phone numbers), `sync_sqlite.py` (copies Postgres to SQLite).

### Measured state of the data (read-only queries)
| Store | Counts |
|---|---|
| `data/liscraper.db` | 178 people, 1 company, queue 33 done / 25 pending |
| `lead_intel.db` (same as `backend/lead_intel.db`) | 167 contacts, 132 companies, 164 emails, 139 phones, 167 profiles, 1 job |
| Geography | liscraper: 148 India, 14 US, 2 GB; **0 rows in Charlotte or North Carolina** |

---

## 2. Findings that change the plan

1. **Authenticated LinkedIN scraping has never worked here.** `data/cookies.json` holds `test_token` / `ajax:test`.
   `raw_voyager` is empty for all 178 rows. The request log shows 20 x HTTP 200, 14 x 404, 11 x 999 (blocked),
   6 x 429, 3 x 401. LinkedIn is already blocking this client.
2. **LinkedIn's terms forbid scraping and automated access**, and it actively bans accounts and IPs. A logged-in
   scraper risks the account that logs in. No design can make LinkedIn scraping "perfect" or reliable.
   What can be made reliable is public discovery: search-engine results, public pages, company sites, registries.
3. **Most emails are guesses.** 161 of 178 people have emails, produced by name patterns plus an MX check.
   An MX record proves the domain accepts mail, not that the mailbox exists. They must be labelled `inferred`.
4. **Some data is hand-typed**, not scraped (`seed_tamilnadu_ceos.py`, `rectify_phones.py`). It needs a
   provenance flag or it will pollute search results.
5. **`search_discovery.py` uses `httpx.AsyncClient(verify=False)`** (TLS verification off) and swallows all errors.
6. **Two parallel stacks**: SQLite (liscraper) vs SQLAlchemy/Postgres (LeadIntel), joined by a sync script;
   Vite React UI vs this project's Next.js dashboard; `liscraper` is synchronous, this project is async + Temporal.
7. **The folder has nothing for "elderly care in Charlotte".** Questions like that are answered best by:
   Google Maps (already scraped here), official registries (CMS Care Compare home health agencies, NC DHSR
   licensed facility lists), company websites, and web search. LinkedIn adds only people and company headlines.
8. Existing assets that already cover part of the goal: this project's Google Maps scraper (details, reviews,
   services, hours), website crawler with SSRF protection, LLM layer (Groq `openai/gpt-oss-120b`), key vault,
   deep place pipeline, Temporal workers, suppression lists (GDPR/CCPA).

---

## 3. Decisions and defaults (change any of these before running Prompt A)

| # | Decision | Default used in the prompts |
|---|---|---|
| D1 | LinkedIn access | **Public only**: discover profiles/companies through search-engine results and read public pages (ld+json) through a polite client. The authenticated Voyager client is ported but **off** (`LINKEDIN_AUTH_ENABLED=false`), needs a manually supplied cookie, runs at low rate, and shows a warning. No fake accounts, no cookie sharing, no CAPTCHA or 999 bypass: a block stops that source. |
| D2 | Web search provider | DuckDuckGo HTML (no key) by default. Optional paid providers (Brave, Tavily, SerpAPI) through the key vault, selectable by env. |
| D3 | Legacy data | Import the 178 people and 167 contacts with `source='legacy_import'`. Hand-typed rows (`seed_*`, `rectify_*`) get `provenance='manual_seed'`, `verified=false`, and are hidden from search unless "include unverified" is on. |
| D4 | Email labels | `found` (on a page), `inferred` (pattern + MX), `verified` (SMTP probe done by Agent 7). Search shows the label on every email. |
| D5 | Personal data | Names of business owners/administrators are collected from public business sources. Suppression list is enforced on every write and every search result. Reviewer names stay hashed (existing setting). |
| D6 | One stack | Merge into this project. No second FastAPI, no second DB, no Vite app. LeadIntel services are ported into `packages/`, UI pages are rebuilt in the Next.js dashboard. |
| D7 | Speed targets (to be measured, not promised) | First results from cache or DB < 2 s. Live answer for a city-level query: first live result < 5 s, full result set p50 < 30 s, bounded by each site's rate limits. |

---

## 4. Target design

```
Search box (Next.js /search)  ──►  POST /api/v1/discovery/search  (returns search_id)
                               ──►  GET  /api/v1/discovery/search/{id}/stream   (SSE: results appear as sources answer)

Query understanding (LLM, 1 call, cached)
   "elderly care, home care in Charlotte metro area"
   -> {categories:["home care agency","senior care","assisted living","home health"],
       synonyms:[...], geography:{type:"msa", name:"Charlotte-Concord-Gastonia", counties:[...], cities:[...]},
       want:["organizations","people","reviews","contacts"]}

Fan-out (asyncio.gather, per-source time budget, per-host token buckets, request coalescing)
   1. Local DB            places, orgs, people already stored       (instant)
   2. Google Maps         query x city grid -> place stubs -> deep place pipeline (details, services, reviews)
   3. CMS Care Compare    Medicare home health agencies, star ratings, ownership, addresses (official)
   4. NC DHSR / state     licensed facility lists (official)
   5. Web search          DuckDuckGo/Brave -> candidate sites + LinkedIn public URLs + directories
   6. Website crawler     SSRF-safe crawl of each org site: phones, emails, team, services, hours
   7. LinkedIn (public)   search-engine discovered /company/ and /in/ pages -> ld+json (+ Voyager if enabled)
   8. Enrichment          email finder, phone normalisation, MX/SMTP, GLEIF/tax IDs where relevant

Entity resolution (existing Splink/dedup + new quick key: normalised name + phone + domain + geo)
   -> one canonical organization with merged fields, every field carrying {value, source, url, retrieved_at, confidence}

Answer
   - Result cards (org, type, address, phone, website, hours, rating, services, license/CMS data, people, emails with labels, links)
   - LLM summary with numbered citations that point at stored source rows (no uncited claims)
   - Counts per source, timings, errors per source ("Google blocked: stopped", "LinkedIn public: 3 pages")
```

### Output for the example query
`elderly care, home care in Charlotte metro area` returns, per organization: name, category (home care agency,
assisted living, skilled nursing, adult day care), full address, phone(s), website, hours, Google rating and
review count with sentiment topics, services offered, CMS star rating and ownership type (when listed), NC licence
status (when listed), named people (owner, administrator, director of nursing) with role and source URL,
emails (labelled found/inferred/verified), social and LinkedIn URLs, and a source list with retrieval time.

### Making everything run quickly (measure first)
1. Benchmark harness first (`scripts/bench/`): requests/second per source, DB writes/second, end-to-end query time. Record a baseline.
2. One shared `httpx.AsyncClient` per source with HTTP/2, keep-alive and connection limits. Remove blocking `time.sleep`
   pacing; use per-host async token buckets so slow hosts do not slow fast ones.
3. Bounded concurrency per source from `config/rate_limits.yaml`. Speed gains come from parallelism across hosts,
   never from exceeding a site's limit.
4. Cache: `discovery_cache` table (key = normalised URL or query, TTL per source, ETag/Last-Modified, content hash).
   Skip unchanged pages. Coalesce identical in-flight requests.
5. Batch DB writes (`execute_values`), one transaction per batch, no per-row commits.
6. Stream results over SSE as each source returns, so the first card shows in seconds.
7. LLM off the hot path: one query-understanding call (cached), one final summary call, run in parallel with scraping.
8. Temporal fan-out: child workflows per city/source for big runs; interactive search uses in-process asyncio with the same adapters.
9. Report p50/p95 and per-source timings in the response and in Prometheus metrics.

---

## 5. Phased plan

| Phase | Work | Key files (new unless stated) |
|---|---|---|
| 0 | Recon of both repos, baseline benchmarks, confirm decisions D1-D7 | report only |
| 1 | Port `liscraper` into `packages/scrapers/linkedin/` as async-friendly code; public-first, Voyager behind flag; cookies from key vault, not a file | `packages/scrapers/linkedin/{client,public_profile,company,voyager,search}.py` |
| 2 | Port LeadIntel services (email finder, phone finder, verification, crawler, parser, dedup, disposable list) into `packages/leadintel/`; fix `verify=False`; reuse this project's SSRF crawler where it overlaps | `packages/leadintel/*` |
| 3 | Unified schema + legacy import with provenance | migration `017_discovery_schema.sql`, `scripts/migration/import_linkedin_folder.py` |
| 4 | Source adapters behind one interface: local DB, Google Maps query, CMS Care Compare, NC DHSR, web search, website crawl, LinkedIn public | `packages/discovery/sources/*.py` |
| 5 | Query understanding, geography expansion (Census CBSA/county data, not hard-coded), orchestrator, resolver, answer composer with citations | `packages/discovery/{planner,geo,orchestrator,resolver,answer}.py` |
| 6 | Speed layer: cache, token buckets, coalescing, batch writes, SSE, metrics | `packages/discovery/{cache,ratelimit,metrics}.py` |
| 7 | API + Temporal wrapper + Next.js pages (search box, live results, org/person detail, source panel, filters, export) | `packages/api/routers/discovery_router.py`, `frontend/src/app/(dashboard)/search/*` |
| 8 | Tests, benchmarks, docs, CI, cleanup of ported code | `tests/unit/discovery/`, `docs/operations/discovery.md` |

---

## 6. PROMPT A: implementation (paste into Antigravity)

---

### Role
Senior backend and full-stack engineer. Work in `C:\Users\OneData\Downloads\Data_Extraction\New_Extraction\DataExtraction`
(the "main repo": Python 3.12, FastAPI, Temporal, PostgreSQL, Next.js in `frontend/`). The folder
`C:\Users\OneData\Downloads\LinkedIN` is a read-only source. Never modify it, never copy its `.venv`, `venv`,
`.pytest_cache`, `data/exports`, `*.db` or `data/cookies.json` into the main repo. Use the GRAVITAS skill in `.agents/skills/gravitas/`.
Report only what you observed by running commands.

### Goal
Merge the LinkedIN folder's capabilities into the main repo and add a live, fast, source-cited search so that a
user can type `elderly care, home care in Charlotte metro area`, press **Search**, and see complete, merged,
cited results about organizations and people, streamed as sources answer. Also make the scraping pipelines faster
without exceeding any site's rate limits.

### Non-negotiable rules
1. **No secrets in the repo.** Never print, log, commit or store API keys or cookies. Use the existing key vault
   (`packages/infrastructure/key_vault/`) and redaction. Tests use fake values only.
2. **LinkedIn policy (decision D1):** public pages only by default. `LINKEDIN_AUTH_ENABLED=false` by default.
   If enabled, the cookie comes from the key vault (provider `linkedin`), the rate is capped at 30 requests/hour,
   and the UI shows a warning. On HTTP 999, 429, 401, 403, a login wall or CAPTCHA the source stops for that run and reports
   `blocked`. Never rotate identities to evade a block, never solve CAPTCHAs, never create or share accounts.
3. **Truthful output.** Every stored fact carries `source`, `source_url`, `retrieved_at`, `confidence`. Emails are labelled
   `found | inferred | verified` (D4). The answer composer may only state facts that exist in stored rows and must cite them.
   If a source returned nothing, say so. Never invent people, phones, emails or ratings.
4. **Privacy.** Enforce `kg_audit.suppression_lists` on every write and on every search result. Keep reviewer-name hashing.
5. **SSRF and robots.** All outbound page fetches of third-party sites go through the existing SSRF checks
   (`gmaps_scraper/website/ssrf.py`) and honour robots.txt. Remove `verify=False` from any ported code.
6. **One stack (D6).** No second FastAPI app, DB, Alembic setup or Vite app. Parameterized SQL only. Migrations idempotent (`IF NOT EXISTS`).
7. **No dumping of dead code.** Port only what is used; keep each ported module's tests; delete nothing in the source folder.
8. Windows + PowerShell commands only. Add every new dependency to `requirements.txt`.
9. Follow existing conventions (structured logger, `db_connector`, router style in `packages/api/routers/`, Temporal worker registration).

### Phase 0: recon (read-only; output a report before editing)
Read and summarise with file paths and line numbers:
* LinkedIN: `liscraper/*.py`, `backend/app/{services,scraper,models,api,utils}/*.py`, `backend/alembic/versions/*`, `frontend/src/{pages,services,types}/*`, `DECISIONS.md`, `scratch/*` (names and purpose only).
* Main repo: `packages/scrapers/google_maps/` (search.py, deep_place.py, deep_runner.py, website/*), `packages/domain/` (deduplication, splink_engine, contact_validator, smtp_engine, email_enricher, compliance_manager), `packages/infrastructure/{llm,key_vault,db_connector.py,migrations}`, `packages/temporal/{config.py,workers,workflows,activities}`, `packages/api/routers/search_router.py` (existing, do not break), `config/{rate_limits.yaml,agents.yaml}`, `frontend/src/app/(dashboard)`, `frontend/src/lib/api.ts`.
* Establish a **baseline**: run `tests/unit/ai_stack` and note the existing failing set of `tests/unit` (do not fix unrelated failures).
* Build a benchmark harness `scripts/bench/bench_sources.py` that measures, with mocked or local targets, requests/second, DB rows/second and wall time for: gmaps deep place run on fixtures, website crawl on a local test server, DB upsert of 10k rows. Save results to `scripts/bench/baseline.json`.
Then output: the exact file list you will create/modify, the migration number (next free after 016), and any conflict with the plan. Stop and ask only if a decision D1-D7 cannot be applied.

### Phase 1: LinkedIn client in the main repo
Create `packages/scrapers/linkedin/`:
* `client.py`: async HTTP client built on `httpx` (HTTP/2) for public pages, with per-host async token bucket, retry with jitter, circuit breaker on 999/429, and the exception types from `liscraper/http.py` (`Blocked`, `RateLimited`, `AuthExpired`, `Transient`). `curl_cffi` impersonation is optional: use it only for the flagged authenticated path, behind a lazy import, wrapped with `asyncio.to_thread`.
* `public_profile.py`, `company.py`: port `parse_public` and the Organization parser; keep the 4 real HTML fixtures as test fixtures under `tests/fixtures/linkedin/` (they are public pages; strip nothing else, keep sizes small by trimming to the ld+json blocks if > 200 KB).
* `voyager.py`, `search.py`: port, disabled unless `LINKEDIN_AUTH_ENABLED=true`.
* `discover.py` (new): given a query and location, use the web-search source to find `linkedin.com/in/` and `linkedin.com/company/` URLs (query forms like `site:linkedin.com/company "home care" Charlotte NC`), then fetch each public page politely and parse ld+json. Return normalized `PersonRecord` / `OrgRecord`.
* Cookies: read through the key vault (`provider="linkedin"`, JSON `{"li_at":..., "jsessionid":...}`), never from a file. Extend the key vault's allowed providers and the secrets router `Provider` literal to include `linkedin` and `search` (for search API keys).

### Phase 2: LeadIntel services
Create `packages/leadintel/` and port with tests: `email_finder.py`, `phone_finder.py` (phonenumbers, default region from the geo context), `verification_engine.py` (syntax, disposable list, role accounts, MX), `parser.py` (team-member extraction), `deduplication.py`, `disposable_domains.py`. Where the main repo already has equivalent logic (`packages/domain/contact_validator.py`, `smtp_engine.py`, `email_enricher.py`, `gmaps_scraper/website/*`), **reuse the main repo's version and delete the duplicate**. Port `search_discovery.py` into a web-search source (Phase 4) with TLS verification on and real error handling.
Port the email candidate generator and confidence logic from `liscraper/enrich.py` but make labels explicit (`inferred` unless an SMTP probe or page evidence exists).

### Phase 3: schema and legacy import
Migration `017_discovery_schema.sql` (schema `discovery_dataextraction`): 
* `organizations` (id UUID, canonical_name, normalized_name, category, subcategories JSONB, address fields, lat/lng, phones JSONB, emails JSONB `[{value,label,source_url,confidence}]`, website, domain, hours JSONB, rating, review_count, services JSONB, regulatory JSONB, social JSONB, linked_place_id, linked_company_id, first_seen, last_seen, quality_score).
* `people` (id, full_name, normalized_name, title, role_type, org_id FK, headline, city, region, country, profile_urls JSONB, emails JSONB, phones JSONB, provenance, verified BOOL, suppressed BOOL).
* `facts` (entity_type, entity_id, field, value JSONB, source, source_url, retrieved_at, confidence) with a unique key `(entity_type, entity_id, field, source, md5(value::text))`.
* `search_runs` (id, query, parsed JSONB, status, timings JSONB, source_status JSONB, started_at, finished_at), `search_results` (run_id, entity_type, entity_id, rank, score).
* `discovery_cache` (cache_key PK, source, payload JSONB, etag, last_modified, content_hash, fetched_at, expires_at).
* Indexes: trigram (`pg_trgm`, create extension if available, else btree) on names, GIN on JSONB, btree on `(normalized_name, domain)`, partial index on non-suppressed rows, and a `tsvector` column for text search.
`scripts/migration/import_linkedin_folder.py` (read-only access to the source folder, path from an argument, dry-run by default):
* Imports `data/liscraper.db` people/companies and `backend/lead_intel.db` contacts/companies/emails/phones/profiles. Dedupes across both. Sets `provenance='legacy_import'`. Rows whose `source_url`/notes show they came from `seed_tamilnadu_ceos.py` or `rectify_phones.py` (hand-typed) get `provenance='manual_seed'`, `verified=false`.
* Emails from `contact_emails` become `label='inferred'` unless `source_url` is a real page containing them.
* Prints a report: rows read, inserted, merged, skipped, per provenance. Idempotent.

### Phase 4: source adapters (`packages/discovery/sources/`)
Common interface: `async def search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]`, plus `name`, `rate_limit`, `healthcheck()`. Each adapter yields normalized `OrgRecord` / `PersonRecord` items with per-field provenance, never raises (returns a `SourceStatus` of ok/blocked/error/empty with a reason), and stops on `Budget` timeout.
1. `local_db.py`: Postgres full-text + trigram + geo filter over `discovery_dataextraction` and existing `staging_dataextraction.place_*`.
2. `google_maps.py`: text-query search around a city grid reusing `gmaps_scraper` (HttpClient, block detection). Extend `search.py` minimally to accept a text query term (keep the tile function unchanged). New stubs flow into the existing deep place pipeline (`deep_runner.run_deep_extraction`) for details, services, hours and reviews. A CAPTCHA/consent wall marks the source `blocked`.
3. `cms_care_compare.py`: official CMS provider data (home health agencies, hospice, nursing homes) via the data.cms.gov provider-data API. **Look up the current dataset ids from the official site at implementation time** and put them in config, do not guess. Filter by state/county/ZIP, map to organizations with CMS star rating, ownership type, services offered.
4. `state_registry.py`: pluggable state registry adapter; implement North Carolina (NC DHSR licensed facility/agency lists) from the official public downloads or pages, with the same interface so other states can be added by config. If an official file/endpoint is not machine-readable, implement the downloader + parser for the published file format and document the URL.
5. `web_search.py`: DuckDuckGo HTML by default; optional Brave/Tavily/SerpAPI selected by `SEARCH_PROVIDER`, keys from the key vault. Returns candidate sites, directories and LinkedIn URLs. Respects each provider's terms and rate limits.
6. `website_crawl.py`: SSRF-safe crawl of an organization's site (reuse `SafeWebsiteCrawler` and `WebsiteExtractor`): phones, emails (`found`), team/leadership, services, hours, social links.
7. `linkedin_public.py`: Phase 1 `discover.py` wrapped as a source.
8. `enrichment.py`: email candidates (`inferred`), MX check, phone normalisation, optional SMTP probe via Agent 7 for `verified`.
Add per-source limits to `config/rate_limits.yaml` and make adapters read them.

### Phase 5: planning, resolution, answer (`packages/discovery/`)
* `planner.py`: one cached LLM call (`get_llm()`, Pydantic `SearchIntent` schema) that returns categories, synonyms, geography text, wanted entity types, and filters. Deterministic fallback (keyword rules) when the LLM is unavailable or over budget.
* `geo.py`: resolve a place phrase to cities, counties, ZIPs, centroid and bounding box. Use Census CBSA/county/place data (download once, cache in `data/geo/`, document the source URL) instead of hard-coded lists. "Charlotte metro area" must resolve to the Charlotte-Concord-Gastonia MSA counties in NC and SC; show the resolved list in the response so the user can see what was searched.
* `orchestrator.py`: starts all applicable sources concurrently with a total budget (default 45 s) and per-source budgets, merges the stream, writes `search_runs`, persists new entities in batches, and emits events (`source_started`, `result`, `source_done`, `summary`, `done`).
* `resolver.py`: canonical entity resolution. Fast key (normalized name + phone, name + domain, name + geo within 150 m) then the existing dedupe/Splink path for borderline pairs. Merge rule: keep all values as facts; choose display value by source trust (official registry > website > Google Maps > search snippet > inferred), confidence and recency.
* `answer.py`: builds the cards and an LLM summary. The prompt gets only stored facts with ids; the model must cite fact ids; post-validate that every cited id exists and drop uncited claims. If the LLM is down, return cards without a summary.
* `ranking.py`: score by text relevance, geo distance, data completeness, source agreement, rating and review count.

### Phase 6: speed layer
* `ratelimit.py`: async token buckets per host and per source (from `config/rate_limits.yaml`); no global `time.sleep`.
* `cache.py`: `discovery_cache` get/put with TTL per source, conditional requests (ETag/Last-Modified), content-hash skip, and in-flight request coalescing.
* Batch writes with `execute_values`, one transaction per batch.
* Apply the same improvements to existing scrapers where measured: website verification/crawl activities (shared client, HTTP/2, bounded semaphores already exist: tune from the benchmark), deep place pipeline (fetch details and first review page concurrently, review pages sequential per place but many places in parallel up to the Google limit), federal/OSM writers (batch inserts). Change only what the benchmark shows is slow; keep behaviour identical and tests green.
* Prometheus metrics: per-source latency histogram, results count, error and block counters.
* Re-run `scripts/bench/bench_sources.py`, save `scripts/bench/after.json`, and print a before/after table.

### Phase 7: API, Temporal and UI
API (`packages/api/routers/discovery_router.py`, prefix `/api/v1/discovery`, auth like other routers):
* `POST /search` body `{query, sources?:[...], max_results?, include_unverified?:false, live?:true}` returns `{search_id, parsed_intent, resolved_geography}` immediately.
* `GET /search/{id}/stream` Server-Sent Events with the event types above.
* `GET /search/{id}` final JSON: cards, summary with citations, per-source status and timings.
* `GET /organizations/{id}`, `GET /people/{id}` with all facts and sources; `POST /search/{id}/export?format=csv|jsonl`.
* `GET /sources/status` health and recent block/error counts per source. Admin-only `PATCH /sources/{name}` to enable/disable.
Temporal: workflow `DiscoverySearchWorkflow` (geospatial queue) for large asynchronous runs with child workflows per city/source, plus activities wrapping the same adapters; register on the right worker and add to the planner's allowlist (`ALLOWLIST` in `autonomy_planner.py`, with parameter validators).
Frontend (Next.js, `frontend/src/app/(dashboard)/search/page.tsx` and components under `frontend/src/components/discovery/`):
* Prominent search box with example chips, a **Search** button, and a "Live internet search" toggle (on by default).
* Streaming results list that fills as sources answer; per-source status chips (ok, empty, blocked, error, time).
* Result card with the fields listed in section 4, badges for email labels, source links, "unverified" markers, copy and export buttons.
* Filters: category, county/city, rating, has phone/email/website, source, include unverified.
* Organization and person detail pages showing every fact with its source and time.
* The existing `/places/[id]` page links to the organization.
Add sidebar entry "Search". No secrets or cookies in client code.

### Phase 8: tests, docs, CI
Tests in `tests/unit/discovery/` and `tests/integration/discovery/` (offline: recorded fixtures or local test servers, no live calls in CI):
* Parsers: LinkedIn ld+json fixtures, CMS and NC registry fixture rows, DuckDuckGo result HTML fixture, website team/contact pages.
* Planner: LLM output parsed; LLM down uses fallback; geography expansion for Charlotte returns NC and SC MSA counties from a small Census fixture.
* Resolver: duplicate merge, no false merge for different branches, provenance preserved.
* Orchestrator: budget enforcement, one failing/blocked source does not stop others, SSE event order, partial results.
* Cache: TTL, conditional requests, coalescing (N identical calls = 1 fetch).
* Suppression: suppressed person never appears in storage or results.
* Answer: every citation id exists; uncited sentences removed; no-LLM path works.
* API: auth, validation, SSE format, export.
* Import script: dry-run vs apply, idempotent, `manual_seed` flagged, emails labelled `inferred`.
* LinkedIn: 999/429/401 stop the source; authenticated path off by default; cookie never logged.
* Migration applies twice.
Docs: `docs/operations/discovery.md` (how it works, sources, limits, adding a state registry, legal notes on LinkedIn and Google terms, how to enable the optional authenticated LinkedIn mode and its risks), update `README.md`, `.env.example` (empty placeholders: `SEARCH_PROVIDER`, `LINKEDIN_AUTH_ENABLED=false`, `DISCOVERY_TOTAL_BUDGET_SECONDS`, `DISCOVERY_CACHE_TTL_*`), CI workflow step for the new tests.

### Definition of done (show command output for each)
1. `ruff check` clean on touched files (`--select E9,F` too).
2. `pytest tests/unit/discovery tests/unit/ai_stack -q` passes; the pre-existing unit failures are unchanged (give before/after counts).
3. Migration 017 applies twice on a fresh test database.
4. `Select-String` secret scan over tracked and untracked files finds no real keys or cookies; no `li_at` values; no `verify=False`.
5. `npm run typecheck` and `npm run build` in `frontend/` succeed.
6. Benchmark before/after table printed; no benchmark regresses.
7. Import script dry-run and apply on a copy path report counts matching section 1 (178 people, 167 contacts) after dedupe.
8. Offline demo: with fixtures, the query `elderly care, home care in Charlotte metro area` returns merged organizations with phone, address, website, rating, CMS data, people, labelled emails and citations.
9. `git status` shows only intended files and nothing was written into the LinkedIN folder.

### Output format
Per phase: What changed (files), Evidence (verbatim trimmed command output), Not verified (and why). End with a requirement checklist
and `VERDICT: PASS` only if every item in the Definition of done has evidence, else `VERDICT: PARTIAL` with the gaps.
Never claim live behaviour of LinkedIn, Google, CMS or NC sources unless you ran it live in this session.

---

## 7. PROMPT B: independent verification (new session, did not write the code)

---

### Role
Adversarial reviewer and QA engineer. Assume the work is wrong until command output proves otherwise. Use GRAVITAS.
You may fix trivial defects; report anything larger without silently fixing it. Do not modify `C:\Users\OneData\Downloads\LinkedIN`.

### Step 1: scope check
`git status`, `git diff --stat`. List new/changed files. Compare with Prompt A phases 1-8 and flag every requirement with no code.
Confirm nothing was added under the LinkedIN folder: record `Get-FileHash` of `data/liscraper.db`, `lead_intel.db`, `backend/lead_intel.db` before and after running the import script; they must be identical.

### Step 2: safety and policy (highest priority)
1. Secret scan over tracked + untracked files for `gsk_[A-Za-z0-9]{20,}`, `AKIA[0-9A-Z]{16}`, `li_at`, `JSESSIONID`, `BEGIN PRIVATE`; also scan git history of new files. Cookie and key values must never appear in logs: run the LinkedIn client against a local mock server returning 999 and capture logs.
2. `Select-String -Pattern 'verify\s*=\s*False'` over `packages/` must return nothing.
3. LinkedIn: confirm `LINKEDIN_AUTH_ENABLED` defaults to false, the authenticated client is unreachable without it, cookies are read only from the key vault, and a mock 999/429/401/403/login-redirect response stops the source and reports `blocked` with no retry storm and no proxy/identity rotation.
4. SSRF: crawl requests to `http://127.0.0.1`, `http://169.254.169.254`, `http://[::1]`, `file://`, and a hostname resolving to a private IP are all refused. Redirect to a private IP is refused.
5. Robots: a disallowed path is not fetched (local test server).
6. Suppression: add a person to `kg_audit.suppression_lists`, run an import and a search; the person appears nowhere (DB tables, API JSON, SSE, exports).
7. Unauthenticated and non-admin calls to admin routes return 401/403.
8. LLM output safety: feed the answer composer a stored-facts set plus a model reply that cites a non-existent fact id and makes an uncited claim; both must be removed.

### Step 3: static and unit checks
`ruff check`, `python -m compileall packages -q`, import every new module, then `pytest tests/unit/discovery tests/unit/ai_stack -q`. Record before/after counts of the full `tests/unit` run in a baseline worktree (`git worktree add ../_base HEAD`, remove it afterwards) and prove no new failures.
Mutation spot checks (revert each with `git checkout -- <file>`): (a) disable the suppression filter, (b) make the resolver merge by name only, (c) remove the source time budget, (d) make `LINKEDIN_AUTH_ENABLED` default true, (e) stop labelling inferred emails. At least one test must fail for each; report any mutation that survives.

### Step 4: data and migration
Apply 017 twice on a fresh test database; inspect columns, constraints, indexes against Prompt A. Run the import script in dry-run, then apply twice: second run inserts 0 new rows. Counts must reconcile with the source (178 people in liscraper, 167 contacts in lead_intel, minus cross-duplicates), and a report of `legacy_import` vs `manual_seed` must exist. Spot check 20 imported emails: all are `inferred` unless a `source_url` page evidence exists. Confirm hand-typed rows are hidden by default in search.

### Step 5: behaviour with mocks (offline)
Local test servers or recorded fixtures stand in for Google, CMS, NC registry, DuckDuckGo, LinkedIn public pages and an organization website. Run the query `elderly care, home care in Charlotte metro area` and show:
* parsed intent and resolved geography (must list Mecklenburg, Union, Cabarrus, Gaston NC and York SC among the counties, from the Census fixture),
* SSE order: `source_started` for each source, results arriving before the slowest source finishes, then `summary` and `done`,
* one source forced to hang: total time stays within the budget and the response marks that source `timeout`,
* one source forced to return 429/CAPTCHA: marked `blocked`, others unaffected,
* the same organization from Google, CMS, and a website merges into one card with all phones/addresses kept as facts and the display value chosen by trust order,
* two different branches of one chain at different addresses do not merge,
* identical concurrent requests cause one fetch (coalescing), and a second search within TTL makes zero network calls to cached sources,
* the summary cites fact ids that exist; with the LLM disabled the cards still return.

### Step 6: performance
Re-run `scripts/bench/bench_sources.py`; compare to `baseline.json`. Report requests/second, rows/second, wall time, and p50/p95 for the offline search. Confirm no per-request `time.sleep` remains in async paths (`Select-String 'time\.sleep' packages/discovery packages/scrapers/linkedin`). Confirm rate limits still hold: a test with a 5 req/s bucket and 50 requests takes at least about 10 s. State plainly that real-world speed is bounded by site limits and was not measured live.

### Step 7: API, Temporal and UI
Exercise every endpoint with TestClient (validation errors, auth, SSE framing, export CSV/JSONL). Start a local Temporal dev server (`temporalio.testing.WorkflowEnvironment.start_local()`), run the real worker modules, execute `DiscoverySearchWorkflow` against fixtures, and confirm the planner allowlist accepts it only with validated parameters. Frontend: `npm ci`, `npm run typecheck`, `npm run build`; read the search page and confirm it uses only the API client, shows per-source status, labels email types, and contains no secrets. If Playwright is configured, run an offline smoke test with the API mocked.

### Step 8: docs honesty
Check README and `docs/operations/discovery.md` for claims not backed by code or evidence (speed numbers, source coverage, "verified" emails). Confirm the LinkedIn and Google terms warnings and the authenticated-mode risk are present.

### Report
Table: requirement | PASS / FAIL / NOT VERIFIED | evidence (command + key output). Defects by severity (safety, correctness, missing feature, polish) with file and line. `VERDICT: PASS` only if there are zero FAIL and zero NOT VERIFIED in Steps 2-6.

---

## 8. PROMPT C: acceptance run (new session, after Prompt B passes)

---

### Role
Release engineer. Prove it works on a real running stack. Do not print keys or cookies.

### Preconditions
Postgres reachable, `SECRETS_MASTER_KEY` set, Temporal available, Groq key added through the dashboard (or `GROQ_API_KEY` in the environment), network access. Report the state of each and stop if one is missing.

### Steps
1. Boot (`python start.py`), show `/healthz`, workers polling every queue, schedules registered.
2. Import: dry-run then apply `scripts/migration/import_linkedin_folder.py` on a **copy** of the LinkedIN folder's databases; show counts and provenance report.
3. Live search, politely and bounded: run `elderly care, home care in Charlotte metro area` with `max_results=25` through the UI Search button. Capture screenshots of: streaming in progress, final cards, a detail page, the source panel. Record per-source status, time to first result, total time, and counts per source.
4. For three of the returned organizations, open each source URL and compare phone, address and website by hand (list the differences). Report accuracy honestly, including wrong or missing fields.
5. Source behaviour: show which sources returned data, which were empty, which were blocked or timed out, and why. A `blocked` source is a valid result; do not work around it.
6. Cache: repeat the same search; show zero outbound calls to cached sources and the time difference.
7. Speed: run the benchmark again on the real stack; print before/after for the gmaps deep-place run (5 places), website crawl (20 sites) and DB upsert; state limits imposed by robots.txt and rate limits.
8. LinkedIn: with default settings confirm only public pages were requested, the log shows no cookie, and nothing authenticated ran. Do not enable the authenticated mode.
9. Privacy: add a test person to the suppression list, repeat the search, confirm absence everywhere.
10. Shutdown cleanly; confirm no orphan processes; run the secret scan again.

### Report
Per step PASS / FAIL / BLOCKED with commands, trimmed output and screenshot paths. List every discrepancy between source pages and stored data. Final line:
`ACCEPTANCE: PASS` only if all steps pass with evidence (BLOCKED is acceptable only for a third-party source that actually blocked, with proof). Otherwise `ACCEPTANCE: FAIL` plus a numbered list.
