"""
DataExtraction — Extraction API Router
======================================
Endpoints for managing direct, ad-hoc, and scheduled scraping extractions:
  - Trigger individual statutory sovereign registry scrapers (SEC, CMS, FDIC, SAM, USAspending)
  - Trigger geospatial crawlers (OSM Overpass bounding box & Google Maps places)
  - Inspect extraction health, scraper politeness metrics, and circuit breaker states
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from packages.api.dependencies import get_current_user, require_admin, UserPrincipal
from packages.scrapers.federal.cms_npi_scraper import CmsNpiScraper
from packages.scrapers.federal.sec_edgar_scraper import SecEdgarScraper
from packages.scrapers.federal.fdic_scraper import FdicScraper
from packages.scrapers.federal.usaspending_scraper import UsaspendingScraper
from packages.scrapers.federal.propublica_scraper import ProPublicaScraper
from packages.scrapers.federal.sam_gov_scraper import SamGovScraper
from packages.scrapers.open_map.osm_scraper import OsmScraper
from packages.scrapers.google_maps.gmaps_scraper import GMapsScraper

router = APIRouter(prefix="/api/extraction", tags=["Extraction"])


class ScraperTriggerRequest(BaseModel):
    source: str = Field(..., description="Target source: sec, cms, fdic, usaspending, propublica, sam, osm, gmaps")
    limit: int = Field(0, description="Max records to scrape (0 for unlimited)")
    dry_run: bool = Field(False, description="Dry run mode without database writes")
    params: Dict[str, Any] = Field(default_factory=dict, description="Source-specific parameters")


@router.post("/trigger", status_code=status.HTTP_202_ACCEPTED)
def trigger_extraction(
    payload: ScraperTriggerRequest,
    current_user: UserPrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """Trigger an ad-hoc scraper extraction task."""
    src = payload.source.lower().strip()
    lim = payload.limit
    dry = payload.dry_run

    scrapers = {
        "sec": lambda: SecEdgarScraper().scrape(limit=lim, dry_run=dry),
        "cms": lambda: CmsNpiScraper().scrape(limit=lim, dry_run=dry),
        "fdic": lambda: FdicScraper().scrape(limit=lim, dry_run=dry),
        "usaspending": lambda: UsaspendingScraper().scrape(limit=lim, dry_run=dry),
        "propublica": lambda: ProPublicaScraper().scrape(limit=lim, dry_run=dry),
        "sam": lambda: SamGovScraper().scrape(limit=lim, dry_run=dry),
        "osm": lambda: OsmScraper().scrape(limit=lim, dry_run=dry),
        "gmaps": lambda: GMapsScraper().scrape(limit=lim, dry_run=dry),
    }

    if src not in scrapers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown source '{payload.source}'. Available: {list(scrapers.keys())}",
        )

    try:
        result = scrapers[src]()
        return {
            "status": "ACCEPTED",
            "source": src,
            "dry_run": dry,
            "result": result,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scraper execution failed: {str(exc)}",
        )


@router.get("/sources")
def list_extraction_sources(
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """List available statutory and geospatial scraper sources."""
    return {
        "federal_registries": ["sec_edgar", "cms_npi", "fdic", "usaspending", "propublica", "sam_gov"],
        "geospatial_engines": ["osm_overpass", "google_maps_places"],
        "vendor_connectors": ["gleif_lei", "pdl", "apollo", "zoominfo"],
    }
