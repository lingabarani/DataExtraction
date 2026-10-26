"""
OneExtraction Open Map Extraction Engine Package.

Provides high-performance, fault-tolerant spatial data extraction, circuit-breaker managed Overpass API querying,
adaptive quadtree subdivision, ACID checkpoint state tracking, and canonical deduplicated ingestion.
"""

from .config import OverpassConfig, default_config
from .circuit_breaker import EndpointCircuitBreaker, EndpointHealth
from .quadtree import AdaptiveQuadtree, split_bounding_box
from .checkpoint import EnterpriseCheckpointManager
from .taxonomy import (
    US_STATES,
    STATE_CODES,
    CODE_TO_STATE,
    STATE_BOUNDING_BOXES,
    FIELDS_TAXONOMY,
    FIELD_BY_NAME,
    slugify,
    get_state_bbox,
    get_field_info,
)
from .connector import OpenMapConnector

__all__ = [
    "OverpassConfig",
    "default_config",
    "EndpointCircuitBreaker",
    "EndpointHealth",
    "AdaptiveQuadtree",
    "split_bounding_box",
    "EnterpriseCheckpointManager",
    "OpenMapConnector",
    "US_STATES",
    "STATE_CODES",
    "CODE_TO_STATE",
    "STATE_BOUNDING_BOXES",
    "FIELDS_TAXONOMY",
    "FIELD_BY_NAME",
    "slugify",
    "get_state_bbox",
    "get_field_info",
]
