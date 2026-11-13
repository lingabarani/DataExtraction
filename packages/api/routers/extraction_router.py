"""
DataExtraction — Extraction API Router
======================================
Endpoints for managing direct, ad-hoc, and scheduled scraping extractions:
  - Trigger individual statutory sovereign registry scrapers (SEC, CMS, FDIC, SAM, USAspending)
  - Trigger geospatial crawlers (OSM Overpass bounding box & Google Maps places)
  - Inspect extraction health, scraper politeness metrics, and circuit breaker states

Performance note: All scraper classes are imported lazily (inside the request handler),
not at module load time. This eliminates 200-600ms of cold-start overhead and prevents
pandas/aiohttp/lxml from loading until a scraper is actually triggered.
"""

import importlib
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from packages.api.dependencies import get_current_user, require_admin, UserPrincipal

logger = logging.getLogger("dataextraction.api.extraction")

router = APIRouter(prefix="/api/extraction", tags=["Extraction"])

# ---------------------------------------------------------------------------
# Registry of scraper sources — module path and class name only.
# Nothing is imported here; importlib resolves them at request time.
# ---------------------------------------------------------------------------
_SCRAPER_REGISTRY: Dict[str, Dict[str, str]] = {
    "sec":          {"module": "packages.scrapers.federal.sec_edgar_scraper",  "class": "SecEdgarScraper"},
    "cms":          {"module": "packages.scrapers.federal.cms_npi_scraper",    "class": "CmsNpiScraper"},
    "fdic":         {"module": "packages.scrapers.federal.fdic_scraper",        "class": "FdicScraper"},
    "usaspending":  {"module": "packages.scrapers.federal.usaspending_scraper", "class": "UsaspendingScraper"},
    "propublica":   {"module": "packages.scrapers.federal.propublica_scraper",  "class": "ProPublicaScraper"},
    "sam":          {"module": "packages.scrapers.federal.sam_gov_scraper",     "class": "SamGovScraper"},
    "osm":          {"module": "packages.scrapers.open_map.osm_scraper",        "class": "OsmScraper"},
    "gmaps":        {"module": "packages.scrapers.google_maps.gmaps_scraper",   "class": "GMapsScraper"},
}


def _load_scraper(source: str):
    """
    Lazily import and instantiate a scraper class by registry key.
    Raises HTTPException(400) for unknown sources, HTTPException(500) for import failures.
    """
    entry = _SCRAPER_REGISTRY.get(source)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown source '{source}'. Available: {sorted(_SCRAPER_REGISTRY.keys())}",
        )
    try:
        mod = importlib.import_module(entry["module"])
        cls = getattr(mod, entry["class"])
        return cls()
    except ImportError as exc:
        logger.error("Scraper module import failed for source '%s': %s", source, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Scraper '{source}' is not available in this environment: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("Scraper instantiation failed for source '%s': %s", source, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load scraper '{source}': {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ScraperTriggerRequest(BaseModel):
    source: str = Field(
        ...,
        description=f"Target source. Available: {sorted(_SCRAPER_REGISTRY.keys())}",
    )
    limit: int = Field(0, ge=0, description="Max records to scrape (0 = unlimited)")
    dry_run: bool = Field(False, description="Simulate without writing to the database")
    params: Dict[str, Any] = Field(default_factory=dict, description="Source-specific parameters")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
def trigger_extraction(
    payload: ScraperTriggerRequest,
    current_user: UserPrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Trigger an ad-hoc scraper extraction task for the specified data source.
    Admin privileges required. Scraper modules are loaded on demand.
    """
    src = payload.source.lower().strip()
    scraper = _load_scraper(src)

    logger.info(
        "Extraction triggered: source=%s limit=%d dry_run=%s user=%s",
        src, payload.limit, payload.dry_run, current_user.email,
    )

    try:
        result = scraper.scrape(limit=payload.limit, dry_run=payload.dry_run, **payload.params)
        return {
            "status": "ACCEPTED",
            "source": src,
            "dry_run": payload.dry_run,
            "result": result,
        }
    except Exception as exc:
        logger.error("Scraper execution failed for source '%s': %s", src, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scraper execution failed for '{src}': {exc}",
        ) from exc


@router.get("/sources")
def list_extraction_sources(
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """List all registered statutory and geospatial scraper sources."""
    return {
        "federal_registries": ["sec", "cms", "fdic", "usaspending", "propublica", "sam"],
        "geospatial_engines": ["osm", "gmaps"],
        "available_sources": sorted(_SCRAPER_REGISTRY.keys()),
    }
