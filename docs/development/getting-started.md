# Getting Started with DataExtraction Monorepo

## Overview
DataExtraction is an enterprise B2B data extraction platform integrating:
- **6 Federal Data Ingestion Scrapers** (CMS NPI, SEC EDGAR, FDIC, USAspending, ProPublica, SAM.gov)
- **High-Density Google Maps Local Scraper** (Multi-threaded geo-tiling, RPC parsing, website enrichment)
- **OpenMap Spatial Engine** (Adaptive quadtree bisection, Overpass circuit breaker, ACID checkpoints)
- **Temporal Orchestration Engine** (5 isolated task queues, saga compensation, state queries & signals)
- **Autonomous AI Supervisor Agents** (Quality, Resource, Freshness, and Pipeline Coordination)
- **FastAPI Backend + Next.js 15 Enterprise UI**

---

## Prerequisites
- **Python 3.12+**
- **Node.js 20+** & **npm**
- **Docker & Docker Compose** (for PostgreSQL, PostGIS, Temporal Server)
- **Git**

---

## Quickstart

### 1. Environment Configuration
Copy `.env.example` to `.env` and fill in credentials:
```bash
cp .env.example .env
```

### 2. Install Dependencies
```powershell
pip install -r requirements.txt
cd packages/frontend && npm install && cd ../..
```

### 3. Launch Core Infrastructure Stack
```powershell
.\manage.ps1 up
```
This boots:
- PostgreSQL 15 + PostGIS (Port `5432`)
- Temporal Server & UI (Port `7233`, Web UI at `8088`)
- Prometheus Metrics (Port `9090`)

### 4. Run Test Suites
```powershell
.\manage.ps1 test
```
Runs all 333 tests across backend, GMaps scraper, OpenMap spatial engine, and autonomous agents.

### 5. Start Temporal Workers
In separate terminals or as background services:
```powershell
.\manage.ps1 worker:federal
.\manage.ps1 worker:gmaps
.\manage.ps1 worker:osm
.\manage.ps1 worker:pipeline
```

### 6. Launch Backend API & Frontend UI
```powershell
# Backend API
python -m uvicorn packages.api.api_server:app --host 0.0.0.0 --port 8000 --reload

# Frontend Web Dashboard
cd packages/frontend && npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to view the unified operations console.

