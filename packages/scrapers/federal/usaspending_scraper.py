"""
DataExtraction — USAspending Federal Scraper
============================================
Official USAspending.gov federal contract awards, grants, and recipient extraction engine.
"""

from typing import Any, Dict
from packages.scrapers.base_scraper import BaseScraper
from packages.scrapers.federal import fetch_usaspending


class UsaspendingScraper(BaseScraper):
    """USAspending Federal Awards Scraper."""

    def __init__(self):
        super().__init__(
            name="USASPENDING",
            rate_limit_per_second=5.0,
            circuit_failure_threshold=5,
            circuit_cooldown_seconds=45.0,
        )

    def scrape(self, limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
        """Executes USAspending contract awards extraction."""
        return fetch_usaspending.run(limit=limit, dry_run=dry_run) or {"status": "SUCCESS"}


def run(limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
    scraper = UsaspendingScraper()
    return scraper.scrape(limit=limit, dry_run=dry_run)

