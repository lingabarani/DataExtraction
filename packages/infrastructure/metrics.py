"""
OneExtraction — Enterprise Prometheus Metrics & Telemetry Exporter
Provides standard Prometheus metric collectors, HTTP request timing,
database connection pool gauges, and dead-letter queue backpressure indicators.
"""

import logging
import time
from typing import Callable, Optional

from fastapi import Request, Response
from fastapi.responses import PlainTextResponse

logger = logging.getLogger("oneextraction.metrics")

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        REGISTRY,
        generate_latest,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; charset=utf-8"


if PROMETHEUS_AVAILABLE:
    # ── HTTP Request Metrics ──────────────────────────────────────────────────
    HTTP_REQUESTS_TOTAL = Counter(
        "http_requests_total",
        "Total count of HTTP requests processed by endpoint and status",
        ["method", "endpoint", "status_code"],
    )

    HTTP_REQUEST_DURATION_SECONDS = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency histogram in seconds",
        ["method", "endpoint"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    # ── Database & Connection Pool Metrics ────────────────────────────────────
    DB_POOL_ACTIVE_CONNECTIONS = Gauge(
        "oneextraction_db_pool_active_connections",
        "Number of database connections currently checked out by workers",
    )

    DB_POOL_CAPACITY = Gauge(
        "oneextraction_db_pool_capacity",
        "Total maximum capacity of the PostgreSQL connection pool",
    )

    # ── Dead-Letter Queue (DLQ) Gauges ────────────────────────────────────────
    DLQ_PENDING_RECORDS = Gauge(
        "oneextraction_dlq_pending_records",
        "Total un-replayed quarantined records in Dead-Letter Queue",
    )

    DLQ_ALERT_STATUS = Gauge(
        "oneextraction_dlq_alert_status",
        "1 if DLQ backpressure exceeds the critical threshold (e.g., > 100), else 0",
    )

    # ── Ingestion Operations ──────────────────────────────────────────────────
    INGESTION_RUNS_TOTAL = Counter(
        "oneextraction_ingestion_runs_total",
        "Total source extraction runs executed",
        ["source", "status"],
    )

    INGESTION_RECORDS_PROCESSED = Counter(
        "oneextraction_ingestion_records_processed_total",
        "Total raw records normalized and ingested",
        ["source"],
    )


def record_request_metrics(method: str, path: str, status_code: int, duration_sec: float) -> None:
    """Record timing and status metrics for an executed HTTP request."""
    if not PROMETHEUS_AVAILABLE:
        return

    # Normalize parameterized paths to avoid metric cardinality explosion
    normalized_path = path
    if path.startswith("/api/leads/") and len(path.split("/")) > 3:
        normalized_path = "/api/leads/{id}"
    elif path.startswith("/api/campaigns/") and len(path.split("/")) > 3:
        normalized_path = "/api/campaigns/{id}"
    elif path.startswith("/api/dlq/replay/"):
        normalized_path = "/api/dlq/replay/{id}"
    elif path.startswith("/api/dlq/discard/"):
        normalized_path = "/api/dlq/discard/{id}"

    try:
        HTTP_REQUESTS_TOTAL.labels(
            method=method,
            endpoint=normalized_path,
            status_code=str(status_code),
        ).inc()

        HTTP_REQUEST_DURATION_SECONDS.labels(
            method=method,
            endpoint=normalized_path,
        ).observe(duration_sec)
    except Exception as e:
        logger.debug("Failed to record Prometheus metrics: %s", e)


def update_system_gauges() -> None:
    """Synchronizes dynamic database pool and DLQ states with Prometheus gauges."""
    if not PROMETHEUS_AVAILABLE:
        return

    # Update DB pool gauges
    try:
        from db_connector import _pool, _pool_max
        if _pool is not None:
            active = len(getattr(_pool, "_used", []))
            DB_POOL_ACTIVE_CONNECTIONS.set(active)
            DB_POOL_CAPACITY.set(_pool_max)
    except Exception:
        pass

    # Update DLQ gauges
    try:
        from dead_letter_queue import get_dlq_stats
        stats = get_dlq_stats()
        pending = stats.get("pending_count", 0)
        DLQ_PENDING_RECORDS.set(pending)
        DLQ_ALERT_STATUS.set(1 if pending > 100 else 0)
    except Exception:
        pass


def get_metrics_response() -> Response:
    """Generates the formatted Prometheus metrics payload."""
    if not PROMETHEUS_AVAILABLE:
        return PlainTextResponse(
            "# HELP oneextraction_info OneExtraction Prometheus exporter unavailable\n"
            "oneextraction_info{status=\"prometheus_client_not_installed\"} 1\n",
            media_type="text/plain; version=0.0.4",
        )

    # Refresh gauges right before scrape
    update_system_gauges()

    payload = generate_latest(REGISTRY)
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)
