"""
DataExtraction — FDIC Federal Scraper
=====================================
Official FDIC financial institution directory and bank branch extraction engine.
"""

from typing import Any, Dict
from packages.scrapers.base_scraper import BaseScraper
from packages.scrapers.federal import fetch_fdic


class FdicScraper(BaseScraper):
    """FDIC Bank Registry Scraper."""

    def __init__(self):
        super().__init__(
            name="FDIC",
            rate_limit_per_second=5.0,
            circuit_failure_threshold=5,
            circuit_cooldown_seconds=30.0,
        )

    def scrape(self, source: str = "both", limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
        """Executes FDIC bank institutions and branches extraction."""
        return fetch_fdic.run(source=source, dry_run=dry_run) or {"status": "SUCCESS"}


def run(source: str = "both", dry_run: bool = False) -> Dict[str, Any]:
    scraper = FdicScraper()
    return scraper.scrape(source=source, dry_run=dry_run)

