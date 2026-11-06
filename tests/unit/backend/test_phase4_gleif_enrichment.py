"""
DataExtraction — Unit Test Suite: Phase 4 GLEIF LEI Enrichment
==============================================================
Validates:
  1. Exact 20-character ISO 17442 LEI lookups via GleifEnrichmentClient.
  2. Legal suffix normalization and country-filtered search.
  3. Multi-signal matching score calculation (Name + Postal Code boost).
  4. Three-Tier Decision Policy enforcement in enrich_gleif_lei_activity:
     - Confidence >= 0.95 -> AUTO_ENRICH
     - 0.70 <= Confidence < 0.95 -> QUARANTINE_REVIEW
     - Confidence < 0.70 -> NO_MATCH
  5. Error resilience on 404s, malformed identifiers, and API timeouts.
"""

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch

from packages.scrapers.us_enrichment.connectors.gleif_client import (
    GleifEnrichmentClient,
    gleif_client,
)
from packages.temporal.activities.federal_activities import enrich_gleif_lei_activity


SAMPLE_GLEIF_RESPONSE = {
    "data": [
        {
            "type": "lei-records",
            "id": "5493006MHB84DD0ZWV18",
            "attributes": {
                "lei": "5493006MHB84DD0ZWV18",
                "entity": {
                    "legalName": {
                        "name": "ACME INDUSTRIAL HOLDINGS, INC.",
                        "language": "en"
                    },
                    "jurisdiction": "US-DE",
                    "status": "ACTIVE",
                    "legalAddress": {
                        "country": "US",
                        "city": "Wilmington",
                        "postalCode": "19801"
                    },
                    "headquartersAddress": {
                        "country": "US",
                        "city": "New York",
                        "postalCode": "10001"
                    }
                },
                "registration": {
                    "initialRegistrationDate": "2015-06-18T10:00:00Z",
                    "lastUpdateDate": "2024-01-10T12:00:00Z",
                    "status": "ISSUED",
                    "managingLou": "5299000J2J4500000000"
                }
            }
        }
    ]
}


class TestGleifEnrichmentClient(unittest.TestCase):
    """Test suite for GleifEnrichmentClient connector."""

    def setUp(self):
        self.client = GleifEnrichmentClient(timeout=5)

    def test_lookup_by_lei_invalid_format(self):
        """LEIs shorter or longer than 20 characters must return None without HTTP call."""
        self.assertIsNone(self.client.lookup_by_lei("INVALID"))
        self.assertIsNone(self.client.lookup_by_lei("123456789012345678901"))  # 21 chars

    @patch("requests.Session.get")
    def test_lookup_by_lei_success(self, mock_get):
        """Exact 20-character LEI lookup correctly parses JSON:API schema."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": SAMPLE_GLEIF_RESPONSE["data"][0]}
        mock_get.return_value = mock_resp

        result = self.client.lookup_by_lei("5493006MHB84DD0ZWV18")

        self.assertIsNotNone(result)
        self.assertEqual(result["lei"], "5493006MHB84DD0ZWV18")
        self.assertEqual(result["legal_name"], "ACME INDUSTRIAL HOLDINGS, INC.")
        self.assertEqual(result["normalized_name"], "ACME INDUSTRIAL HOLDINGS")
        self.assertEqual(result["jurisdiction"], "US-DE")
        self.assertEqual(result["entity_status"], "ACTIVE")
        self.assertEqual(result["registration_status"], "ISSUED")
        self.assertEqual(result["country"], "US")
        self.assertEqual(result["city"], "Wilmington")
        self.assertEqual(result["postal_code"], "19801")
        self.assertEqual(result["source"], "GLEIF_LEI")

    @patch("requests.Session.get")
    def test_lookup_by_lei_not_found(self, mock_get):
        """HTTP 404 status safely returns None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        result = self.client.lookup_by_lei("00000000000000000000")
        self.assertIsNone(result)

    @patch("requests.Session.get")
    def test_search_by_name_with_postal_boost(self, mock_get):
        """Search normalizes legal suffixes and awards boost for matching postal code."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_GLEIF_RESPONSE
        mock_get.return_value = mock_resp

        # Search with matching postal code
        results = self.client.search_by_name(
            company_name="Acme Industrial Holdings LLC",
            country="US",
            postal_code="19801",
        )

        self.assertEqual(len(results), 1)
        top = results[0]
        self.assertEqual(top["lei"], "5493006MHB84DD0ZWV18")
        # Base ratio of ACME INDUSTRIAL HOLDINGS is 1.0 * 0.85 + 0.15 postal boost = 1.0
        self.assertGreaterEqual(top["match_confidence"], 0.95)

    @patch("requests.Session.get")
    def test_search_by_name_partial_similarity(self, mock_get):
        """Partial name match without postal match scores in the quarantine range."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_GLEIF_RESPONSE
        mock_get.return_value = mock_resp

        # Query has extra token and different postal code
        results = self.client.search_by_name(
            company_name="Acme Industrial Systems Corp",
            country="US",
            postal_code="90210",
        )

        self.assertEqual(len(results), 1)
        confidence = results[0]["match_confidence"]
        self.assertGreater(confidence, 0.60)
        self.assertLess(confidence, 0.95)


class TestGleifTemporalActivity(unittest.TestCase):
    """Test suite for enrich_gleif_lei_activity."""

    def setUp(self):
        self.db_patcher = patch("packages.infrastructure.db_connector.get_connection", return_value=None)
        self.mock_get_conn = self.db_patcher.start()
        self.rel_patcher = patch("packages.infrastructure.db_connector.release_connection", return_value=None)
        self.rel_patcher.start()

    def tearDown(self):
        self.rel_patcher.stop()
        self.db_patcher.stop()

    @patch("packages.scrapers.us_enrichment.connectors.gleif_client.gleif_client.lookup_by_lei")
    def test_activity_exact_lei_auto_enrich(self, mock_lookup):
        """Exact LEI input results in AUTO_ENRICH decision with confidence 1.0."""
        mock_lookup.return_value = {
            "lei": "5493006MHB84DD0ZWV18",
            "legal_name": "ACME INDUSTRIAL HOLDINGS, INC.",
            "normalized_name": "ACME INDUSTRIAL HOLDINGS",
        }

        payload = {
            "lei": "5493006MHB84DD0ZWV18",
            "entity_id": "test-uuid-1234",
        }

        result = asyncio.run(enrich_gleif_lei_activity(payload))

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["decision"], "AUTO_ENRICH")
        self.assertEqual(result["lei"], "5493006MHB84DD0ZWV18")
        self.assertEqual(result["confidence"], 1.0)
        self.assertEqual(result["entity_id"], "test-uuid-1234")

    @patch("packages.scrapers.us_enrichment.connectors.gleif_client.gleif_client.search_by_name")
    def test_activity_fuzzy_high_confidence_auto_enrich(self, mock_search):
        """Confidence >= 0.95 triggers AUTO_ENRICH."""
        mock_search.return_value = [
            {
                "lei": "5493006MHB84DD0ZWV18",
                "legal_name": "ACME HOLDINGS CORP",
                "match_confidence": 0.98,
            }
        ]

        payload = {"company_name": "Acme Holdings LLC", "country": "US"}
        result = asyncio.run(enrich_gleif_lei_activity(payload))

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["decision"], "AUTO_ENRICH")
        self.assertEqual(result["confidence"], 0.98)

    @patch("packages.scrapers.us_enrichment.connectors.gleif_client.gleif_client.search_by_name")
    def test_activity_medium_confidence_quarantine_review(self, mock_search):
        """Confidence between 0.70 and 0.9499 routes to QUARANTINE_REVIEW."""
        mock_search.return_value = [
            {
                "lei": "5493006MHB84DD0ZWV18",
                "legal_name": "ACME GLOBAL HOLDINGS CORP",
                "match_confidence": 0.82,
            }
        ]

        payload = {"company_name": "Acme Holdings", "country": "US"}
        result = asyncio.run(enrich_gleif_lei_activity(payload))

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["decision"], "QUARANTINE_REVIEW")
        self.assertEqual(result["confidence"], 0.82)

    @patch("packages.scrapers.us_enrichment.connectors.gleif_client.gleif_client.search_by_name")
    def test_activity_low_confidence_no_match(self, mock_search):
        """Confidence < 0.70 results in NO_MATCH."""
        mock_search.return_value = [
            {
                "lei": "99999999999999999999",
                "legal_name": "COMPLETELY DIFFERENT ENTITY",
                "match_confidence": 0.25,
            }
        ]

        payload = {"company_name": "Acme Holdings", "country": "US"}
        result = asyncio.run(enrich_gleif_lei_activity(payload))

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["decision"], "NO_MATCH")
        self.assertEqual(result["confidence"], 0.25)

    @patch("packages.scrapers.us_enrichment.connectors.gleif_client.gleif_client.search_by_name")
    def test_activity_resilience_on_exception(self, mock_search):
        """Exceptions in client do not crash activity, returning structured FAILED status."""
        mock_search.side_effect = RuntimeError("API Gateway Timeout")

        payload = {"company_name": "Acme Corp"}
        result = asyncio.run(enrich_gleif_lei_activity(payload))

        self.assertEqual(result["status"], "FAILED")
        self.assertIn("API Gateway Timeout", result["error"])

    @patch("packages.scrapers.us_enrichment.connectors.gleif_client.gleif_client.search_by_name")
    def test_activity_quarantine_db_insertion(self, mock_search):
        """Quarantined candidate records are inserted into kg_resolution.isolation_review_queue."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = ["11111111-2222-3333-4444-555555555555"]
        mock_conn.cursor.return_value = mock_cur
        self.mock_get_conn.return_value = mock_conn

        mock_search.return_value = [
            {
                "lei": "5493006MHB84DD0ZWV18",
                "legal_name": "ACME GLOBAL HOLDINGS CORP",
                "match_confidence": 0.85,
            }
        ]

        payload = {"company_name": "Acme Holdings", "entity_id": "test-entity-001"}
        result = asyncio.run(enrich_gleif_lei_activity(payload))

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["decision"], "QUARANTINE_REVIEW")
        self.assertEqual(result["review_id"], "11111111-2222-3333-4444-555555555555")
        mock_cur.execute.assert_called()
        mock_conn.commit.assert_called()

    @patch("packages.scrapers.us_enrichment.connectors.gleif_client.gleif_client.lookup_by_lei")
    def test_activity_auto_enrich_db_update(self, mock_lookup):
        """Auto-enriched records update companies table when database connection is present."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        self.mock_get_conn.return_value = mock_conn

        mock_lookup.return_value = {
            "lei": "5493006MHB84DD0ZWV18",
            "legal_name": "ACME INDUSTRIAL HOLDINGS, INC.",
        }

        payload = {"lei": "5493006MHB84DD0ZWV18", "entity_id": "test-entity-001"}
        result = asyncio.run(enrich_gleif_lei_activity(payload))

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["decision"], "AUTO_ENRICH")
        mock_cur.execute.assert_called()
        self.assertIn("UPDATE companies SET lei", mock_cur.execute.call_args[0][0])
        mock_conn.commit.assert_called()

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["decision"], "AUTO_ENRICH")
        mock_cur.execute.assert_called()
        self.assertIn("UPDATE companies SET lei", mock_cur.execute.call_args[0][0])
        mock_conn.commit.assert_called()


if __name__ == "__main__":
    unittest.main()
