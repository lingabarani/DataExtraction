"""
DataExtraction — ProPublica Federal Scraper
===========================================
ProPublica Nonprofit Explorer 990 filings extraction engine.
"""

from typing import Any, Dict, List, Optional
from packages.scrapers.base_scraper import BaseScraper
from packages.scrapers.federal import fetch_propublica


class ProPublicaScraper(BaseScraper):
    """ProPublica Nonprofit Explorer Scraper."""

    def __init__(self):
        super().__init__(
            name="PROPUBLICA",
            rate_limit_per_second=4.0,
            circuit_failure_threshold=5,
            circuit_cooldown_seconds=30.0,
        )

    def scrape(self, states: Optional[List[str]] = None, limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
        """Executes ProPublica 990 filings extraction."""
        return fetch_propublica.run(states=states, limit=limit, dry_run=dry_run) or {"status": "SUCCESS"}


def run(states: Optional[List[str]] = None, limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
    scraper = ProPublicaScraper()
    return scraper.scrape(states=states, limit=limit, dry_run=dry_run)

