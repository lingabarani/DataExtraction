"""
DataExtraction — Unit Test Suite: Phase 4 Distributed Scraper Engines
======================================================================
Validates:
  1. BaseScraper framework:
     - Rate-limiting / politeness calculation.
     - Circuit breaker states: CLOSED -> OPEN -> HALF_OPEN.
     - CircuitBreakerOpenException rejection when tripped.
     - Compliant SEC EDGAR / Sovereign User-Agent generation.
     - Performance & audit telemetry collection.
  2. Federal Scrapers:
     - CmsNpiScraper, SecEdgarScraper, FdicScraper, UsaspendingScraper,
       ProPublicaScraper, SamGovScraper.
  3. Geospatial Scrapers:
     - OsmScraper, GMapsScraper.
"""

import time
import unittest
from unittest.mock import MagicMock, patch

import requests

from packages.scrapers.base_scraper import BaseScraper, CircuitBreakerOpenException
from packages.scrapers.federal.cms_npi_scraper import CmsNpiScraper
from packages.scrapers.federal.sec_edgar_scraper import SecEdgarScraper
from packages.scrapers.federal.fdic_scraper import FdicScraper
from packages.scrapers.federal.usaspending_scraper import UsaspendingScraper
from packages.scrapers.federal.propublica_scraper import ProPublicaScraper
from packages.scrapers.federal.sam_gov_scraper import SamGovScraper
from packages.scrapers.open_map.osm_scraper import OsmScraper
from packages.scrapers.google_maps.gmaps_scraper import GMapsScraper


class ConcreteTestScraper(BaseScraper):
    """Concrete scraper for base behavior verification."""

    def scrape(self, limit: int = 0, dry_run: bool = False):
        return {"records": 10, "status": "SUCCESS"}


class TestBaseScraper(unittest.TestCase):
    """Verifies BaseScraper rate limiting, circuit breaker, and politeness."""

    def test_user_agent_format(self):
        scraper = ConcreteTestScraper(name="Test", user_agent_contact="auditor@domain.com")
        ua = scraper.get_user_agent()
        self.assertIn("contact=auditor@domain.com", ua)
        self.assertIn("DataExtractionPlatform", ua)

    def test_politeness_interval(self):
        scraper = ConcreteTestScraper(name="Test", rate_limit_per_second=10.0)
        self.assertAlmostEqual(scraper.min_interval, 0.1, places=3)

    @patch("requests.Session.request")
    def test_successful_request_flow(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"ok": true}'
        mock_req.return_value = mock_resp

        scraper = ConcreteTestScraper(name="Test")
        resp = scraper.fetch("https://api.example.com/data")
        self.assertEqual(resp.status_code, 200)

        metrics = scraper.get_metrics()
        self.assertEqual(metrics["requests_total"], 1)
        self.assertEqual(metrics["requests_success"], 1)
        self.assertEqual(metrics["circuit_state"], "CLOSED")

    @patch("requests.Session.request")
    def test_circuit_breaker_trip_and_cooldown(self, mock_req):
        mock_req.side_effect = requests.exceptions.ConnectionError("Connection reset")

        scraper = ConcreteTestScraper(
            name="TestTrip",
            rate_limit_per_second=100.0,
            circuit_failure_threshold=3,
            circuit_cooldown_seconds=0.2,
        )

        # 1. Trigger failures until circuit trips
        for _ in range(3):
            with self.assertRaises(Exception):
                scraper.fetch("https://failing.api/test", max_retries=1)

        self.assertEqual(scraper.circuit_state, "OPEN")
        self.assertEqual(scraper.metrics["circuit_trips"], 1)

        # 2. Subsequent call must immediately fail with CircuitBreakerOpenException
        with self.assertRaises(CircuitBreakerOpenException):
            scraper.fetch("https://failing.api/test")

        # 3. Wait for cooldown
        time.sleep(0.25)
        # Next call evaluates to HALF_OPEN probe
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"recovered"
        mock_req.side_effect = None
        mock_req.return_value = mock_resp

        resp = scraper.fetch("https://failing.api/test", max_retries=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(scraper.circuit_state, "CLOSED")


class TestDistributedScraperEngines(unittest.TestCase):
    """Verifies all specialized scrapers instantiate and expose compliant parameters."""

    def test_federal_scrapers_initialization(self):
        sec = SecEdgarScraper()
        self.assertEqual(sec.name, "SEC_EDGAR")
        self.assertLessEqual(sec.rate_limit, 10.0)

        cms = CmsNpiScraper()
        self.assertEqual(cms.name, "CMS_NPI")

        fdic = FdicScraper()
        self.assertEqual(fdic.name, "FDIC")

        usa = UsaspendingScraper()
        self.assertEqual(usa.name, "USASPENDING")

        prop = ProPublicaScraper()
        self.assertEqual(prop.name, "PROPUBLICA")

        sam = SamGovScraper()
        self.assertEqual(sam.name, "SAM_GOV")

    def test_geospatial_scrapers_initialization(self):
        osm = OsmScraper()
        self.assertEqual(osm.name, "OSM_GEOSPATIAL")

        gmaps = GMapsScraper()
        self.assertEqual(gmaps.name, "GMAPS_GEOSPATIAL")


if __name__ == "__main__":
    unittest.main()

