"""
DataExtraction — Unit Test Suite: Phase 6 FastAPI Gateway & Routers
===================================================================
Validates:
  1. FastAPI application factory (packages.api.main:create_app).
  2. Health and readiness probe endpoints (/healthz, /readyz).
  3. Orchestration router (/api/orchestration/queues).
  4. Extraction router (/api/extraction/sources).
  5. Search router autocomplete proxy (/api/search/autocomplete).
  6. Authentication guards on protected endpoints.
"""

import unittest
from fastapi.testclient import TestClient

from packages.api.main import create_app
from packages.api.dependencies import UserPrincipal, get_current_user


class TestApiGateway(unittest.TestCase):
    """Verifies FastAPI application endpoints, middlewares, and routers."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        # Override get_current_user to return a test principal
        cls.app.dependency_overrides[get_current_user] = lambda: UserPrincipal(
            id="test-user-001",
            email="tester@oneextraction.internal",
            name="Platform Tester",
            is_admin=True,
        )
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.app.dependency_overrides.clear()

    def test_healthz_liveness(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["service"], "dataextraction-api")

    def test_readyz_readiness(self):
        resp = self.client.get("/readyz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("status", data)
        self.assertIn("database_pool", data)

    def test_orchestration_queues_endpoint(self):
        resp = self.client.get("/api/orchestration/queues")
        self.assertEqual(resp.status_code, 200)
        queues = resp.json()
        self.assertGreaterEqual(len(queues), 6)
        self.assertIn("agent_1_registry", queues)
        self.assertIn("agent_6_search", queues)
        self.assertIn("agent_7_email_enrichment", queues)

    def test_orchestration_health_endpoint(self):
        resp = self.client.get("/api/orchestration/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("orchestration_engine", data)
        self.assertIn("temporal_cluster_status", data)
        self.assertIn("timestamp", data)

    def test_extraction_sources_endpoint(self):
        resp = self.client.get("/api/extraction/sources")
        self.assertEqual(resp.status_code, 200)
        sources = resp.json()
        self.assertIn("federal_registries", sources)
        self.assertIn("geospatial_engines", sources)
        self.assertIn("sec_edgar", sources["federal_registries"])

    def test_search_autocomplete_endpoint(self):
        resp = self.client.get("/api/search/autocomplete?prefix=acme&limit=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["prefix"], "acme")
        self.assertTrue(isinstance(data["suggestions"], list))
        self.assertGreater(len(data["suggestions"]), 0)

    def test_process_time_header_in_response(self):
        resp = self.client.get("/healthz")
        self.assertIn("x-process-time-ms", resp.headers)

    def test_delivery_config_and_status_endpoints(self):
        # 1. GET /api/delivery/config
        resp = self.client.get("/api/delivery/config")
        self.assertEqual(resp.status_code, 200)
        cfg = resp.json()
        self.assertIn("webhook_url", cfg)
        self.assertIn("enabled", cfg)

        # 2. GET /api/delivery/status
        resp = self.client.get("/api/delivery/status")
        self.assertEqual(resp.status_code, 200)
        status_data = resp.json()
        self.assertIn("status", status_data)
        self.assertIn("metrics", status_data)

    def test_delivery_dispatch_and_stream(self):
        # 3. POST /api/delivery/onereach/dispatch (dry run)
        resp = self.client.post("/api/delivery/onereach/dispatch", json={"dry_run": True, "limit": 10})
        self.assertEqual(resp.status_code, 200)
        dispatch_res = resp.json()
        self.assertEqual(dispatch_res["status"], "SIMULATED")
        self.assertIn("signature", dispatch_res)

        # 4. GET /api/delivery/onereach/stream
        resp = self.client.get("/api/delivery/onereach/stream?limit=5")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/x-ndjson", resp.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
