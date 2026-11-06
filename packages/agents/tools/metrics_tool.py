"""
DataExtraction — Agent Metrics Tool (Consolidated Re-export)

Maintained for backward compatibility. Canonical implementation is located in
`packages.supervisor.tools.metrics_tool`.
"""

from packages.supervisor.tools.metrics_tool import *  # noqa: F401, F403
from packages.supervisor.tools.metrics_tool import get_current_metrics

__all__ = [
    "get_current_metrics",
]
