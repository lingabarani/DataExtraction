# Live Discovery Search: Operations Guide

The Live Discovery page (`/search` in the dashboard) takes a plain-language query such as
`elderly care, home care in Charlotte metro area`, queries several public sources at the same time, merges
duplicates and returns organization cards in which every value is tied to the source it came from.
No data is invented. A source that has no data, does not apply, or blocks the request says so in the
source panel (`empty`, `Not applicable`, `blocked`, `unavailable`, `timeout`).

## 1. How a search runs

1. **Plan** (`packages/discovery/planner.py`, `geo.py`, `world_geo.py`): the query is split into "what" and
   "where" (text after the last "in" / "near" / "around" / "at", or after the last comma).
   - U.S. places are resolved offline from Census files in `data/geo/` (metro areas, counties, places, ZIPs).
   - Anywhere else ("home care in Chennai", "hospitals in RS Puram, Coimbatore", "restaurants in Paris, France") is
     looked up with OpenStreetMap Nominatim: free, at most 1 request per second, cached in
     `data/geo/world_cache.json` for 30 days. Set `NOMINATIM_EMAIL` to send a contact address with each request.
   - A U.S. result is kept only when it accounts for every word of the location, so "Coimbatore, TN" is not read as
     Tennessee and "Anna Nagar, Chennai" is not read as Anna, TX.
   - There is no default location: a query without one, or a place that cannot be found, returns `needs_location`.
   - Outside the U.S. the Medicare and state licence sources report "Not applicable"; Google Maps, web search,
     company websites and saved results work everywhere.
2. **Sources in parallel** (`packages/discovery/sources/`), each streaming results as they arrive:

   | Source | What it provides | Runs when |
   |---|---|---|
   | `local_db` | Organizations already stored in PostgreSQL | always |
   | `cms_care_compare` | Medicare home health, nursing home, hospice records (CCN, star rating, ownership) from the CMS Provider Data API | care queries only |
   | `state_registry` | NC DHSR licence lists (licence #, administrator, address, phone). Other states report "no adapter" | care queries in NC |
   | `google_maps` | Listings, ratings, review counts, hours, website (`DISCOVERY_DISABLE_GOOGLE_MAPS=true` turns it off) | always |
   | `web_search` | DuckDuckGo HTML results; directory/listicle pages are kept as references only | always |
   | `linkedin_public` | Public company pages only. HTTP 403/429/999 stops the source as `blocked` | always |
   | `website_crawl` | Up to 3 pages per organization website, honouring robots.txt; published phones, emails, team names | after the first stage |
   | `enrichment` | Phone normalisation and email labelling (`found` / `inferred` / `verified`) | after the crawl |

3. **Merge** (`resolver.py`): records are linked by domain, phone + similar name, name + ZIP, street + ZIP,
   CMS CCN or NC licence number. Display values follow the trust order (registry/CMS above Google above web).
4. **Answer** (`answer.py`): ranked cards, a short cited summary and the per-source counts.
   The answer is saved to `search_runs.answer` (migration 018), so a finished search can be replayed after a restart.

Measured on the Charlotte query above (live, Nov 2026): first results after about 1 s, full answer after
17 to 22 s, about 1,070 merged organizations from about 1,300 source records.

## 2. API

All endpoints require a bearer token unless `AUTH_REQUIRED=false`.

| Method and path | Purpose |
|---|---|
| `POST /api/v1/discovery/search` | Start a search. Body: `{"query": "...", "filters": {...}, "budget_seconds": 45}`. Returns 202 with `search_id` and `stream_url`. Filters below |
| `GET /api/v1/discovery/search/{id}/stream` | Server-sent events: `plan`, `source_started`, `result`, `snapshot`, `source_done`, `entities_resolved`, `answer`, `done` (or `needs_location`). A finished search replays its stored answer; a second live listener gets 409 |
| `GET /api/v1/discovery/search/{id}` | Stored status and answer |
| `GET` or `POST /api/v1/discovery/search/{id}/export?format=csv\|jsonl` | Export the shown cards |
| `GET /api/v1/discovery/organizations/{org_id}` | Organization detail with facts and people |
| `GET /api/v1/discovery/people/{person_id}` | Person detail (suppressed people are never returned) |
| `GET /api/v1/discovery/searches` | Recent searches |
| `GET /api/v1/discovery/sources/status?probe=true` | Adapter health (admin only) |

### Search options (`filters`)

| Filter | Values | Page control | Effect |
|---|---|---|---|
| `sources` | `"all"` (default), `"internet"` | Search in: Internet + saved / Internet only | `internet` skips `local_db`, so every result comes from a live source |
| `crawl_websites` | `true` (default), `false` | Details: Full / Fast | `false` skips company websites, LinkedIn and email checks; finishes in about 2 to 5 s |
| `max_results` | 1 to 1000 (default 50) | Results | Cards in the final answer and export; Google Maps fetches more pages (up to 5 per area, 24 requests per search) for larger values |
| `include_unverified` | bool | Include unchecked imported leads | Shows `manual_seed` legacy rows from the saved database |

`snapshot` events carry the merged, ranked cards found so far (up to 200, at most every 0.6 s). The page shows
them immediately; names become clickable and CSV export is enabled when the final `answer` arrives (ids are final
only after the results are saved).

Measured live (Nov 2026, browser timings): "plumbers in Austin, TX", Internet only + Fast, up to 250: first card
1.4 to 2.5 s, finished 2.8 to 3.8 s, about 100 results. "elderly care, home care in Charlotte metro area",
Internet + saved + Full, up to 1000: first card 0.9 s, finished 14 to 23 s, about 1,190 results.

## 3. Setup and running

```powershell
# 1. Python and frontend dependencies (once)
pip install -r requirements.txt
cd frontend; npm install; cd ..

# 2. .env in the project root (copy .env.example). Needed for discovery:
#    POSTGRES_* , SECRETS_MASTER_KEY, REVIEWER_HASH_SALT, AUTH_REQUIRED, CORS_ORIGINS=http://localhost:3000

# 3. Database migrations (includes 015-018 for the AI layer and discovery)
python -m packages.infrastructure.migration_manager

# 4. Census geography files (about 20 s; also downloaded automatically on first search if missing)
python scripts/data/fetch_census_geo.py

# 5a. Everything at once: PostgreSQL check, Temporal, workers, API on :8000, frontend on :3000
python start.py

# 5b. Or only what the search page needs, in two terminals
python -m uvicorn packages.api.main:app --host 127.0.0.1 --port 8000
cd frontend; npm run dev
```

Open http://localhost:3000/search. API docs are at http://localhost:8000/api/docs.

NC registry spreadsheets are cached in `data/registry/nc/` for 7 days (`DISCOVERY_REGISTRY_DIR` overrides the
base folder). Census files live in `data/geo/` with their source URLs in `data/geo/SOURCES.md`.

## 4. Tests

The tests use a separate database (`dex_ai_test`) and must not read `.env`, which points at the real database:

```powershell
$env:DEX_SKIP_DOTENV='true'; $env:POSTGRES_USER='postgres'; $env:POSTGRES_PASSWORD='postgres'
$env:POSTGRES_DB='dex_ai_test'; $env:POSTGRES_HOST='127.0.0.1'
$env:SECRETS_MASTER_KEY=(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
$env:REVIEWER_HASH_SALT='unit'
python -m pytest tests/unit/discovery tests/unit/ai_stack -q
```

Remove those variables (or open a new terminal) before starting the API, otherwise it connects to `dex_ai_test`
and ignores `.env`.

## 5. Known limits

- LinkedIn usually answers HTTP 403 to unauthenticated requests, so `linkedin_public` is often `blocked`.
  Authenticated scraping is disabled (`LINKEDIN_AUTH_ENABLED=false`) and should stay that way.
- Only North Carolina has a state licence adapter. South Carolina parts of the Charlotte metro show "no adapter for SC".
- Google Maps and DuckDuckGo are scraped without an official API; they can rate-limit or change markup,
  and their terms of service restrict automated access. Review that before commercial use.
- Legacy rows imported from the old LinkedIn folder are `manual_seed` / unverified and are hidden unless
  "Include unverified imported leads" is ticked.

## 6. Legacy import

```powershell
python scripts/migration/import_linkedin_folder.py --source-dir "C:\Users\OneData\Downloads\LinkedIN"          # dry run
python scripts/migration/import_linkedin_folder.py --source-dir "C:\Users\OneData\Downloads\LinkedIN" --apply  # write
```
