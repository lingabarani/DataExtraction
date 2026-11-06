"""
DataExtraction — Platform SRE Supervisor Metrics Tool
====================================================
Provides Prometheus / OTEL telemetry bridge for supervisors to observe
connection pool saturation, throughput rates, and system pressure.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger("dataextraction.supervisor.tools.metrics")


async def get_current_metrics(metric_names: List[str]) -> Dict[str, Any]:
    """
    Returns current values for requested metrics.
    Supported metric names:
      - 'db_pool_utilization'
      - 'db_pool_active'
      - 'db_pool_capacity'
      - 'api_request_rate'
      - 'dlq_pending'
    """
    results: Dict[str, Any] = {}

    for name in metric_names:
        if name in ("db_pool_utilization", "db_pool_active", "db_pool_capacity"):
            try:
                from packages.infrastructure.db_connector import _PG_POOL, DB_POOL_MAX
                if _PG_POOL is not None:
                    # In psycopg2 ThreadedConnectionPool:
                    # len(_PG_POOL._used) is active connections
                    active = len(getattr(_PG_POOL, "_used", []))
                    capacity = DB_POOL_MAX or 20
                    utilization = active / capacity if capacity > 0 else 0.0

                    if name == "db_pool_utilization":
                        results[name] = round(utilization, 3)
                    elif name == "db_pool_active":
                        results[name] = active
                    elif name == "db_pool_capacity":
                        results[name] = capacity
                else:
                    results[name] = 0.0 if name == "db_pool_utilization" else 0
            except Exception as exc:
                logger.debug("Failed to read DB pool metrics: %s", exc)
                results[name] = 0.0 if name == "db_pool_utilization" else 0

        elif name == "api_request_rate":
            try:
                from packages.infrastructure.metrics import metrics
                results[name] = getattr(metrics, "current_request_rate", 0.0)
            except Exception:
                results[name] = 0.0

        elif name == "dlq_pending":
            try:
                from packages.infrastructure.dead_letter_queue import dead_letter_queue
                results[name] = dead_letter_queue.get_pending_count()
            except Exception:
                results[name] = 0

        else:
            results[name] = None

    return results


__all__ = [
    "get_current_metrics",
]

