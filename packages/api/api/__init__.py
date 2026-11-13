"""
DataExtraction — API Routers Package
====================================
Lazily exposes canonical route modules via PEP 562 __getattr__ so importing a
single router or dependency never eagerly loads all routers or Temporal workflows.
"""

import importlib

_EXPORTED_ROUTERS = {
    "orchestration_router": ("packages.api.routers.orchestration_router", "router"),
    "extraction_router": ("packages.api.routers.extraction_router", "router"),
    "search_router": ("packages.api.routers.search_router", "router"),
    "enrichment_router": ("packages.api.routers.enrichment_router", "router"),
}


def __getattr__(name: str):
    if name in _EXPORTED_ROUTERS:
        mod_path, attr = _EXPORTED_ROUTERS[name]
        return getattr(importlib.import_module(mod_path), attr)
    return importlib.import_module(f"packages.api.routers.{name}")


__all__ = [
    "orchestration_router",
    "extraction_router",
    "search_router",
    "enrichment_router",
]
