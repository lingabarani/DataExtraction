"""
Unit tests for GMapsScraper BaseScraper wrapper
"""

import pytest
from unittest.mock import patch, MagicMock
from packages.scrapers.google_maps.gmaps_scraper import GMapsScraper, run


def test_gmaps_scraper_init():
    scraper = GMapsScraper(rate_limit_per_second=5.0)
    assert scraper.name == "GMAPS_GEOSPATIAL"
    assert scraper.rate_limit == 5.0
    assert scraper.circuit_state == "CLOSED"


def test_gmaps_scraper_dry_run():
    scraper = GMapsScraper()
    res = scraper.scrape(region="US-CA", vertical="healthcare", limit=10, dry_run=True)
    assert res["status"] == "SUCCESS"
    assert res["mode"] == "dry_run"
    assert res["region"] == "US-CA"
    assert res["vertical"] == "healthcare"
    assert "metrics" in res
    assert res["metrics"]["requests_success"] >= 1


def test_gmaps_scraper_convenience_run():
    res = run(region="US-TX", vertical="restaurant", limit=5, dry_run=True)
    assert res["status"] == "SUCCESS"
    assert res["mode"] == "dry_run"
    assert res["region"] == "US-TX"

