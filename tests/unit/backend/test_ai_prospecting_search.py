"""
DataExtraction — Unit Test Suite: AI Prospecting Search & Intelligence
======================================================================
Validates the 5 integrated layers:
  1. POST /api/ai/parse-search-query (Ollama LLM structured parsing & fallback).
  2. POST /api/search/companies (faceted company search with live facets).
  3. POST /api/search/people (decision-maker search with deliverability).
  4. POST /api/prospecting/push-onereach (outbound webhook delivery with HMAC).
  5. GET /api/prospecting/company/{org_id}/decision-makers (linked executives).
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from packages.api.dependencies import UserPrincipal, get_current_user
from packages.api.main import create_app
from packages.infrastructure.ollama_client import ollama_client


class TestAiProspectingSearch(unittest.TestCase):
    """Test suite for AI Prospecting Search & Faceted Filter Workspace."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.dependency_overrides[get_current_user] = lambda: UserPrincipal(
            id="test-prospecting-user",
            email="prospector@dataextraction.test",
            name="Prospecting Architect",
            is_admin=True,
        )
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.app.dependency_overrides.clear()

    # ── Test Layer 1: AI Query Parsing (Ollama & Fallback) ─────────────────

    @patch.object(ollama_client, "is_available", return_value=True)
    @patch.object(ollama_client, "generate_structured", new_callable=AsyncMock)
    def test_parse_search_query_company_mode_ollama(self, mock_generate, mock_avail):
        """Verifies company query parsing with Ollama structured generation."""
        mock_generate.return_value = {
            "states": ["TX"],
            "industries": ["Homecare"],
            "technologies": ["Salesforce"],
            "compliance": ["SOC 2"],
            "intent_strength": "HIGH",
            "summary": "Filtering for SOC 2 compliant Homecare agencies in Texas.",
        }

        resp = self.client.post(
            "/api/ai/parse-search-query",
            json={"query": "Find SOC 2 compliant homecare agencies in Texas", "mode": "company"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "company")
        self.assertEqual(data["source"], "ollama")
        self.assertIn("TX", data["filters"].get("states", []))
        self.assertIn("Homecare", data["filters"].get("industries", []))
        self.assertIn("SOC 2", data["filters"].get("compliance", []))
        self.assertIn("SOC 2", data["summary"])

    @patch.object(ollama_client, "is_available", return_value=False)
    def test_parse_search_query_company_mode_fallback(self, mock_avail):
        """Verifies deterministic regex fallback when Ollama is offline."""
        resp = self.client.post(
            "/api/ai/parse-search-query",
            json={
                "query": "Find SOC 2 compliant homecare agencies in Texas using Salesforce",
                "mode": "company",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "company")
        self.assertEqual(data["source"], "fallback")
        self.assertIn("TX", data["filters"]["states"])
        self.assertIn("Salesforce", data["filters"]["technologies"])
        self.assertIn("SOC 2", data["filters"]["compliance"])
        self.assertTrue("TX" in data["summary"] or "Texas" in data["summary"])

    @patch.object(ollama_client, "is_available", return_value=False)
    def test_parse_search_query_people_mode_fallback(self, mock_avail):
        """Verifies deterministic regex fallback for decision-maker prospecting."""
        resp = self.client.post(
            "/api/ai/parse-search-query",
            json={
                "query": "Show C-suite and VPs of Engineering at tech companies in California with verified email",
                "mode": "people",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["mode"], "people")
        self.assertEqual(data["source"], "fallback")
        self.assertIn("C_SUITE", data["filters"]["seniority_levels"])
        self.assertIn("VP", data["filters"]["seniority_levels"])
        self.assertIn("ENGINEERING_TECH", data["filters"]["departments"])
        self.assertIn("CA", data["filters"]["states"])
        self.assertTrue(data["filters"]["verified_email_only"])

    # ── Test Layer 2: Company Search & Live Facets ─────────────────────────

    def test_search_companies_database_query(self):
        """Verifies faceted company search returning real records and dynamic facets."""
        resp = self.client.post(
            "/api/search/companies",
            json={
                "query": "care",
                "states": ["TX", "CA"],
                "headcount_ranges": ["11-50", "51-200"],
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total", data)
        self.assertIn("results", data)
        self.assertIn("facets", data)
        self.assertIn("states", data["facets"])
        self.assertIn("industries", data["facets"])
        self.assertIn("technologies", data["facets"])
        self.assertIn("intent_strengths", data["facets"])

        # Check format of returned results
        if data["results"]:
            item = data["results"][0]
            self.assertIn("org_id", item)
            self.assertIn("legal_name", item)
            self.assertIn("primary_domain", item)
            self.assertIn("trust_score", item)
            self.assertIn("intent_score", item)

    # ── Test Layer 3: People Search & Deliverability ───────────────────────

    def test_search_people_database_query(self):
        """Verifies decision-maker search joining persons, organizations, and emails."""
        resp = self.client.post(
            "/api/search/people",
            json={
                "seniority_levels": ["C_SUITE", "VP"],
                "email_statuses": ["VERIFIED"],
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("total", data)
        self.assertIn("results", data)
        self.assertIn("facets", data)
        self.assertIn("seniority_levels", data["facets"])
        self.assertIn("departments", data["facets"])

        if data["results"]:
            person = data["results"][0]
            self.assertIn("person_id", person)
            self.assertIn("full_name", person)
            self.assertIn("title", person)
            self.assertIn("seniority_level", person)
            self.assertIn("email", person)
            self.assertIn("deliverability_status", person)
            self.assertIn("deliverability_score", person)

    # ── Test Layer 4: OneReach Outbound Delivery ───────────────────────────

    @patch("packages.domain.onereach_delivery_service.OneReachDeliveryService.dispatch_payload")
    def test_push_to_onereach_success(self, mock_dispatch):
        """Verifies signed batch dispatch of selected prospects to OneReach."""
        mock_dispatch.return_value = {
            "status": "DELIVERED",
            "delivery_id": "test-deliv-uuid-1234",
            "http_status": 200,
            "attempts": 1,
            "signature": "mocked-sha256-sig",
        }

        resp = self.client.post(
            "/api/prospecting/push-onereach",
            json={
                "entity_type": "company",
                "ids": ["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"],
                "campaign_id": "q4-homecare-blitz",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "DELIVERED")
        self.assertEqual(data["record_count"], 2)
        self.assertEqual(data["delivery_id"], "test-deliv-uuid-1234")

    # ── Test Layer 5: Company Decision-Makers for Drawer ───────────────────

    def test_get_company_decision_makers(self):
        """Verifies lookup of executive leadership for slide-over detail drawer."""
        resp = self.client.get("/api/prospecting/company/00000000-0000-0000-0000-000000000001/decision-makers")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("org_id", data)
        self.assertIn("decision_makers", data)
        self.assertIsInstance(data["decision_makers"], list)


if __name__ == "__main__":
    unittest.main()
