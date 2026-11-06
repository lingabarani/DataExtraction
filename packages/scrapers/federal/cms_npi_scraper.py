"""
DataExtraction — CMS NPI Federal Scraper
========================================
Official National Provider Identifier (NPI) Registry extraction engine.
Inherits from BaseScraper for circuit breaking and rate limiting.
"""

from typing import Any, Dict
from packages.scrapers.base_scraper import BaseScraper
from packages.scrapers.federal import fetch_cms_npi


class CmsNpiScraper(BaseScraper):
    """CMS NPI Sovereign Registry Scraper."""

    def __init__(self):
        super().__init__(
            name="CMS_NPI",
            rate_limit_per_second=5.0,
            circuit_failure_threshold=5,
            circuit_cooldown_seconds=30.0,
        )

    def scrape(self, limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
        """Executes CMS NPI bulk extraction."""
        return fetch_cms_npi.run(limit=limit, dry_run=dry_run) or {"status": "SUCCESS"}


# Programmatic helper
def run(limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
    scraper = CmsNpiScraper()
    return scraper.scrape(limit=limit, dry_run=dry_run)

