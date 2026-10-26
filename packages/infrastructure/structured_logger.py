"""
OneExtraction — Structured JSON Logging & Pipeline Observability Engine

Enterprise-grade structured logging for data ingestion and API servers.
Features:
  - Structured JSON format in production with ISO-8601 timestamps.
  - Automatic sensitive data redaction (API keys, passwords, bearer tokens).
  - Contextual log binding (.bind(run_id=..., source=...)).
  - Context manager timing (.timed("operation_name")) for latency tracing.
  - Integration with standard Python logging.
"""

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SENSITIVE_KEYS = {
    "password", "secret", "token", "jwt", "api_key", "apikey",
    "authorization", "private_key", "sam_gov_api_key", "propublica_api_key",
}


def _mask_sensitive(data: Any) -> Any:
    """Recursively redacts sensitive keys from dictionaries and tuples."""
    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if str(k).lower() in SENSITIVE_KEYS or any(s in str(k).lower() for s in ("password", "secret", "token")):
                masked[k] = "[REDACTED]"
            elif isinstance(v, (dict, list)):
                masked[k] = _mask_sensitive(v)
            else:
                masked[k] = v
        return masked
    elif isinstance(data, list):
        return [_mask_sensitive(x) for x in data]
    return data


class JsonLogFormatter(logging.Formatter):
    """Formats log records as structured, machine-parseable JSON lines."""

    def __init__(self, service_name: str = "oneextraction"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }

        # Contextual metadata attached to LogRecord
        if hasattr(record, "run_id") and record.run_id:
            log_obj["run_id"] = record.run_id
        if hasattr(record, "source") and record.source:
            log_obj["source"] = record.source
        if hasattr(record, "duration_ms") and record.duration_ms is not None:
            log_obj["duration_ms"] = round(record.duration_ms, 2)
        if hasattr(record, "metadata") and record.metadata:
            log_obj["metadata"] = _mask_sensitive(record.metadata)

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, default=str, ensure_ascii=False)


class StandardLogFormatter(logging.Formatter):
    """Human-friendly terminal log formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        ctx = []
        if hasattr(record, "run_id") and record.run_id:
            ctx.append(f"run={record.run_id}")
        if hasattr(record, "source") and record.source:
            ctx.append(f"src={record.source}")
        if hasattr(record, "duration_ms") and record.duration_ms is not None:
            ctx.append(f"{record.duration_ms:.1f}ms")
        ctx_str = f" [{', '.join(ctx)}]" if ctx else ""

        base = f"[{ts}] [{record.levelname:<5}] [{record.name}]{ctx_str} {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class BoundLogger:
    """A contextual wrapper around standard logging.Logger providing structured context binding."""

    def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
        self._logger = logger
        self._context = context or {}

    def bind(self, **kwargs) -> "BoundLogger":
        """Returns a new BoundLogger with merged context attributes."""
        merged = {**self._context, **kwargs}
        return BoundLogger(self._logger, merged)

    def _log(self, level: int, msg: str, *args, **kwargs):
        extra = kwargs.pop("extra", {})
        merged_extra = {**self._context, **extra}
        self._logger.log(level, msg, *args, extra=merged_extra, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        kwargs["exc_info"] = True
        self._log(logging.ERROR, msg, *args, **kwargs)

    @contextmanager
    def timed(self, operation: str, **metadata):
        """Context manager measuring execution duration and logging completion metrics."""
        start = time.perf_counter()
        try:
            yield
            duration_ms = (time.perf_counter() - start) * 1000.0
            self.info(f"Finished {operation}", extra={"duration_ms": duration_ms, "metadata": metadata})
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self.error(f"Failed {operation}: {exc}", extra={"duration_ms": duration_ms, "metadata": metadata})
            raise exc


def get_structured_logger(name: str = "oneextraction", json_format: Optional[bool] = None) -> BoundLogger:
    """
    Returns a production-ready BoundLogger configured according to APP_ENV.
    Defaults to JSON formatting in production and standard formatting locally.
    """
    raw_logger = logging.getLogger(name)

    # Determine format mode
    if json_format is None:
        env = os.getenv("APP_ENV", "development").lower()
        json_format = env in ("production", "staging", "prod")

    # If no handler configured on this logger, attach one
    if not raw_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        if json_format:
            handler.setFormatter(JsonLogFormatter())
        else:
            handler.setFormatter(StandardLogFormatter())
        raw_logger.addHandler(handler)
        raw_logger.setLevel(logging.INFO)

    return BoundLogger(raw_logger)


def get_pipeline_health_metrics() -> Dict[str, Any]:
    """Retrieves operational pipeline health and connection pool telemetry."""
    metrics = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "healthy",
        "process_id": os.getpid(),
    }

    # DB pool metrics
    try:
        from db_connector import _PG_POOL
        if _PG_POOL is not None:
            metrics["database_pool"] = {
                "active": True,
                "minconn": getattr(_PG_POOL, "minconn", None),
                "maxconn": getattr(_PG_POOL, "maxconn", None),
                "closed": getattr(_PG_POOL, "closed", False),
            }
        else:
            metrics["database_pool"] = {"active": False, "status": "uninitialized"}
    except Exception as e:
        metrics["database_pool"] = {"active": False, "error": str(e)}

    return metrics
