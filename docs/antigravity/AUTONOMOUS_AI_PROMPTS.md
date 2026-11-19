# Antigravity Prompts: Autonomous AI Extraction

Three prompts, run in this order, each in a fresh Antigravity session:

1. **Prompt A**: Implementation (do the work, phase by phase).
2. **Prompt B**: Independent verification (a different session audits Prompt A's work).
3. **Prompt C**: End-to-end run (prove the whole system works with real data flow).

Rules for you (the human):
- Never paste a real API key into a prompt, a file in the repo, or a commit. The Groq key that was shared in chat must be **revoked and replaced**. Enter the new key later through the Settings page or `.env`.
- Run Prompt B and Prompt C in sessions that did not write the code.

---

# PROMPT A: IMPLEMENTATION

Paste everything between the lines into Antigravity.

---

## Role
You are a senior backend engineer working in the monorepo at the workspace root (DataExtraction: Python 3.12, FastAPI, Temporal, PostgreSQL/PostGIS, OpenSearch, Next.js in `frontend/`). Use the GRAVITAS skill in `.agents/skills/gravitas/`. Ground yourself in the code before editing anything. Report only what you observed by running commands in this session.

## Goal
Make the platform autonomous and AI-driven, in five parts:
1. A **secrets manager** that stores API keys, supports many keys per provider, and lets the user replace them daily without a restart.
2. A provider-agnostic **LLM layer**: Groq (model `openai/gpt-oss-120b`) now, AWS Bedrock ready for later.
3. A **deep place scraper** that stores everything about a place (details, services, address, contacts, reviews, people) in PostgreSQL.
4. An **autonomy planner agent** that decides what to extract and when, then starts the existing Temporal workflows by itself.
5. **API endpoints and dashboard pages** to manage keys and watch the planner.

## Hard constraints (do not break)
- **No secrets in the repo.** Never write an API key into source, tests, fixtures, docs, logs, or git history. Tests must use fake keys such as `gsk_test_fake_key_0000`. `.env.example` may only contain empty placeholders.
- Never log a full key. Show at most the last 4 characters.
- Do not delete or rewrite existing scrapers. Extend them or wrap them.
- Follow existing conventions (logging via `packages/infrastructure/structured_logger`, DB access via `packages/infrastructure/db_connector`, migrations as numbered SQL in `packages/infrastructure/migrations/`).
- All new SQL migrations must be idempotent (`IF NOT EXISTS`) and safe to run twice.
- Parameterized SQL only. No string-built queries.
- Do not add dependencies without adding them to `requirements.txt`. Prefer `httpx`, `cryptography`, `pydantic`, and `boto3`, whichever are already there.
- Do not touch files outside the paths listed below unless a listed file needs a one-line import or registration. If you must, say why in your report.
- Windows + PowerShell is the dev environment. Commands you run must work in `pwsh`.

## Phase 0: Reconnaissance (read-only, report before coding)
Read and summarize, with file paths and line numbers:
1. `packages/infrastructure/config_manager.py` and `db_config.py` (how secrets and AWS Secrets Manager are used today).
2. `packages/infrastructure/ollama_client.py` and `packages/domain/llm_entity_resolver.py` (current LLM calls).
3. `packages/scrapers/google_maps/` (what it already extracts: fields, reviews, pagination, anti-bot handling, output tables in `postgres_writer`).
4. `packages/infrastructure/migrations/` (highest migration number; schema naming; how `apply_*.py` runs migrations).
5. `packages/temporal/config.py`, `packages/temporal/schedules/register_schedules.py` (`TASK_QUEUE_MAP`), `config/schedules.yaml`, `scripts/ops/start_all_workers.py`, `infra/docker-compose.yml`.
6. `packages/agents/base_agent.py`, `packages/agents/tools/*`, `packages/agents/orchestration_agents/*`, `config/agents.yaml`.
7. `packages/api/main.py`, an existing router (e.g. `routers/orchestration.py`) and the auth dependency used by admin-only routes.
8. `frontend/` routes and API client, and an existing settings page.
9. How tests are organized under `tests/` and how they are run (`pytest` markers, `conftest.py`, DB bootstrap script).

Then output a short plan: the exact files you will create and modify, and the migration number you will use. Known issue to confirm while reading: the schedules for federal, gmaps, osm and DLQ point at queues no worker polls, and `infra/docker-compose.yml` references `packages.temporal.workers.federal_worker` and `gmaps_worker`, which do not exist. Confirm this and include it in the plan.

## Phase 1: Secrets manager
Create `packages/infrastructure/secrets/` with:
- `base.py`: `SecretBackend` interface: `get(provider) -> list[KeyRecord]`, `put`, `disable`, `mark_failed(key_id, reason, cooldown_s)`, `mark_used(key_id)`.
- `db_backend.py`: encrypted storage in PostgreSQL. Encrypt values with Fernet. The master key comes from env `SECRETS_MASTER_KEY`. If it is missing, raise a clear `ConfigurationError` at first use. Do not generate or store the master key silently.
- `env_backend.py`: reads `GROQ_API_KEY`, `GROQ_API_KEYS` (comma-separated), and the AWS variables.
- `aws_backend.py`: reads from AWS Secrets Manager when `USE_AWS_SECRETS=true`. Reuse the existing logic in `config_manager.py` instead of duplicating it.
- `manager.py`: `SecretsManager` facade.
  - Backend priority: DB, then AWS (if enabled), then env.
  - `get_active_key(provider)` returns the best usable key: status `active`, not expired, not in cooldown, lowest `priority`, then least recently used.
  - `report_failure(key_id, status_code)`: 401 or 403 sets the key to `invalid`. 429 sets a cooldown from `Retry-After` (default 60 s). 5xx does not penalize the key.
  - Reads the store on every call (small TTL cache of at most 5 s, invalidated on writes) so a newly added key works without a restart.
  - Thread-safe.
- `redaction.py`: a logging filter and helper `mask(key)` that returns `****abcd`. Install the filter on the root logger in `packages/infrastructure/structured_logger`. It must also redact any string matching `gsk_[A-Za-z0-9]{20,}` and `AKIA[0-9A-Z]{16}`.
- Migration `0NN_secrets_and_llm_usage.sql` (use the next free number) creating, in the schema that matches existing conventions:
  - `api_keys(id, provider, label, ciphertext, last4, status CHECK IN ('active','disabled','invalid','expired'), priority INT DEFAULT 100, expires_at, cooldown_until, daily_token_quota, created_at, created_by, last_used_at, fail_count)`.
  - `llm_usage(id, ts, provider, model, key_id, purpose, prompt_tokens, completion_tokens, latency_ms, status_code, success)`.
  - Index on `(provider, status)` and on `llm_usage(ts)`.

## Phase 2: LLM layer
Create `packages/infrastructure/llm/`:
- `base.py`: `LLMProvider` interface with `chat(messages, *, schema=None, temperature, max_tokens, purpose) -> LLMResult` and `healthcheck()`. `LLMResult` has `text`, `parsed` (when a schema was given), `usage`, `model`, `provider`.
- `groq_provider.py`:
  - Endpoint `https://api.groq.com/openai/v1/chat/completions` through `httpx`. Model from env `GROQ_MODEL`, default `openai/gpt-oss-120b`. Fallback model from `GROQ_FALLBACK_MODEL`, default `openai/gpt-oss-20b`.
  - Check Groq's current docs for gpt-oss structured output. If `response_format` with a JSON schema is supported, use it. If not, use JSON mode, validate with Pydantic, and re-ask the model up to 2 times with the validation error.
  - Pull the key from `SecretsManager` on each call. On 401 or 403, report the failure and retry once with the next key. On 429, report it, switch key if one exists, otherwise wait and retry with backoff (max 3 tries).
  - Write one row to `llm_usage` per call. Never store prompt text.
  - Timeouts: connect 5 s, read 60 s.
- `bedrock_provider.py`: uses `boto3` and the Converse API. Model id from `BEDROCK_MODEL_ID`. Credentials come from `SecretsManager` (provider `aws`) or the default boto3 chain. Must import lazily so the app runs without boto3 installed. It must be fully implemented, and its tests must mock boto3.
- `ollama_provider.py`: wraps the existing `ollama_client` so the old behavior is still available.
- `router.py`: `get_llm()` returns the provider named by `LLM_PROVIDER` (`groq|bedrock|ollama`, default `groq`). Supports an ordered fallback chain `LLM_FALLBACK_CHAIN=groq,bedrock,ollama`. Enforces a daily token budget `LLM_DAILY_TOKEN_BUDGET` using `llm_usage`. When the budget is exceeded, raise `LLMBudgetExceeded` (callers must degrade gracefully).
- Update `packages/domain/llm_entity_resolver.py` to call `get_llm()` instead of Ollama directly. Behavior with `LLM_PROVIDER=ollama` must be unchanged.

## Phase 3: Deep place scraper and storage
Based on Phase 0 findings, extend `packages/scrapers/google_maps/` (do not rewrite it). For each place, collect and store:
- **Core:** place id, name, categories, full address and its parts, latitude and longitude, phone, website, opening hours, price level, rating, review count, services and amenities, "about" attributes, photo URLs (links only, no binary download).
- **Reviews:** all reviews by paginated scrolling or loading until none remain (configurable cap `MAX_REVIEWS_PER_PLACE`, default 500, 0 means unlimited). For each: review id, rating, text, language, published date (absolute date, not "2 weeks ago"), owner reply text and date, and reviewer display name.
- **Reviewer name handling:** controlled by env `REVIEWER_NAME_MODE=hash|plain`, default `hash` (store a salted SHA-256, salt from `REVIEWER_HASH_SALT`). With `plain` the real name is stored. Both modes must honor the existing suppression and opt-out (GDPR/CCPA) tables so a suppressed person is never stored.
- **Contacts and people:** crawl the place website (reuse the existing website crawler and its SSRF protections: allowed ports 80 and 443, 5 MB response cap). Extract emails, phones, social links, and people names with roles. Use `get_llm()` with a Pydantic schema for unstructured text. If the LLM is unavailable, fall back to regex extraction for emails, phones and links, and mark records `extraction_method='regex'`.
- **LLM enrichment (batched, budget aware):** review sentiment and topic tags, and a normalized services list. Keep this in a separate, skippable step so scraping works without any LLM.
- **Politeness:** respect `config/rate_limits.yaml`, randomized delays, and retry with backoff. Be honest about blocking: if the page returns a CAPTCHA or consent wall, record `blocked` in the run status and stop. Do not try to bypass CAPTCHAs.

Create migration `0NN+1_place_deep_data.sql` with tables `place_details`, `place_services`, `place_reviews`, `place_contacts`, `place_people`. Every row carries `source`, `source_url`, `scraped_at`, `run_id`. Use unique constraints so re-scraping upserts (`ON CONFLICT DO UPDATE`) and never duplicates. Link to existing organizations and persons through foreign keys or a mapping table, following the existing identity-resolution design. Indexes on `place_id`, `(place_id, review_id)`, and `published_at`.

Add Temporal activities in `packages/temporal/activities/` and a workflow `PlaceDeepExtractionWorkflow` (input: place ids or a region and category). It must be idempotent, send heartbeats, and use the retry policies from `packages/temporal/config.py`. Register it on the geospatial worker (`geospatial-domain-queue`).

## Phase 4: Autonomy planner agent
Create `packages/agents/orchestration_agents/autonomy_planner.py` extending `base_agent.py`, plus a Temporal workflow `AutonomyPlannerWorkflow` on `governance-quality-queue`.
- **Inputs (gathered by SQL, no LLM):** row counts per source, staleness (age of last successful run per source/region), DLQ size, failed runs in the last 24 h, DB pool usage, current running workflows, today's LLM token usage, and coverage gaps (regions or categories in config with few or no places).
- **Decision:** ask `get_llm()` for a JSON plan validated by a Pydantic schema: a list of actions `{workflow, task_queue, params, priority, reason}`.
- **Guardrails (enforced in code, not in the prompt):**
  - Only workflows in an explicit allowlist can be started.
  - Max concurrent runs per queue and a global cap, from `config/agents.yaml`.
  - Respect `human_approval_required` flags already defined for agents.
  - Never start a workflow that is already running with the same params (use deterministic workflow ids).
  - Dry-run mode (`PLANNER_DRY_RUN=true`) records decisions but starts nothing.
- **Fallback:** when the LLM is unavailable or over budget, use deterministic rules (stale source gets re-run; DLQ below threshold gets replayed).
- **Execution:** start workflows through `agents/tools/temporal_tool.py`.
- **Audit:** create `planner_decisions(id, ts, inputs_json, plan_json, executed_json, mode, llm_provider, llm_model)` in a new migration. Every cycle writes one row.
- Schedule it every 15 minutes via `config/schedules.yaml`, and add an entry in `config/agents.yaml`.

## Phase 5: Fix the known orchestration mismatches
- Make every schedule in `config/schedules.yaml` and `TASK_QUEUE_MAP` point at a queue that a worker really polls, using the 7-agent queues from `packages/temporal/config.py`. Register each workflow on the worker that serves that queue.
- Remove or fix the `worker-federal` and `worker-gmaps` services in `infra/docker-compose.yml` so no container references a missing module.
- Make `start.py` register schedules after Temporal is ready, and replace the blind "SUCCESS" message for workers with a real check (worker process alive after a short wait).
- Update the stale parts of `README.md` (queues, frontend path, agents list). Do not claim a test count you did not measure.

## Phase 6: API and dashboard
Backend (`packages/api/routers/`):
- `secrets.py` (admin only, use the existing auth dependency):
  - `POST /api/v1/secrets/keys` (provider, label, value, priority, expires_at)
  - `GET /api/v1/secrets/keys` (masked: label, last4, status, expires_at, last_used_at, fail_count; never the value)
  - `PATCH /api/v1/secrets/keys/{id}` (status, priority, expires_at)
  - `DELETE /api/v1/secrets/keys/{id}`
  - `POST /api/v1/secrets/keys/{id}/test` (one tiny LLM call to check the key works)
- `llm.py`: `GET /api/v1/llm/status` (active provider, model, today's tokens vs budget, healthcheck).
- `planner.py`: `GET /api/v1/planner/decisions`, `POST /api/v1/planner/run` (run one cycle, with `dry_run` option), `GET/PUT /api/v1/planner/config`.
- `places.py`: `GET /api/v1/places/{place_id}` (details with services, contacts, people), `GET /api/v1/places/{place_id}/reviews` (paginated), `POST /api/v1/places/extract` (start a deep extraction).
- Register routers in `packages/api/main.py`. Add Pydantic request/response models. Return no secret values anywhere.

Frontend (`frontend/`, follow existing components and API client patterns):
- `Settings > API Keys`: table of keys, add/replace/disable/test buttons, provider selector (groq, aws). The value field is write-only and cleared after submit.
- `Autonomy` page: planner decisions timeline, run-now button with dry-run toggle, LLM usage vs budget.
- A place detail view showing services, contacts, people and reviews.

## Phase 7: Configuration
Update `.env.example` with empty placeholders only: `SECRETS_MASTER_KEY`, `LLM_PROVIDER`, `LLM_FALLBACK_CHAIN`, `GROQ_MODEL`, `GROQ_FALLBACK_MODEL`, `GROQ_API_KEY`, `GROQ_API_KEYS`, `BEDROCK_MODEL_ID`, `AWS_REGION`, `LLM_DAILY_TOKEN_BUDGET`, `REVIEWER_NAME_MODE`, `REVIEWER_HASH_SALT`, `MAX_REVIEWS_PER_PLACE`, `PLANNER_DRY_RUN`. Add a short `docs/operations/autonomous-ai.md` explaining key rotation (add a new key daily in Settings, old key can be disabled or left to expire), switching to AWS, and the reviewer-name privacy setting.

## Tests you must write (this task explicitly requires them)
Place under `tests/unit/` and `tests/integration/`, using the existing layout:
- Secrets: encrypt/decrypt round trip, missing master key error, key selection order, cooldown after 429, invalid after 401, expired key skipped, new key used with no restart, redaction filter masks `gsk_...` and `AKIA...`.
- LLM: Groq provider against a mocked HTTP server (`respx` or `httpx.MockTransport`) covering success, 429 with key switch, 401 with key switch, malformed JSON re-ask, budget exceeded, fallback chain. Bedrock provider with mocked boto3.
- Scraper: parse fixtures (saved HTML/JSON snippets, no real personal data) for details, reviews with pagination, relative-date conversion, `hash` vs `plain` reviewer mode, suppression honored, upsert idempotency (running twice gives the same row counts).
- Planner: guardrails (allowlist, concurrency cap, dry run, duplicate prevention), LLM-down fallback, audit row written.
- API: admin-only access, no secret value ever in a response, validation errors.
- Migrations: apply on an empty DB twice with no error.

## Definition of done (all must be shown with command output)
1. `ruff check packages tests` clean for the files you touched.
2. `pytest` on the new and affected tests passes, and the pre-existing unit suite has no new failures (give before and after counts).
3. All new migrations apply twice with no error on a fresh test DB.
4. `Select-String -Path (git ls-files) -Pattern 'gsk_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}'` returns nothing (except obvious fake test keys named `gsk_test_fake_key_*`).
5. Frontend: `npm run typecheck` (or `tsc --noEmit`) and `npm run build` succeed.
6. `git status` shows only intended files.

## Output format
For each phase: **What changed** (files), **Evidence** (verbatim command output, trimmed), **Not verified** (anything you could not run and why). End with a requirement checklist (each requirement above, status, evidence) and `VERDICT: PASS` only if every item in the Definition of done has evidence. Otherwise `VERDICT: PARTIAL` with the list of gaps. Do not claim live Groq or live Google Maps behavior unless you ran it.

---

# PROMPT B: INDEPENDENT VERIFICATION

Use a **new session**. Do not reuse Prompt A's context. Paste everything between the lines.

---

## Role
You are an adversarial reviewer and QA engineer. You did not write this code. Assume it is wrong until command output shows otherwise. Use GRAVITAS. You may fix trivial defects (typos, missing imports); for anything larger, report it and do not fix it silently.

## Goal
Verify that the autonomous AI feature set described in `docs/antigravity/AUTONOMOUS_AI_PROMPTS.md` (Prompt A) is implemented correctly, securely, and completely. Produce a requirement-by-requirement report backed by command output.

## Step 1: Inventory
- Run `git status` and `git diff --stat` against the base commit. List new and changed files.
- Compare against Prompt A's file list. Flag every requirement with no matching code.

## Step 2: Secret hygiene (highest priority)
Run and show the output of each:
1. `git ls-files | ForEach-Object { Select-String -Path $_ -Pattern 'gsk_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|PRIVATE)' -ErrorAction SilentlyContinue }`
2. `git log -p --all -S'gsk_' -- . ` to check history for key-like strings.
3. Confirm `.env` is git-ignored and `.env.example` has only empty values.
4. Read `redaction.py` and prove with a small script that `logging` output of a message containing a fake `gsk_` key and an `AKIA` key is masked.
5. Call `GET /api/v1/secrets/keys` and confirm responses never contain the ciphertext or full value. Confirm the DB column holds ciphertext, not plain text (`SELECT ciphertext FROM ... LIMIT 1`).
6. Confirm the master key is required and there is no hardcoded default.
7. Confirm non-admin tokens get 401 or 403 on every `/secrets` route.

## Step 3: Static checks
`ruff check packages tests`, `python -m compileall packages -q`, and import every new module (`python -c "import packages.infrastructure.secrets.manager, packages.infrastructure.llm.router, ..."`). Report any failure verbatim.

## Step 4: Tests
- Run the full new test set and the existing unit suite: `pytest tests/unit -q`. Record pass/fail counts and compare to the baseline from `git stash` or the base commit if available.
- Mutation spot checks (revert after each with `git checkout -- <file>`): (a) make `report_failure` a no-op, (b) remove the allowlist check in the planner, (c) make the reviewer hash mode store plain names. Confirm at least one test fails for each. If none fails, the tests are too weak; report it.

## Step 5: Migrations
On a fresh disposable database, apply all migrations in order, then apply the new ones a second time. Show output. Run `\d` equivalents (`SELECT ... FROM information_schema.columns`) for each new table and confirm the columns, unique constraints and indexes from Prompt A exist.

## Step 6: Behavior checks with mocks
- Rotate keys: insert two fake keys, force a 429 on the first, confirm the second is used and the first enters cooldown. Insert a third key while the process is running and confirm it is picked up with no restart.
- LLM fallback chain: simulate Groq down, confirm fallback; simulate budget exceeded, confirm `LLMBudgetExceeded` and that the planner uses its deterministic fallback.
- Planner guardrails: ask the mocked LLM to return a non-allowlisted workflow, an oversized batch, and a duplicate. Confirm each is rejected and logged.
- Scraper idempotency: run extraction twice on the same fixture and confirm row counts are identical.
- Suppression: add a suppressed person and confirm no row is created in any mode.

## Step 7: Orchestration consistency
Programmatically confirm: every `task_queue` in `config/schedules.yaml` and `TASK_QUEUE_MAP` is polled by a worker in `scripts/ops/start_all_workers.py`; every workflow registered by schedules is registered on that worker; every `command:` module path in `infra/docker-compose.yml` imports successfully. Show the script and its output.

## Step 8: Frontend
`npm ci`, `npm run typecheck` (or `tsc --noEmit`), `npm run build` in `frontend/`. Confirm the key value input is write-only and cleared after submit by reading the component.

## Step 9: Docs honesty
Check `README.md` and `docs/operations/autonomous-ai.md` for claims not backed by code (for example a test count, or features that do not exist).

## Report format
A table: requirement | status (PASS / FAIL / NOT VERIFIED) | evidence (command and key output lines). Then a list of defects ordered by severity (security, correctness, missing feature, polish) with file and line. End with `VERDICT: PASS` only if there are zero FAIL and zero NOT VERIFIED in steps 2 to 7. Otherwise `VERDICT: FAIL` and list what must change.

---

# PROMPT C: END-TO-END RUN

Use a **new session**, after Prompt B returns PASS. This one needs a real (new, non-leaked) Groq key. Put it in `.env` as `GROQ_API_KEY` or add it through the Settings page. Do not print it.

---

## Role
You are the release engineer proving the system works as a whole. You run the real stack and observe real data moving from trigger to database to API to UI. Use GRAVITAS. Do not mock anything in this prompt except where stated.

## Preconditions (check and report, stop if any fails)
- PostgreSQL is reachable, `SECRETS_MASTER_KEY` is set, Temporal binary or Docker is available, Node 20+ and Python 3.12+ are installed.
- `GROQ_API_KEY` is present in the environment or the secrets store (check by masked value only).

## Steps
1. **Boot:** `python start.py` (or Docker compose if specified). Wait until ports 7233, 8000, 3000 and 8233 respond. Show the health check (`GET /healthz`). Confirm 7 workers are polling: use the Temporal UI/API to list pollers for every queue in `packages/temporal/config.py` and show the output. Confirm schedules are registered and list them.
2. **Secrets flow:** through the API, add a Groq key (value from env, never printed), list keys (masked), call `/test` on it and show success. Add a second deliberately invalid fake key with a lower priority number, run an LLM call, and show that the system marks it `invalid` and uses the good key. Disable it afterwards.
3. **LLM live smoke test:** call `GET /api/v1/llm/status`; then make one real structured call through `get_llm()` (for example extract name and role from a short sample sentence) and show the parsed JSON and the `llm_usage` row.
4. **Deep scrape, small and real:** pick one small, bounded target (for example 3 places for one category in one city, with `MAX_REVIEWS_PER_PLACE=30`). Start `PlaceDeepExtractionWorkflow` through `POST /api/v1/places/extract`. Watch it in Temporal until it completes. If Google blocks the scrape (CAPTCHA or consent wall), report `BLOCKED` with evidence; do not try to bypass it, and rerun the same flow using the saved fixtures to prove the rest of the pipeline.
5. **Database proof:** run SQL and show counts and sample rows (mask personal data in the report) for `place_details`, `place_services`, `place_reviews`, `place_contacts`, `place_people`, and `llm_usage`. Re-run the same extraction and show the counts did not grow (idempotency). Show that with `REVIEWER_NAME_MODE=hash` no plain reviewer name is stored.
6. **Planner:** run `POST /api/v1/planner/run` with `dry_run=true` and show the stored decision. Then run with `dry_run=false` and show that an allowed workflow actually started in Temporal and its result. Show the `planner_decisions` rows. Stop the LLM by temporarily disabling all keys and run again; show the deterministic fallback decision. Re-enable the key.
7. **Scheduled behavior:** trigger one of the registered schedules manually (`temporal schedule trigger`) for each previously mismatched schedule (federal, gmaps, osm, DLQ) and prove a worker picked it up (the workflow leaves "Scheduled" state and starts). A failing scrape because of missing source API keys is acceptable, but a workflow stuck with no worker is a FAIL.
8. **API and UI:** `GET /api/v1/places/{id}` and `/reviews` return the stored data. Using Playwright (existing setup in `frontend/` or `tests/playwright`), open the API Keys page, the Autonomy page and a place detail page, take screenshots, and assert key values are not visible anywhere in the DOM.
9. **Rotation without restart:** while the stack is running, add a new key via the UI, disable the previous one, trigger an LLM call, and show the new key's `last_used_at` changed and no process restarted (compare PIDs before and after).
10. **Teardown:** stop all processes cleanly with Ctrl+C or the shutdown path; confirm no orphan processes remain.
11. **Leak scan:** search logs (`logs/`, process output), the DB (`SELECT ... WHERE ciphertext LIKE 'gsk_%'` must return nothing), and the repo for the real key's value. Report the result.

## Report format
For each step: PASS, FAIL or BLOCKED, the exact commands run, and trimmed verbatim output. Include screenshots paths. List anything not verified and why. Finish with:
- `E2E VERDICT: PASS` only if steps 1 to 11 all pass with evidence (BLOCKED in step 4 is acceptable only if the fixture rerun passes).
- Otherwise `E2E VERDICT: FAIL` with a numbered list of failures, each with the log lines and a suspected cause.

Do not declare success from exit codes alone. Each claim needs observed output.

---
