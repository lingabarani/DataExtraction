# DataExtraction Enterprise Monorepo Makefile
# ============================================

.PHONY: help test test-backend test-gmaps test-osm test-agents typecheck build up down worker-federal worker-gmaps worker-osm worker-pipeline backup clean

PYTHON ?= python3

help:
	@echo "DataExtraction Enterprise Monorepo Makefile"
	@echo "Targets:"
	@echo "  test            Run all test suites"
	@echo "  test-backend    Run Phase 1-6 backend unit tests"
	@echo "  test-gmaps      Run Google Maps scraper test suite"
	@echo "  test-osm        Run Overpass OpenMap engine tests"
	@echo "  test-agents     Run autonomous agent behavior tests"
	@echo "  typecheck       Run frontend TypeScript typecheck"
	@echo "  build           Build Next.js production standalone assets"
	@echo "  up              Launch docker container stack"
	@echo "  down            Stop container stack"
	@echo "  worker-federal  Start Temporal federal scrapers worker"
	@echo "  worker-gmaps    Start Temporal Google Maps worker"
	@echo "  worker-osm      Start Temporal OSM worker"
	@echo "  worker-pipeline Start Temporal pipeline worker"
	@echo "  backup          Run PostgreSQL backup"
	@echo "  clean           Clean build and cache artifacts"

test: test-backend test-gmaps test-osm test-agents

test-backend:
	$(PYTHON) -m unittest discover -s "tests/unit/backend" -p "test_phase*.py"

test-gmaps:
	PYTHONPATH="packages/scrapers/google_maps/src:." $(PYTHON) -m pytest tests/unit/gmaps -q

test-osm:
	$(PYTHON) -m unittest discover -s "tests/unit/osm" -p "test_*.py"

test-agents:
	$(PYTHON) -m unittest tests/integration/test_agent_behaviors.py

typecheck:
	cd packages/frontend && npm run typecheck

build:
	cd packages/frontend && npm run build

up:
	docker compose -f infra/docker-compose.yml up -d

down:
	docker compose -f infra/docker-compose.yml down

worker-federal:
	$(PYTHON) packages/temporal/workers/federal_worker.py

worker-gmaps:
	$(PYTHON) packages/temporal/workers/gmaps_worker.py

worker-osm:
	$(PYTHON) packages/temporal/workers/osm_worker.py

worker-pipeline:
	$(PYTHON) packages/temporal/workers/pipeline_worker.py

backup:
	$(PYTHON) scripts/db/backup_postgres.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf packages/frontend/.next
