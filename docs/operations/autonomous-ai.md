# Autonomous AI operations

This covers API keys, the LLM provider, deep place scraping and the autonomy planner.

## 1. First-time setup

1. Generate the master key that encrypts stored API keys and put it in `.env`:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
   `SECRETS_MASTER_KEY=<output>`. Keep it. Losing it makes stored keys unreadable (re-add them).
2. Apply migrations: `python -m packages.infrastructure.migration_manager` (adds 015 and 016).
3. Start the stack (`python start.py`). It now registers the Temporal schedules and checks that the
   workers stay alive.
4. Open **Settings > AI Keys** in the dashboard and add your Groq key. It is used on the next request.

## 2. Daily key rotation

* Add the new key each day in **Settings > AI Keys** (or `POST /api/v1/secrets/keys`). Give it a lower
  priority number than the old one so it is used first.
* Disable or delete the old key, or set an expiry date when you add it.
* The platform also rotates by itself: HTTP 401/403 marks a key `invalid`, a long HTTP 429 puts it in cooldown,
  and the next key is used. A short 429 (retry-after of 10 s or less) is waited out on the same key.
* Key order: dashboard keys, then AWS Secrets Manager (`USE_AWS_SECRETS=true`), then environment
  (`GROQ_API_KEY`, `GROQ_API_KEYS=k1,k2`).
* Values are encrypted with Fernet, shown only as `****last4`, and scrubbed from logs.
  If a key was ever pasted into chat, email or a ticket, revoke it at the provider and create a new one.

## 3. Switching to AWS

* Secrets: `USE_AWS_SECRETS=true`, `AWS_SECRETS_NAME=<secret>`, `AWS_REGION`. The secret is a JSON object
  with `GROQ_API_KEY` and/or `GROQ_API_KEYS`.
* LLM: `LLM_PROVIDER=bedrock`, `BEDROCK_MODEL_ID=<model id enabled in your account>`. Credentials come from an
  IAM role, the standard AWS environment variables, or an `aws` key added in the dashboard as JSON:
  `{"access_key_id":"...","secret_access_key":"...","session_token":"..."}`.
* To fail over automatically: `LLM_PROVIDER=groq` and `LLM_FALLBACK_CHAIN=bedrock,ollama`.
* Switching provider needs no code change, but environment variables are read when a process starts, so restart
  the API and workers after changing `LLM_PROVIDER`. API keys added in the dashboard need no restart.

## 4. Deep place scraping

Run for places already found by the Google Maps collector:

```
POST /api/v1/places/extract   {"region": "US-CA", "category": "dentist", "max_places": 25}
POST /api/v1/places/extract   {"place_ids": ["123456789"]}
```

For each place it stores details, services, address, hours, all reviews (up to `MAX_REVIEWS_PER_PLACE`),
website contacts (emails, phones, social links) and named people, in `staging_dataextraction.place_*`.
Re-running updates rows and never duplicates them. Read results with `GET /api/v1/places/{id}` and
`/reviews`, or open `/places/<id>` in the dashboard.

* **Reviewer names**: `REVIEWER_NAME_MODE=hash` (default) stores a keyed hash only. `plain` stores real names.
  Reviewer names are personal data under GDPR/CCPA. Anyone in `kg_audit.suppression_lists` is skipped in both modes.
* **Google Terms**: scraping Google Maps is against Google's Terms of Service. You accept that risk.
* **Blocks**: on a CAPTCHA or consent wall the run stops and reports `blocked`. It does not try to get around it.
  Slow down (`PLACE_DELAY_*`), use fewer places per run, or wait.
* The LLM adds sentiment and topics to reviews and extracts people and services from website text. Without a
  key those steps are skipped and regex extraction still runs.

## 5. Autonomy planner

* Runs every 15 minutes (schedule `autonomy-planner-cycle`) and from **Autonomy** in the dashboard.
* It reads platform signals, asks the LLM for a plan, then enforces rules in code: allowlisted workflows only,
  clamped parameters, concurrency caps, no duplicate starts, human approval for full federal refresh and OSM.
* **It ships in dry-run mode** (`PLANNER_DRY_RUN=true`): decisions are recorded, nothing starts.
  Review a few decisions on the Autonomy page, then set `PLANNER_DRY_RUN=false` and restart the governance worker.
* If the LLM is down or over `LLM_DAILY_TOKEN_BUDGET`, deterministic rules decide instead.
* Tunables: `config/agents.yaml` under `autonomy_planner`.

## 6. Checks

```
pytest tests/unit/ai_stack -q
```
DB-backed tests run only against a database whose name contains `test` and skip otherwise. Example:
`POSTGRES_DB=dex_ai_test POSTGRES_USER=postgres POSTGRES_PASSWORD=... pytest tests/unit/ai_stack`.
