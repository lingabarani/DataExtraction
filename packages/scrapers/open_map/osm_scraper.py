"""
DataExtraction — OpenStreetMap Geospatial Scraper
==================================================
Extracts point-of-interest (POI) and commercial entities from OpenStreetMap Overpass API.
Inherits from BaseScraper for rate limiting and circuit breaking.
"""

import sys
from pathlib import Path
_OPEN_MAP_DIR = Path(__file__).resolve().parent
if str(_OPEN_MAP_DIR) not in sys.path:
    sys.path.insert(0, str(_OPEN_MAP_DIR))

from typing import Any, Dict, List, Optional
from packages.scrapers.base_scraper import BaseScraper
from packages.scrapers.open_map.src.osm_state_collector import OSMStateCollector


class OsmScraper(BaseScraper):
    """OpenStreetMap Geospatial Scraper."""

    def __init__(self):
        super().__init__(
            name="OSM_GEOSPATIAL",
            rate_limit_per_second=2.0,  # Overpass API respectful politeness
            circuit_failure_threshold=4,
            circuit_cooldown_seconds=60.0,
        )

    def scrape(
        self,
        states: Optional[List[str]] = None,
        fields: Optional[List[str]] = None,
        limit: int = 0,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Runs OSM state POI collection."""
        collector = OSMStateCollector()
        target_states = states or ["Alabama"]
        results = {}
        for state in target_states:
            res = collector.collect_state(state=state, dry_run=dry_run)
            results[state] = res
        return {"status": "SUCCESS", "states_collected": len(results), "results": results}


def run(states: Optional[List[str]] = None, dry_run: bool = False) -> Dict[str, Any]:
    scraper = OsmScraper()
    return scraper.scrape(states=states, dry_run=dry_run)

