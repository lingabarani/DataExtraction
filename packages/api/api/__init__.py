"""
DataExtraction — API Routers Package
====================================
Exports all route modules:
  - orchestration_router: Temporal Sagas and workflow control
  - extraction_router: Statutory and geospatial scraping triggers
  - search_router: Knowledge Graph queries and OpenSearch proxy
"""

from packages.api.routers.orchestration_router import router as orchestration_router
from packages.api.routers.extraction_router import router as extraction_router
from packages.api.routers.search_router import router as search_router
from packages.api.routers.enrichment_router import router as enrichment_router

__all__ = [
    "orchestration_router",
    "extraction_router",
    "search_router",
    "enrichment_router",
]
