"""
OneExtraction — Enterprise FastAPI Backend Application
Serves all lead intelligence, extraction, and analytics endpoints on port 3001.

Features:
  - Threaded database connection pooling
  - Stateless JWT authentication guards
  - Chunked streaming export with server-side cursors
  - Managed background subprocess execution for scrapers
  - Structured request logging and timing middleware
"""

import logging
import sys
import time
from pathlib import Path

# Bootstrap DataExtraction monorepo package paths
_BASE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _BASE_DIR.parents[1]
_PACKAGES = _REPO_ROOT / 'packages'

for _p in [
    _BASE_DIR,
    _BASE_DIR / 'routers',
    _PACKAGES / 'pipeline',
    _PACKAGES / 'infrastructure',
    _PACKAGES / 'scrapers',
    _PACKAGES / 'scrapers' / 'federal',
    _PACKAGES / 'scrapers' / 'open_map',
    _PACKAGES / 'scrapers' / 'openmap_engine',
    _PACKAGES / 'temporal',
    _PACKAGES / 'agents',
    _REPO_ROOT / 'scripts' / 'db',
    _REPO_ROOT / 'scripts' / 'ops',
    _REPO_ROOT,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from api.ai_router import router as ai_router
from api.auth_router import router as auth_router
from api.duplicates_router import router as dup_router
from api.export_router import router as export_router
from api.leads_router import router as leads_router
from api.scraper_router import router as scraper_router
from api.stats_router import router as stats_router
from api.map_extraction_router import router as map_extraction_router
from api.dlq_router import router as dlq_router, health_router as pipeline_health_router
from api.pipeline_router import router as pipeline_router
from config_manager import config_manager
from metrics import get_metrics_response, record_request_metrics

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("oneextraction.server")

# ── FastAPI Application Instance ──────────────────────────────────────────────

app = FastAPI(
    title="OneExtraction API",
    description="Enterprise US & Mexico B2B Lead Intelligence API",
    version="2.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── CORS Middleware ───────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=config_manager.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request Timing, Security Headers & Metrics Middleware ──────────────────────

@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start_time = time.time()
    path = request.url.path
    method = request.method

    try:
        response = await call_next(request)
        duration_sec = time.time() - start_time
        duration_ms = duration_sec * 1000

        # Security Headers
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # Record telemetry & Prometheus metrics
        record_request_metrics(method, path, response.status_code, duration_sec)
        logger.info("%s %s -> %d (%.1f ms)", method, path, response.status_code, duration_ms)
        return response
    except Exception as exc:
        duration_sec = time.time() - start_time
        duration_ms = duration_sec * 1000
        record_request_metrics(method, path, 500, duration_sec)
        logger.exception("Unhandled error on %s %s (%.1f ms): %s", method, path, duration_ms, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "path": path},
            headers={
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
            },
        )


# ── Mount Routers under /api ──────────────────────────────────────────────────

app.include_router(auth_router, prefix="/api")
app.include_router(leads_router, prefix="/api")
app.include_router(stats_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(dup_router, prefix="/api")
app.include_router(scraper_router, prefix="/api")
app.include_router(ai_router, prefix="/api")
app.include_router(map_extraction_router, prefix="/api")
app.include_router(dlq_router, prefix="/api")
app.include_router(pipeline_health_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")


# ── Prometheus Telemetry & Health Endpoints ───────────────────────────────────

@app.get("/metrics", include_in_schema=False)
@app.get("/api/metrics", tags=["Observability"])
def metrics():
    """Exposes application performance and system gauges in Prometheus scrape format."""
    return get_metrics_response()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/api/docs")


@app.get("/docs", include_in_schema=False)
def docs_redirect():
    return RedirectResponse(url="/api/docs")


# ── Public Health Check ───────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    from db_connector import db_info
    return {
        "status": "ok",
        "service": "OneExtraction API",
        "version": "2.1.0",
        "database": db_info(),
    }


# ── Local Development Entry Point ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api_server:app",
        host="0.0.0.0",
        port=3001,
        reload=True,
        reload_dirs=[str(_BASE_DIR)],
    )
