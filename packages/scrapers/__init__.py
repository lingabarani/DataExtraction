"""
DataExtraction — Distributed Extraction Engines
===============================================
Exports unified base scraper, federal statutory registries, OSM, and GMaps scrapers.
"""

from packages.scrapers.base_scraper import BaseScraper, CircuitBreakerOpenException

__all__ = [
    "BaseScraper",
    "CircuitBreakerOpenException",
]

