"""
DataExtraction — Federal Scrapers Package
=========================================
Exports official sovereign registry scrapers.
"""

from packages.scrapers.federal.cms_npi_scraper import CmsNpiScraper
from packages.scrapers.federal.sec_edgar_scraper import SecEdgarScraper
from packages.scrapers.federal.fdic_scraper import FdicScraper
from packages.scrapers.federal.usaspending_scraper import UsaspendingScraper
from packages.scrapers.federal.propublica_scraper import ProPublicaScraper
from packages.scrapers.federal.sam_gov_scraper import SamGovScraper

__all__ = [
    "CmsNpiScraper",
    "SecEdgarScraper",
    "FdicScraper",
    "UsaspendingScraper",
    "ProPublicaScraper",
    "SamGovScraper",
]
