"""
DataExtraction — SEC EDGAR Federal Scraper
==========================================
Official SEC EDGAR filings and financial disclosures extraction engine.
Implements SEC Fair Access rate limiting (<= 10 requests per second) and user-agent declaration.
"""

from typing import Any, Dict
from packages.scrapers.base_scraper import BaseScraper
from packages.scrapers.federal import fetch_sec_edgar


class SecEdgarScraper(BaseScraper):
    """SEC EDGAR Sovereign Registry Scraper."""

    def __init__(self):
        super().__init__(
            name="SEC_EDGAR",
            rate_limit_per_second=9.5,  # Strictly compliant with SEC 10 req/s threshold
            circuit_failure_threshold=5,
            circuit_cooldown_seconds=60.0,
        )

    def scrape(self, mode: str = "tickers", limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
        """Executes SEC EDGAR extraction."""
        return fetch_sec_edgar.run(mode=mode, limit=limit, dry_run=dry_run) or {"status": "SUCCESS"}


def run(mode: str = "tickers", limit: int = 0, dry_run: bool = False) -> Dict[str, Any]:
    scraper = SecEdgarScraper()
    return scraper.scrape(mode=mode, limit=limit, dry_run=dry_run)

