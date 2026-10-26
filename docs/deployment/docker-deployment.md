# Multi-Container Docker Deployment Guide

## Architecture
The platform runs via Docker Compose with dedicated containers:
1. `dataextraction-postgres`: PostgreSQL 15 + PostGIS database.
2. `dataextraction-temporal`: Temporal Server standalone instance.
3. `dataextraction-temporal-admin-tools`: Temporal CLI and cluster admin utilities.
4. `dataextraction-temporal-ui`: Temporal Web UI on port 8088.
5. `dataextraction-api`: FastAPI backend container on port 8000.
6. `dataextraction-web`: Next.js 15 standalone frontend on port 3000.
7. `dataextraction-nginx`: High-performance reverse proxy routing `/api` and `/` on port 80.

---

## Deployment Commands

### Production Build & Launch
```bash
# Build production Docker images
docker compose -f infra/docker-compose.yml build

# Start detached stack
docker compose -f infra/docker-compose.yml up -d

# Inspect health status
docker compose -f infra/docker-compose.yml ps
```

### Logs & Diagnostics
```bash
# View aggregated container logs
docker compose -f infra/docker-compose.yml logs -f

# View API logs specifically
docker compose -f infra/docker-compose.yml logs -f api
```

### Shutdown
```bash
docker compose -f infra/docker-compose.yml down
```
