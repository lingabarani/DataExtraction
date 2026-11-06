"""
DataExtraction — Agent Read-Only Database Tool (Consolidated Re-export)

Maintained for backward compatibility. Canonical implementation is located in
`packages.supervisor.tools.db_tool`.
"""

from packages.supervisor.tools.db_tool import *  # noqa: F401, F403
from packages.supervisor.tools.db_tool import (
    get_dlq_stats,
    get_table_counts,
    get_source_freshness,
)

__all__ = [
    "get_dlq_stats",
    "get_table_counts",
    "get_source_freshness",
]
