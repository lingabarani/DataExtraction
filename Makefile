# DataExtraction Enterprise Monorepo Makefile
# ============================================
# Cross-platform targets. On Windows use PowerShell or WSL.
# On Windows without Make installed: use bootstrap.ps1 or start.ps1 instead.

.PHONY: help install test test-backend test-gmaps test-osm test-agents \
        typecheck lint lint-fix build up up-cpu down logs \
        worker-federal worker-gmaps worker-osm worker-pipeline \
        db-bootstrap db-migrate backup clean

# Detect OS and set platform-specific Python/npm commands
ifeq ($(OS),Windows_NT)
    PYTHON   ?= python
    NPM      ?= npm
    VENV_PY  ?= .venv\Scripts\python.exe
    SEP      := &&
else
    PYTHON   ?= python3
    NPM      ?= npm
    VENV_PY  ?= .venv/bin/python
    SEP      := &&
endif

# Prefer the venv python if it exists
ifneq ($(wildcard $(VENV_PY)),)
    PY := $(VENV_PY)
else
    PY := $(PYTHON)
endif

help:
	@echo ""
	@echo "DataExtraction Enterprise — Makefile Targets"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  install       Install Python and Node dependencies"
	@echo "  test          Run all test suites"
	@echo "  test-backend  Run backend unit tests"
	@echo "  test-gmaps    Run Google Maps scraper tests"
	@echo "  test-osm      Run OpenStreetMap engine tests"
	@echo "  test-agents   Run agent integration tests"
	@echo "  lint          Lint Python with ruff"
	@echo "  lint-fix      Auto-fix ruff violations"
	@echo "  typecheck     TypeScript typecheck (frontend)"
	@echo "  build         Build Next.js production assets"
	@echo "  up            Start full Docker stack (CPU Ollama)"
	@echo "  up-gpu        Start Docker stack with GPU Ollama"
	@echo "  down          Stop Docker stack"
	@echo "  logs          Tail all container logs"
	@echo "  db-bootstrap  Run canonical DB bootstrap SQL"
	@echo "  db-migrate    Run Python migration runner"
	@echo "  backup        Run PostgreSQL backup"
	@echo "  clean         Remove build/cache artifacts"
	@echo ""

# ── Installation ──────────────────────────────────────────────────────────────
install:
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	cd frontend $(SEP) $(NPM) ci

# ── Tests ─────────────────────────────────────────────────────────────────────
test: test-backend test-gmaps test-osm test-agents

test-backend:
	PYTHONPATH=. $(PY) -m pytest tests/unit/backend/ -v --tb=short \
	  --cov=packages --cov-report=term-missing

test-gmaps:
	PYTHONPATH="packages/scrapers/google_maps/src:." \
	  $(PY) -m pytest tests/unit/gmaps/ -v --tb=short

test-osm:
	PYTHONPATH=. $(PY) -m pytest tests/unit/osm/ -v --tb=short

test-agents:
	PYTHONPATH=. $(PY) -m pytest tests/integration/ -v --tb=short \
	  -m "not requires_temporal"

# ── Code Quality ──────────────────────────────────────────────────────────────
lint:
	$(PY) -m ruff check packages/ tests/

lint-fix:
	$(PY) -m ruff check packages/ tests/ --fix

typecheck:
	cd frontend $(SEP) $(NPM) run typecheck

# ── Frontend Build ────────────────────────────────────────────────────────────
build:
	cd frontend $(SEP) $(NPM) run build

# ── Docker ────────────────────────────────────────────────────────────────────
up:
	docker compose -f infra/docker-compose.yml --profile cpu up -d

up-gpu:
	docker compose -f infra/docker-compose.yml --profile gpu up -d

down:
	docker compose -f infra/docker-compose.yml down

logs:
	docker compose -f infra/docker-compose.yml logs -f --tail=100

# ── Database ──────────────────────────────────────────────────────────────────
db-bootstrap:
	@echo "Running canonical DB bootstrap..."
	PYTHONPATH=. $(PY) -c "\
	  import os, psycopg2; \
	  conn = psycopg2.connect(host=os.getenv('POSTGRES_HOST','localhost'), \
	    port=int(os.getenv('POSTGRES_PORT','5432')), \
	    dbname=os.getenv('POSTGRES_DB','dataextraction'), \
	    user=os.getenv('POSTGRES_USER','dex_user'), \
	    password=os.getenv('POSTGRES_PASSWORD','')); \
	  conn.autocommit=True; \
	  cur=conn.cursor(); \
	  cur.execute(open('packages/infrastructure/bootstrap_db.sql').read()); \
	  cur.close(); conn.close(); print('Bootstrap complete.')"

db-migrate:
	PYTHONPATH=. $(PY) -m packages.infrastructure.migration_manager

# ── Workers (local, non-Docker) ───────────────────────────────────────────────
worker-federal:
	PYTHONPATH=. $(PY) -m packages.temporal.workers.federal_worker

worker-gmaps:
	PYTHONPATH=. $(PY) -m packages.temporal.workers.gmaps_worker

worker-osm:
	PYTHONPATH=. $(PY) -m packages.temporal.workers.osm_worker

worker-pipeline:
	PYTHONPATH=. $(PY) -m packages.temporal.workers.pipeline_worker

# ── Maintenance ───────────────────────────────────────────────────────────────
backup:
	PYTHONPATH=. $(PY) scripts/db/backup_postgres.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/.next 2>/dev/null || true
