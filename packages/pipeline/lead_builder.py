"""
OneExtraction - Pipeline Lead Builder (Consolidated Re-export)

NOTE: This module is maintained for backward compatibility.
The canonical implementation is located at `packages.domain.lead_builder`.
"""

from packages.domain.lead_builder import *  # noqa: F401, F403
from packages.domain.lead_builder import (
    build_us_lead,
    build_mexico_lead,
    _clean,
    _clean_domain,
    _to_int,
    _to_float,
    _as_dict,
)

__all__ = [
    "build_us_lead",
    "build_mexico_lead",
]
