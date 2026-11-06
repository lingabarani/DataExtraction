"""
DataExtraction — SAM.gov Federal Scraper
========================================
System for Award Management (SAM.gov) federal entity registration and exclusion engine.
"""

from typing import Any, Dict
from packages.scrapers.base_scraper import BaseScraper
from packages.scrapers.federal import fetch_sam_gov


class SamGovScraper(BaseScraper):
    """SAM.gov Federal Entity Scraper."""

    def __init__(self):
        super().__init__(
            name="SAM_GOV",
            rate_limit_per_second=3.0,
            circuit_failure_threshold=5,
            circuit_cooldown_seconds=45.0,
        )

    def scrape(self, limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
        """Executes SAM.gov entity extraction."""
        return fetch_sam_gov.run(limit=limit, dry_run=dry_run) or {"status": "SUCCESS"}


def run(limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
    scraper = SamGovScraper()
    return scraper.scrape(limit=limit, dry_run=dry_run)

