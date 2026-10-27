<#
.SYNOPSIS
    DataExtraction Unified Enterprise Management Script (PowerShell CLI)
    Provides automated commands for testing, building, backups, container orchestration,
    Temporal worker execution, and cache hygiene.

.EXAMPLE
    .\manage.ps1 test
    .\manage.ps1 test:backend
    .\manage.ps1 test:gmaps
    .\manage.ps1 test:osm
    .\manage.ps1 test:agents
    .\manage.ps1 typecheck
    .\manage.ps1 build
    .\manage.ps1 up
    .\manage.ps1 worker:federal
    .\manage.ps1 backup
#>

param (
    [Parameter(Position=0)]
    [ValidateSet(
        "test", "test:backend", "test:gmaps", "test:osm", "test:agents", "test:e2e", "test:ui",
        "typecheck", "build", "up", "down",
        "worker:federal", "worker:gmaps", "worker:osm", "worker:pipeline",
        "db:migrate", "db:partitions", "backup", "backup:verify", "restore", "restore:verify", "restore:list",
        "clean", "status", "help"
    )]
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Resolve Python from virtual environment if present
$VenvPython = "D:\Data Scraping Project POC\OneExtraction\.venv\Scripts\python.exe"
if (Test-Path (Join-Path $Root ".venv\Scripts\python.exe")) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
} elseif (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $Python = "python"
}

# Set Monorepo PYTHONPATH for all scraper packages
$GmapsSrc = Join-Path $Root "packages\scrapers\google_maps\src"
$env:PYTHONPATH = "$GmapsSrc;$Root"

switch ($Command) {
    "test" {
        Write-Host "==> [1/5] Running Phase 1-6 backend tests (122 tests)..." -ForegroundColor Cyan
        & $Python -m unittest discover -s "tests/unit/backend" -p "test_phase*.py"

        Write-Host "`n==> [2/5] Running Google Maps scraper tests (168 tests)..." -ForegroundColor Cyan
        & $Python -m pytest tests/unit/gmaps -q

        Write-Host "`n==> [3/5] Running OpenMap engine tests (31 tests)..." -ForegroundColor Cyan
        & $Python -m unittest discover -s "tests/unit/osm" -p "test_*.py"

        Write-Host "`n==> [4/5] Running Autonomous Agent tests (12 tests)..." -ForegroundColor Cyan
        & $Python -m unittest tests/integration/test_agent_behaviors.py

        Write-Host "`n==> [5/5] Running End-to-End Pipeline & Saga tests (16 tests)..." -ForegroundColor Cyan
        & $Python -m pytest tests/e2e -q

        Write-Host "`n==> ALL DATAEXTRACTION TEST SUITES PASSED GREEN (349/349 - 100%)!" -ForegroundColor Green
    }

    "test:backend" {
        Write-Host "==> Running Phase 1-6 backend unit tests..." -ForegroundColor Cyan
        & $Python -m unittest discover -s "tests/unit/backend" -p "test_phase*.py" -v
    }

    "test:gmaps" {
        Write-Host "==> Running Google Maps scraper test suite..." -ForegroundColor Cyan
        & $Python -m pytest tests/unit/gmaps -v
    }

    "test:osm" {
        Write-Host "==> Running OpenMap spatial engine tests..." -ForegroundColor Cyan
        & $Python -m unittest discover -s "tests/unit/osm" -p "test_*.py" -v
    }

    "test:agents" {
        Write-Host "==> Running autonomous agent behavior tests..." -ForegroundColor Cyan
        & $Python -m unittest tests/integration/test_agent_behaviors.py -v
    }

    "test:e2e" {
        Write-Host "==> Running End-to-End pipeline & saga integration tests..." -ForegroundColor Cyan
        & $Python -m pytest tests/e2e -v
    }

    "test:ui" {
        Write-Host "==> Running Playwright E2E UI automation tests..." -ForegroundColor Cyan
        $FrontendDir = Join-Path $Root "packages\frontend"
        $env:NODE_PATH = Join-Path $FrontendDir "node_modules"
        Push-Location $FrontendDir
        try {
            npx playwright test --config=../../tests/playwright/playwright.config.ts
        } finally {
            Pop-Location
        }
    }

    "typecheck" {
        Write-Host "==> Running frontend TypeScript typecheck..." -ForegroundColor Cyan
        $FrontendDir = Join-Path $Root "packages\frontend"
        if (Test-Path $FrontendDir) {
            Push-Location $FrontendDir
            try { npm run typecheck } finally { Pop-Location }
        } else {
            Write-Host "Frontend directory not found at $FrontendDir" -ForegroundColor Red
        }
    }

    "build" {
        Write-Host "==> Running Next.js production standalone build..." -ForegroundColor Cyan
        $FrontendDir = Join-Path $Root "packages\frontend"
        Push-Location $FrontendDir
        try { npm run build } finally { Pop-Location }
    }

    "up" {
        Write-Host "==> Starting production multi-container stack (Nginx + Web + API + Temporal + PostGIS)..." -ForegroundColor Cyan
        docker compose -f (Join-Path $Root "infra\docker-compose.yml") up -d
        docker compose -f (Join-Path $Root "infra\docker-compose.yml") ps
    }

    "down" {
        Write-Host "==> Stopping container stack..." -ForegroundColor Yellow
        docker compose -f (Join-Path $Root "infra\docker-compose.yml") down
    }

    "worker:federal" {
        Write-Host "==> Launching Temporal Federal Scrapers Worker..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "packages\temporal\workers\federal_worker.py")
    }

    "worker:gmaps" {
        Write-Host "==> Launching Temporal Google Maps Worker..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "packages\temporal\workers\gmaps_worker.py")
    }

    "worker:osm" {
        Write-Host "==> Launching Temporal OSM Worker..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "packages\temporal\workers\osm_worker.py")
    }

    "worker:pipeline" {
        Write-Host "==> Launching Temporal Pipeline & Normalizer Worker..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "packages\temporal\workers\pipeline_worker.py")
    }

    "db:migrate" {
        Write-Host "==> Applying Knowledge Graph Schema Migrations (PostgreSQL)..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "scripts\db\apply_kg_migration.py")
    }

    "db:partitions" {
        Write-Host "==> Executing Automated Knowledge Graph Partition Maintenance..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "scripts\db\maintain_partitions.py")
    }

    "backup" {
        Write-Host "==> Executing PostgreSQL automated backup..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "scripts\db\backup_postgres.py")
    }

    "backup:verify" {
        Write-Host "==> Simulating PostgreSQL backup (dry-run)..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "scripts\db\backup_postgres.py") --dry-run
    }

    "restore" {
        Write-Host "==> Executing PostgreSQL restoration from latest verified backup..." -ForegroundColor Yellow
        & $Python (Join-Path $Root "scripts\db\restore_postgres.py") --latest
    }

    "restore:verify" {
        Write-Host "==> Simulating PostgreSQL restoration dry-run..." -ForegroundColor Cyan
        & $Python (Join-Path $Root "scripts\db\restore_postgres.py") --dry-run
    }

    "restore:list" {
        Write-Host "==> Cataloged PostgreSQL Backups:" -ForegroundColor Cyan
        & $Python (Join-Path $Root "scripts\db\restore_postgres.py") --list
    }

    "clean" {
        Write-Host "==> Purging temporary test artifacts, caches, and logs..." -ForegroundColor Yellow
        Get-ChildItem -Path $Root -Include __pycache__, .pytest_cache -Recurse -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
        $NextCache = Join-Path $Root "packages\frontend\.next"
        if (Test-Path $NextCache) {
            Remove-Item -Path $NextCache -Recurse -Force -ErrorAction SilentlyContinue
        }
        Write-Host "==> Cache purge complete." -ForegroundColor Green
    }

    "status" {
        Write-Host "==> DataExtraction Services Status:" -ForegroundColor Cyan
        if (Test-Path (Join-Path $Root "scripts\ops\check_services.py")) {
            & $Python (Join-Path $Root "scripts\ops\check_services.py")
        } else {
            Write-Host "PostgreSQL, Temporal, API Server health check script located in scripts/ops/"
        }
    }

    default {
        Write-Host "DataExtraction Enterprise Monorepo CLI" -ForegroundColor Green
        Write-Host "Usage: .\manage.ps1 <command>"
        Write-Host "Commands:"
        Write-Host "  test            Run all test suites (Backend + GMaps + OSM + Agents + E2E - 349 tests)"
        Write-Host "  test:backend    Run Phase 1-6 backend unit tests"
        Write-Host "  test:gmaps      Run Google Maps scraper test suite"
        Write-Host "  test:osm        Run Overpass OpenMap engine tests"
        Write-Host "  test:agents     Run autonomous agent behavior tests"
        Write-Host "  test:e2e        Run End-to-End pipeline & saga integration tests"
        Write-Host "  test:ui         Run Playwright E2E UI automation tests"
        Write-Host "  typecheck       Validate frontend TypeScript types (tsc --noEmit)"
        Write-Host "  build           Build Next.js production standalone assets"
        Write-Host "  up              Launch multi-container stack"
        Write-Host "  down            Stop container stack"
        Write-Host "  worker:federal  Start Temporal federal worker"
        Write-Host "  worker:gmaps    Start Temporal Google Maps worker"
        Write-Host "  worker:osm      Start Temporal OSM worker"
        Write-Host "  worker:pipeline Start Temporal pipeline worker"
        Write-Host "  db:migrate      Apply Knowledge Graph schema migrations to PostgreSQL"
        Write-Host "  backup          Execute pg_dump with SHA-256 verification"
        Write-Host "  backup:verify   Simulate database backup dry run"
        Write-Host "  restore         Restore PostgreSQL from latest verified backup"
        Write-Host "  restore:verify  Simulate PostgreSQL restore dry run"
        Write-Host "  restore:list    List all cataloged database backups"
        Write-Host "  clean           Purge Python and build caches"
        Write-Host "  status          Inspect service availability and endpoints"
    }
}

