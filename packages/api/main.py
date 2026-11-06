"""
DataExtraction — FastAPI Application Factory & Main Gateway
===========================================================
Production application entry point with:
  - Async lifespan handler (graceful DB connection pool warmup and shutdown)
  - CORS, Request timing, and Security headers middlewares
  - Dynamic route aggregation:
      * Orchestration Router (/api/orchestration)
      * Extraction Router (/api/extraction)
      * Search & KG Router (/api/search)
      * Legacy Routers (Leads, DLQ, Auth, Stats, Exports)
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.db_connector import close_connection_pool, get_db_pool_status
from packages.infrastructure.structured_logger import get_structured_logger
from packages.infrastructure.metrics import get_metrics_response, record_request_metrics
from packages.api.middleware.rate_limiter import RateLimitMiddleware
from packages.api.middleware.audit_middleware import AuditTrailMiddleware
from packages.api.routers.orchestration_router import router as orchestration_router
from packages.api.routers.extraction_router import router as extraction_router
from packages.api.routers.search_router import router as search_router
from packages.api.routers.enrichment_router import router as enrichment_router
from packages.api.routers.delivery_router import router as delivery_router
from packages.api.routers.compliance_router import router as compliance_router
from packages.api.routers.governance_router import router as governance_router

logger = get_structured_logger("api.gateway")

# Legacy router imports for 100% backward compatibility
try:
    from packages.api.routers.auth_router import router as auth_router
    from packages.api.routers.leads_router import router as leads_router
    from packages.api.routers.dlq_router import router as dlq_router, health_router as dlq_health_router
    from packages.api.routers.stats_router import router as stats_router
    from packages.api.routers.export_router import router as export_router
    from packages.api.routers.duplicates_router import router as duplicates_router
    from packages.api.routers.ai_router import router as ai_router
    from packages.api.routers.map_extraction_router import router as map_extraction_router
    _HAS_LEGACY_ROUTERS = True
except ImportError as _legacy_err:
    logger.warning("Legacy routers import error: %s", _legacy_err)
    _HAS_LEGACY_ROUTERS = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager handling startup warmup and shutdown cleanup."""
    logger.info("Initializing DataExtraction API Gateway...")
    yield
    logger.info("Shutting down DataExtraction API Gateway...")
    close_connection_pool()


def create_app() -> FastAPI:
    """FastAPI application factory."""
    application = FastAPI(
        title="DataExtraction Enterprise API Gateway",
        description="Unified Enterprise B2B Lead Intelligence, SRE Orchestration & Knowledge Graph Gateway",
        version="3.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS Middleware ───────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config_manager.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(AuditTrailMiddleware)

    # ── Request Timing & Metrics Middleware ───────────────────────────────────
    @application.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start_time = time.time()
        try:
            response = await call_next(request)
            duration_sec = time.time() - start_time
            duration_ms = duration_sec * 1000
            response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
            record_request_metrics(request.method, request.url.path, response.status_code, duration_sec)
            return response
        except Exception as exc:
            duration_sec = time.time() - start_time
            duration_ms = duration_sec * 1000
            record_request_metrics(request.method, request.url.path, 500, duration_sec)
            logger.error(
                "Unhandled API Exception: method=%s path=%s duration=%.2fms error=%s",
                request.method, request.url.path, duration_ms, exc,
            )
            origin = request.headers.get("origin") or "http://localhost:3000"
            return JSONResponse(
                status_code=500,
                content={"error": "Internal Server Error", "detail": str(exc)},
                headers={
                    "X-Process-Time-Ms": f"{duration_ms:.2f}",
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Allow-Methods": "*",
                },
            )

    # ── Core Modern Routers ───────────────────────────────────────────────────
    application.include_router(orchestration_router)
    application.include_router(extraction_router)
    application.include_router(search_router)
    application.include_router(enrichment_router)
    application.include_router(delivery_router)
    application.include_router(compliance_router)
    application.include_router(governance_router)

    # ── Legacy Routers (Backward Compatibility) ───────────────────────────────
    if _HAS_LEGACY_ROUTERS:
        legacy_routers = [
            auth_router,
            leads_router,
            dlq_router,
            dlq_health_router,
            stats_router,
            export_router,
            duplicates_router,
            ai_router,
            map_extraction_router,
        ]
        for r in legacy_routers:
            application.include_router(r, prefix="/api")
            application.include_router(r)

    # ── Health Probes & Root Endpoints ────────────────────────────────────────
    @application.get("/healthz", tags=["Health"])
    def liveness_probe() -> Dict[str, Any]:
        return {"status": "ok", "service": "dataextraction-api", "timestamp": time.time()}

    @application.get("/api/health", tags=["Health"])
    def legacy_health_probe() -> Dict[str, Any]:
        pool = get_db_pool_status()
        return {
            "status": "ok",
            "service": "OneExtraction API",
            "database": "connected" if pool.get("initialized") else "mocked/standalone",
            "timestamp": time.time(),
        }

    @application.get("/readyz", tags=["Health"])
    def readiness_probe() -> Dict[str, Any]:
        pool = get_db_pool_status()
        return {
            "status": "ready" if pool.get("initialized") else "degraded",
            "database_pool": pool,
        }

    # ── Prometheus Metrics Endpoint (Observability) ───────────────────────────
    @application.get("/metrics", tags=["Observability"], include_in_schema=True)
    @application.get("/api/metrics", tags=["Observability"], include_in_schema=True)
    def prometheus_metrics():
        """Scrape endpoint for Prometheus server to collect latency and throughput metrics."""
        return get_metrics_response()

    @application.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse(url="/api/docs")

    return application


# Canonical app instance
app = create_app()

__all__ = ["app", "create_app"]
