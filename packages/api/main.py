"""
DataExtraction — FastAPI Application Factory & Main Gateway
===========================================================
Production application entry point with:
  - Async lifespan handler (graceful DB connection pool warmup and shutdown)
  - CORS, Request timing, Security headers, and Rate-Limit middlewares
  - Structured request logging with Prometheus metrics
  - Dynamic route aggregation across all domain routers
  - Single-pass legacy router registration (no duplicates)
"""

import asyncio
import logging
import sys
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

# ---------------------------------------------------------------------------
# Legacy router imports — wrapped in a single try/except for backward compat.
# If any legacy router is missing it will not block server startup.
# ---------------------------------------------------------------------------
_legacy_routers = []

try:
    from packages.api.routers.auth_router import router as auth_router
    _legacy_routers.append((auth_router, "/api", ["auth"]))
except ImportError as _e:
    logger.warning("Legacy auth_router unavailable: %s", _e)

try:
    from packages.api.routers.leads_router import router as leads_router
    _legacy_routers.append((leads_router, "/api", ["leads"]))
except ImportError as _e:
    logger.warning("Legacy leads_router unavailable: %s", _e)

try:
    from packages.api.routers import dlq_router as _dlq_mod
    from packages.api.routers.dlq_router import router as dlq_router
    from packages.api.routers.dlq_router import health_router as dlq_health_router
    sys.modules.setdefault("api.dlq_router", _dlq_mod)
    _legacy_routers.append((dlq_router, "/api", ["dlq"]))
    _legacy_routers.append((dlq_health_router, "/api", ["health"]))
except (ImportError, AttributeError) as _e:
    logger.warning("Legacy dlq_router unavailable: %s", _e)

try:
    from packages.api.routers.stats_router import router as stats_router
    _legacy_routers.append((stats_router, "/api", ["stats"]))
except ImportError as _e:
    logger.warning("Legacy stats_router unavailable: %s", _e)

try:
    from packages.api.routers.export_router import router as export_router
    _legacy_routers.append((export_router, "/api", ["export"]))
except ImportError as _e:
    logger.warning("Legacy export_router unavailable: %s", _e)

try:
    from packages.api.routers.duplicates_router import router as duplicates_router
    _legacy_routers.append((duplicates_router, "/api", ["duplicates"]))
except ImportError as _e:
    logger.warning("Legacy duplicates_router unavailable: %s", _e)

try:
    from packages.api.routers.ai_router import router as ai_router
    _legacy_routers.append((ai_router, "/api", ["ai"]))
except ImportError as _e:
    logger.warning("Legacy ai_router unavailable: %s", _e)

try:
    from packages.api.routers.map_extraction_router import router as map_extraction_router
    _legacy_routers.append((map_extraction_router, "/api", ["map-extraction"]))
except ImportError as _e:
    logger.warning("Legacy map_extraction_router unavailable: %s", _e)


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: non-blocking DB pool warmup and graceful shutdown."""
    logger.info("DataExtraction API Gateway starting up...")

    async def _warmup_pool_async() -> None:
        try:
            from packages.infrastructure.db_connector import _init_pool
            await asyncio.to_thread(_init_pool)
            logger.info("Database connection pool initialised.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("DB pool warmup skipped (DB not reachable at startup): %s", exc)

    warmup_task = asyncio.create_task(_warmup_pool_async())
    yield
    if not warmup_task.done():
        warmup_task.cancel()
        try:
            await warmup_task
        except asyncio.CancelledError:
            pass
    logger.info("DataExtraction API Gateway shutting down...")
    close_connection_pool()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """
    FastAPI application factory.
    Registers all routers exactly once — no duplicate registrations.
    """
    app = FastAPI(
        title="DataExtraction Enterprise API Gateway",
        description=(
            "Unified B2B Lead Intelligence, SRE Orchestration "
            "& Knowledge Graph Gateway — DataExtraction Platform v3"
        ),
        version="3.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config_manager.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Rate Limiter & Audit Trail ─────────────────────────────────────────────
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuditTrailMiddleware)

    # ── Request timing, logging, and Prometheus metrics ───────────────────────
    @app.middleware("http")
    async def _request_metrics_middleware(request: Request, call_next):
        start = time.monotonic()
        try:
            response = await call_next(request)
            duration_sec = time.monotonic() - start
            response.headers["X-Process-Time-Ms"] = f"{duration_sec * 1000:.2f}"
            record_request_metrics(request.method, request.url.path, response.status_code, duration_sec)
            return response
        except Exception as exc:
            duration_sec = time.monotonic() - start
            record_request_metrics(request.method, request.url.path, 500, duration_sec)
            logger.error(
                "Unhandled exception: method=%s path=%s duration=%.2fms error=%s",
                request.method, request.url.path, duration_sec * 1000, exc,
                exc_info=True,
            )
            origin = request.headers.get("origin")
            allowed_origins = set(config_manager.get_cors_origins() or [])
            headers = {"X-Process-Time-Ms": f"{duration_sec * 1000:.2f}"}
            if origin and ("*" in allowed_origins or origin in allowed_origins):
                headers.update({
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Credentials": "true",
                    "Access-Control-Allow-Headers": "*",
                    "Access-Control-Allow-Methods": "*",
                })
            return JSONResponse(
                status_code=500,
                content={"error": "Internal Server Error", "detail": str(exc)},
                headers=headers,
            )

    # ── Core modern routers (each registered exactly once) ────────────────────
    app.include_router(orchestration_router)
    app.include_router(extraction_router)
    app.include_router(search_router)
    app.include_router(enrichment_router)
    app.include_router(delivery_router)
    app.include_router(compliance_router)
    app.include_router(governance_router)

    # ── Legacy routers (each registered exactly once with /api prefix) ─────────
    for router_obj, prefix, _tags in _legacy_routers:
        app.include_router(router_obj, prefix=prefix)

    # ── Health probes ─────────────────────────────────────────────────────────
    @app.get("/healthz", tags=["Health"], include_in_schema=False)
    def liveness() -> Dict[str, Any]:
        return {"status": "ok", "service": "dataextraction-api", "timestamp": time.time()}

    @app.get("/health", tags=["Health"], include_in_schema=False)
    def health_alias() -> Dict[str, Any]:
        return liveness()

    @app.get("/api/health", tags=["Health"])
    def legacy_health() -> Dict[str, Any]:
        pool = get_db_pool_status()
        return {
            "status": "ok",
            "service": "DataExtraction API",
            "database": "connected" if pool.get("initialized") else "unavailable",
            "timestamp": time.time(),
        }

    @app.get("/readyz", tags=["Health"], include_in_schema=False)
    def readiness() -> Dict[str, Any]:
        pool = get_db_pool_status()
        return {
            "status": "ready" if pool.get("initialized") else "degraded",
            "database_pool": pool,
        }

    # ── Prometheus metrics ────────────────────────────────────────────────────
    @app.get("/metrics", tags=["Observability"], include_in_schema=True)
    @app.get("/api/metrics", tags=["Observability"], include_in_schema=False)
    def prometheus_metrics():
        return get_metrics_response()

    # ── Root redirect ─────────────────────────────────────────────────────────
    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse(url="/api/docs")

    return app


# Canonical ASGI application instance
app = create_app()

__all__ = ["app", "create_app"]
