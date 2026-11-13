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

logger = logging.getLogger("dataextraction.metrics")

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Gauge,
        Histogram,
        REGISTRY,
        generate_latest,
        start_http_server,
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; charset=utf-8"
    start_http_server = None  # type: ignore


class _NoOpMetric:
    """Enterprise fallback no-op metric collector when prometheus_client is not installed."""
    def inc(self, *args, **kwargs): pass
    def dec(self, *args, **kwargs): pass
    def set(self, *args, **kwargs): pass
    def observe(self, *args, **kwargs): pass
    def labels(self, *args, **kwargs): return self

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
    DATAEXTRACTION_DB_POOL_ACTIVE_CONNECTIONS = Gauge(
        "dataextraction_db_pool_active_connections",
        "Number of database connections currently checked out by workers",
    )

    DB_POOL_CAPACITY = Gauge(
        "oneextraction_db_pool_capacity",
        "Total maximum capacity of the PostgreSQL connection pool",
    )
    DATAEXTRACTION_DB_POOL_CAPACITY = Gauge(
        "dataextraction_db_pool_capacity",
        "Total maximum capacity of the PostgreSQL connection pool",
    )

    # ── Dead-Letter Queue (DLQ) Gauges ────────────────────────────────────────
    DLQ_PENDING_RECORDS = Gauge(
        "oneextraction_dlq_pending_records",
        "Total un-replayed quarantined records in Dead-Letter Queue",
    )
    DATAEXTRACTION_DLQ_PENDING_RECORDS = Gauge(
        "dataextraction_dlq_pending_records",
        "Total un-replayed quarantined records in Dead-Letter Queue",
    )

    DLQ_ALERT_STATUS = Gauge(
        "oneextraction_dlq_alert_status",
        "1 if DLQ backpressure exceeds the critical threshold (e.g., > 100), else 0",
    )
    DATAEXTRACTION_DLQ_ALERT_STATUS = Gauge(
        "dataextraction_dlq_alert_status",
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

    # ── Agent 2: Geospatial & Domain Intelligence Telemetry ──────────────────
    AGENT2_GMAPS_PLACES_PERSISTED = Counter(
        "agent2_gmaps_places_persisted_total",
        "Total Google Maps places persisted to PostgreSQL by Agent 2",
        ["region", "status"],
    )
    AGENT2_OSM_POIS_PERSISTED = Counter(
        "agent2_osm_pois_persisted_total",
        "Total OpenStreetMap POIs persisted to PostgreSQL by Agent 2",
        ["region", "status"],
    )
    AGENT2_WEBSITE_VERIFICATIONS_TOTAL = Counter(
        "agent2_website_verifications_total",
        "Total company websites verified by Agent 2",
        ["status"],
    )
    AGENT2_WEBSITE_CRAWLS_TOTAL = Counter(
        "agent2_website_crawls_total",
        "Total company websites crawled for executive/contact extraction",
        ["status"],
    )
    AGENT2_KG_OBSERVATIONS_TOTAL = Counter(
        "agent2_kg_observations_total",
        "Total KG observations persisted directly to Lakehouse or PG outbox",
        ["destination", "status"],
    )
    AGENT2_LAKEHOUSE_OUTBOX_BACKLOG = Gauge(
        "agent2_lakehouse_outbox_backlog",
        "Pending records waiting in kg_observation.pending_lakehouse_uploads outbox",
    )
    AGENT2_ACTIVITY_DURATION_SECONDS = Histogram(
        "agent2_activity_duration_seconds",
        "Execution latency of Agent 2 Temporal activities in seconds",
        ["activity_name"],
        buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0, 300.0, 1800.0),
    )
else:
    HTTP_REQUESTS_TOTAL = _NoOpMetric()
    HTTP_REQUEST_DURATION_SECONDS = _NoOpMetric()
    DB_POOL_ACTIVE_CONNECTIONS = _NoOpMetric()
    DATAEXTRACTION_DB_POOL_ACTIVE_CONNECTIONS = _NoOpMetric()
    DB_POOL_CAPACITY = _NoOpMetric()
    DATAEXTRACTION_DB_POOL_CAPACITY = _NoOpMetric()
    DLQ_PENDING_RECORDS = _NoOpMetric()
    DATAEXTRACTION_DLQ_PENDING_RECORDS = _NoOpMetric()
    DLQ_ALERT_STATUS = _NoOpMetric()
    DATAEXTRACTION_DLQ_ALERT_STATUS = _NoOpMetric()
    INGESTION_RUNS_TOTAL = _NoOpMetric()
    INGESTION_RECORDS_PROCESSED = _NoOpMetric()
    AGENT2_GMAPS_PLACES_PERSISTED = _NoOpMetric()
    AGENT2_OSM_POIS_PERSISTED = _NoOpMetric()
    AGENT2_WEBSITE_VERIFICATIONS_TOTAL = _NoOpMetric()
    AGENT2_WEBSITE_CRAWLS_TOTAL = _NoOpMetric()
    AGENT2_KG_OBSERVATIONS_TOTAL = _NoOpMetric()
    AGENT2_LAKEHOUSE_OUTBOX_BACKLOG = _NoOpMetric()
    AGENT2_ACTIVITY_DURATION_SECONDS = _NoOpMetric()



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
        from packages.infrastructure.db_connector import _PG_POOL, DB_POOL_MAX
        if _PG_POOL is not None:
            active = len(getattr(_PG_POOL, "_used", []))
            DB_POOL_ACTIVE_CONNECTIONS.set(active)
            DATAEXTRACTION_DB_POOL_ACTIVE_CONNECTIONS.set(active)
            DB_POOL_CAPACITY.set(DB_POOL_MAX)
            DATAEXTRACTION_DB_POOL_CAPACITY.set(DB_POOL_MAX)
    except Exception:
        pass

    # Update DLQ gauges
    try:
        from packages.infrastructure.dead_letter_queue import get_dlq_stats
        stats = get_dlq_stats()
        pending = stats.get("pending_count", 0)
        DLQ_PENDING_RECORDS.set(pending)
        DATAEXTRACTION_DLQ_PENDING_RECORDS.set(pending)
        alert_val = 1 if pending > 100 else 0
        DLQ_ALERT_STATUS.set(alert_val)
        DATAEXTRACTION_DLQ_ALERT_STATUS.set(alert_val)
    except Exception:
        pass

    # Update Agent 2 Lakehouse Outbox backlog gauge
    try:
        from packages.infrastructure.db_connector import get_connection, release_connection
        conn = get_connection()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM kg_observation.pending_lakehouse_uploads WHERE uploaded_at IS NULL;"
                    )
                    outbox_cnt = int((cur.fetchone() or [0])[0] or 0)
                    AGENT2_LAKEHOUSE_OUTBOX_BACKLOG.set(outbox_cnt)
            finally:
                release_connection(conn)
    except Exception:
        pass


def start_worker_metrics_server(port: int) -> bool:
    """Starts the Prometheus standalone HTTP metrics server for Temporal workers."""
    if not PROMETHEUS_AVAILABLE or start_http_server is None:
        return False
    try:
        start_http_server(int(port))
        logger.info("Prometheus worker metrics server listening on :%d", int(port))
        return True
    except OSError as exc:
        logger.warning("Prometheus worker metrics server port %d unavailable (%s); continuing.", port, exc)
        return False


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
