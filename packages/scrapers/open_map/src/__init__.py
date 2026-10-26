"""
Open Map Extraction Engine.
"""

from .config import OverpassConfig, default_config
from .circuit_breaker import EndpointCircuitBreaker
from .quadtree import AdaptiveQuadtree, split_bounding_box
from .checkpoint import EnterpriseCheckpointManager

try:
    from .pipeline import CollectionPipeline
    __all__ = [
        "OverpassConfig",
        "default_config",
        "EndpointCircuitBreaker",
        "AdaptiveQuadtree",
        "split_bounding_box",
        "EnterpriseCheckpointManager",
        "CollectionPipeline",
    ]
except ImportError:
    __all__ = [
        "OverpassConfig",
        "default_config",
        "EndpointCircuitBreaker",
        "AdaptiveQuadtree",
        "split_bounding_box",
        "EnterpriseCheckpointManager",
    ]
