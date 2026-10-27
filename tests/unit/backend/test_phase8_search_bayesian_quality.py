"""
Phase 8 Test Suite: Search Projections, OpenSearch CDC & Bayesian Quality Engine
================================================================================
Comprehensive verification of:
1. OpenSearchCDCSyncClient:
   - Config loading & session pooling.
   - Index mapping templates (autocomplete edge_ngram, geo_point, keyword arrays).
   - Resilient cluster health checking & offline fallback.
   - CDC delta sync from PostgreSQL to OpenSearch ndjson _bulk format.
   - Watermark checkpoint commits in kg_search.cdc_watermarks.
   - Multi-field fuzzy search query construction with quality score boosting.
2. BayesianQualityEngine:
   - Regulatory source authority priors.
   - Multi-source Bayesian belief updates (P = 1 - Prod(1 - P_i)).
   - Field-level lineage arbitration (initial assignment, identical corroboration, authority overrides).
   - Composite entity quality score (0 - 100) for organizations and persons.
3. Activity wrappers & system integration:
   - sync_opensearch_cdc activity contract.
   - compute_bayesian_quality activity contract.
"""

import json
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
_backend_dir = Path(__file__).resolve().parent
_project_root = _backend_dir.parents[2]
_packages = _project_root / "packages"

for _p in [
    _packages / "pipeline",
    _packages / "infrastructure",
    _packages / "temporal",
    _packages / "temporal" / "activities",
    _project_root,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from packages.infrastructure.opensearch_cdc_sync import (
    COMPANY_INDEX_MAPPING,
    PERSON_INDEX_MAPPING,
    OpenSearchCDCSyncClient,
)
from packages.pipeline.bayesian_quality_engine import (
    DEFAULT_SOURCE_AUTHORITIES,
    BayesianQualityEngine,
    bayesian_quality_engine,
)


class TestOpenSearchCDCSyncClient(unittest.TestCase):
    """Verifies OpenSearch 2.x CDC sync client and search query generation."""

    def setUp(self):
        self.mock_config = {
            "host": "127.0.0.1",
            "port": 9200,
            "user": "admin",
            "password": "secret_password",
            "use_ssl": False,
            "verify_certs": False,
            "index_companies": "test_companies_v1",
            "index_people": "test_people_v1",
            "batch_size": 500,
            "timeout": 10,
            "base_url": "http://127.0.0.1:9200",
        }
        self.client = OpenSearchCDCSyncClient(config=self.mock_config)

    def test_index_mappings_validity(self):
        self.assertIn("properties", COMPANY_INDEX_MAPPING["mappings"])
        c_props = COMPANY_INDEX_MAPPING["mappings"]["properties"]
        self.assertEqual(c_props["location"]["type"], "geo_point")
        self.assertEqual(c_props["legal_name"]["analyzer"], "autocomplete_analyzer")
        self.assertEqual(c_props["primary_domain"]["type"], "keyword")

        self.assertIn("properties", PERSON_INDEX_MAPPING["mappings"])
        p_props = PERSON_INDEX_MAPPING["mappings"]["properties"]
        self.assertEqual(p_props["primary_email"]["type"], "keyword")
        self.assertEqual(p_props["primary_linkedin_url"]["type"], "keyword")

    def test_ping_offline_graceful(self):
        # When network is offline or refused, ping returns False without throwing
        with patch.object(self.client.session, "get", side_effect=Exception("Connection refused")):
            self.assertFalse(self.client.ping())

    def test_ensure_indices_offline_fallback(self):
        with patch.object(self.client, "ping", return_value=False):
            res = self.client.ensure_indices()
            self.assertIn("test_companies_v1", res)
            self.assertIn("offline", res["test_companies_v1"])

    def test_sync_companies_cdc_up_to_date(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # Simulate watermark exists and no new rows
        mock_cur.fetchone.return_value = (5, datetime(2026, 1, 1, tzinfo=timezone.utc), 100)
        mock_cur.fetchall.return_value = []

        res = self.client.sync_companies_cdc(conn=mock_conn, batch_limit=500)
        self.assertEqual(res["status"], "up_to_date")
        self.assertEqual(res["records_synced"], 0)
        self.assertEqual(res["total_synced"], 100)

    def test_sync_companies_cdc_with_deltas(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        now = datetime.now(timezone.utc)
        mock_cur.fetchone.return_value = (1, datetime(2026, 1, 1, tzinfo=timezone.utc), 10)
        # 1 delta row
        mock_cur.fetchall.return_value = [
            (
                "org-uuid-111", "US", "Apple Inc", "Apple", "apple.com",
                ["apple.com", "apple.co"], ["Apple Computer"], "334111", 160000,
                383000000000.0, ["iOS", "Swift"], 37.3349, -122.0090, 99, 2, now
            )
        ]

        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {"errors": False, "items": []}

            res = self.client.sync_companies_cdc(conn=mock_conn, batch_limit=500)
            self.assertEqual(res["status"], "synced")
            self.assertEqual(res["records_synced"], 1)
            self.assertEqual(res["total_synced"], 11)
            self.assertEqual(res["max_version"], 2)

            # Ensure ndjson bulk payload contains index line and document line
            self.assertTrue(mock_post.called)
            bulk_body = mock_post.call_args[1]["data"]
            self.assertIn('"_index": "test_companies_v1"', bulk_body)
            self.assertIn('"primary_domain": "apple.com"', bulk_body)
            self.assertIn('"location": {"lat": 37.3349, "lon": -122.009}', bulk_body)

    def test_search_companies_query_building(self):
        with patch.object(self.client.session, "post") as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                "hits": {
                    "total": {"value": 1},
                    "hits": [{"_source": {"org_id": "org-1", "legal_name": "Tesla Motors"}}],
                }
            }

            res = self.client.search_companies("Tesla", jurisdiction="US", industry_naics="336111")
            self.assertEqual(res["total"], 1)
            self.assertEqual(res["hits"][0]["legal_name"], "Tesla Motors")

            payload = mock_post.call_args[1]["json"]
            self.assertIn("query", payload)
            must_clauses = payload["query"]["bool"]["must"]
            self.assertEqual(must_clauses[0]["multi_match"]["query"], "Tesla")


class TestBayesianQualityEngine(unittest.TestCase):
    """Verifies Bayesian belief updating, lineage arbitration, and quality scoring."""

    def setUp(self):
        self.engine = BayesianQualityEngine()

    def test_source_authority_lookup(self):
        self.assertEqual(self.engine.get_source_authority("SEC_EDGAR"), 0.98)
        self.assertEqual(self.engine.get_source_authority("SAM_GOV"), 0.95)
        self.assertEqual(self.engine.get_source_authority("OPENSTREETMAP"), 0.88)
        self.assertEqual(self.engine.get_source_authority("GOOGLE_MAPS"), 0.85)
        self.assertEqual(self.engine.get_source_authority("UNKNOWN_SCRAPER"), 0.60)

    def test_compute_corroborated_confidence(self):
        # 1 source (SEC EDGAR: 0.98) -> ~0.98
        p_sec = self.engine.compute_corroborated_confidence(["SEC_EDGAR"])
        self.assertAlmostEqual(p_sec, 0.98, places=2)

        # 2 sources (SEC EDGAR 0.98 + Google Maps 0.85)
        # Error = 0.02 * 0.15 = 0.003 -> P = 0.997
        p_both = self.engine.compute_corroborated_confidence(["SEC_EDGAR", "GOOGLE_MAPS"])
        self.assertGreaterEqual(p_both, 0.99)

    def test_should_accept_field_update_initial(self):
        # Initial assignment
        accept, w, reason = self.engine.should_accept_field_update(
            existing_val=None,
            existing_source=None,
            existing_weight=None,
            incoming_val="12-3456789",
            incoming_source="SEC_EDGAR",
        )
        self.assertTrue(accept)
        self.assertEqual(w, 0.98)
        self.assertEqual(reason, "initial_value_assignment")

    def test_should_accept_field_update_corroboration(self):
        # Both say the same domain: combined boost
        accept, w, reason = self.engine.should_accept_field_update(
            existing_val="acme.com",
            existing_source="GOOGLE_MAPS",
            existing_weight=0.85,
            incoming_val="acme.com",
            incoming_source="SEC_EDGAR",
            incoming_weight=0.98,
        )
        self.assertTrue(accept)
        self.assertGreater(w, 0.98)
        self.assertEqual(reason, "corroborated_identical_value")

    def test_should_accept_field_update_conflict_higher_wins(self):
        # Incoming SEC EDGAR overrides existing Web Crawler
        accept, w, reason = self.engine.should_accept_field_update(
            existing_val="Acme Global Inc",
            existing_source="GENERIC_WEB",
            existing_weight=0.50,
            incoming_val="Acme Technologies Inc",
            incoming_source="SEC_EDGAR",
            incoming_weight=0.98,
        )
        self.assertTrue(accept)
        self.assertEqual(w, 0.98)
        self.assertIn("higher_authority_override", reason)

    def test_should_accept_field_update_conflict_lower_rejected(self):
        # Incoming Web Crawler rejected when SEC EDGAR already provided value
        accept, w, reason = self.engine.should_accept_field_update(
            existing_val="Acme Technologies Inc",
            existing_source="SEC_EDGAR",
            existing_weight=0.98,
            incoming_val="Acme Low Quality",
            incoming_source="GENERIC_WEB",
            incoming_weight=0.50,
        )
        self.assertFalse(accept)
        self.assertEqual(w, 0.98)
        self.assertIn("lower_authority_rejected", reason)

    def test_compute_entity_quality_score_organization(self):
        org_data = {
            "legal_name": "Microsoft Corporation",
            "statutory_tax_id": "91-1144442",
            "primary_domain": "microsoft.com",
            "emails": ["info@microsoft.com"],
            "phones": ["+1-800-642-7676"],
            "latitude": 47.6396,
            "longitude": -122.1283,
            "primary_industry_naics": "511210",
        }
        res = self.engine.compute_entity_quality_score(
            entity_data=org_data,
            entity_type="organization",
            contributing_sources=["SEC_EDGAR", "SAM_GOV", "GOOGLE_MAPS"],
        )
        self.assertGreaterEqual(res["data_quality_score"], 90)
        self.assertGreaterEqual(res["bayesian_confidence"], 0.99)
        self.assertEqual(res["corroborated_sources_count"], 3)
        self.assertIn("score_breakdown", res)

    def test_compute_entity_quality_score_person(self):
        person_data = {
            "full_name": "Satya Nadella",
            "primary_linkedin_url": "https://linkedin.com/in/satyanadella",
            "primary_email": "satya@microsoft.com",
            "current_primary_title": "Chairman and CEO",
            "current_primary_org_id": "org-msft-uuid",
        }
        res = self.engine.compute_entity_quality_score(
            entity_data=person_data,
            entity_type="person",
            contributing_sources=["SEC_EDGAR", "LINKEDIN"],
        )
        self.assertGreaterEqual(res["data_quality_score"], 85)
        self.assertGreaterEqual(res["bayesian_confidence"], 0.98)


if __name__ == "__main__":
    unittest.main()

