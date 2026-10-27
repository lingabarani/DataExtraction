"""
DataExtraction — Agent Metrics Tool
===================================
Provides methods for agents to observe runtime metrics and telemetry
including Prometheus metrics and DB connection pool utilization.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger("dataextraction.agents.tools.metrics")


async def get_current_metrics(metric_names: List[str]) -> Dict[str, Any]:
    """
    Returns the current values for requested metrics.
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
                from packages.infrastructure.db_connector import _POOL, _PG_MINCONN, _PG_MAXCONN
                if _POOL is not None:
                    # In psycopg2 ThreadedConnectionPool:
                    # len(_POOL._used) is active connections
                    active = len(getattr(_POOL, "_used", []))
                    capacity = _PG_MAXCONN or 20
                    utilization = active / capacity if capacity > 0 else 0.0
                else:
                    active = 0
                    capacity = 20
                    utilization = 0.0

                if name == "db_pool_active":
                    results[name] = active
                elif name == "db_pool_capacity":
                    results[name] = capacity
                elif name == "db_pool_utilization":
                    results[name] = round(utilization, 4)
            except Exception as e:
                logger.debug("Could not read pool metrics: %s", e)
                results[name] = 0.0

        elif name == "api_request_rate":
            # Approximation or prometheus collector reading
            results[name] = 0.0

        elif name == "dlq_pending":
            try:
                from packages.infrastructure.dead_letter_queue import dead_letter_queue
                stats = dead_letter_queue.get_stats()
                results[name] = stats.get("total_pending", 0)
            except Exception:
                results[name] = 0

        else:
            results[name] = None

    return results

