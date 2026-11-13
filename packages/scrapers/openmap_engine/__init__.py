"""
DataExtraction - OpenMap Engine Package Bridge
Allows `from openmap_engine import ...` to resolve directly to `packages.scrapers.open_map`.
"""

import sys
from pathlib import Path

_open_map_dir = Path(__file__).resolve().parent.parent / "open_map"
if str(_open_map_dir) not in sys.path:
    sys.path.insert(0, str(_open_map_dir))

from packages.scrapers.open_map.config import (
    DEFAULT_OVERPASS_MIRRORS,
    OverpassConfig,
    default_config,
)
from packages.scrapers.open_map.circuit_breaker import EndpointCircuitBreaker
from packages.scrapers.open_map.quadtree import AdaptiveQuadtree
from packages.scrapers.open_map.checkpoint import EnterpriseCheckpointManager
from packages.scrapers.open_map.connector import OpenMapConnector
from packages.scrapers.open_map.taxonomy import (
    US_STATES,
    STATE_BOUNDING_BOXES,
    FIELDS_TAXONOMY,
)

__all__ = [
    "DEFAULT_OVERPASS_MIRRORS",
    "OverpassConfig",
    "default_config",
    "EndpointCircuitBreaker",
    "AdaptiveQuadtree",
    "EnterpriseCheckpointManager",
    "OpenMapConnector",
    "US_STATES",
    "STATE_BOUNDING_BOXES",
    "FIELDS_TAXONOMY",
]
