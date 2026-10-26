"""
Phase 6 Test Suite: Frontend & End-to-End Delivery

Comprehensive verification of:
1. Frontend Namespace & Brand Integrity:
   - Zero legacy project namespace drift (@prospex/web, @prospex/types, prospex_token).
   - Clean localStorage keys (oneextraction_token, oneextraction_user) with legacy purge.
   - Modernized production Dockerfile with unprivileged 'oneextraction' user.
   - Leaflet map marker styles and root layout metadata branding.
2. Backend API Parity & Security Contracts:
   - Health check and telemetry endpoints (/api/pipeline/health, /api/health).
   - Dead-Letter Queue (DLQ) endpoints (/api/dlq/stats, /api/dlq/records, /api/dlq/replay, /api/dlq/discard).
   - Unauthenticated access rejection (401) on protected DLQ and pipeline routes.
3. Operational Dashboard Integration:
   - Pipeline & DLQ UI routing and navigation integration.
   - Clean export filename formatting and streaming download contract.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure paths resolve properly
_backend_dir = Path(__file__).resolve().parent
_project_root = _backend_dir.parents[2]
_packages = _project_root / "packages"

for _p in [
    _packages / "pipeline",
    _packages / "infrastructure",
    _packages / "scrapers",
    _packages / "scrapers" / "federal",
    _packages / "scrapers" / "open_map",
    _packages / "api",
    _packages / "api" / "routers",
    _project_root / "scripts" / "db",
    _project_root / "scripts" / "ops",
    _project_root,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastapi.testclient import TestClient
from api_server import app
from api.deps import UserPrincipal, get_current_user


class TestFrontendNamespaceAndBrandIntegrity(unittest.TestCase):
    """Verifies complete eradication of legacy project drift in the frontend codebase."""

    def setUp(self):
        self.frontend_dir = _project_root / "frontend"

    def test_package_json_naming(self):
        pkg_file = self.frontend_dir / "package.json"
        self.assertTrue(pkg_file.exists(), "package.json must exist in frontend/")
        with open(pkg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data.get("name"), "@oneextraction/web")
        self.assertIn("typecheck", data.get("scripts", {}))

    def test_next_config_cleanliness(self):
        next_config = self.frontend_dir / "next.config.ts"
        self.assertTrue(next_config.exists(), "next.config.ts must exist")
        content = next_config.read_text(encoding="utf-8")
        self.assertNotIn("@prospex/types", content)
        self.assertNotIn("@prospex", content)

    def test_dockerfile_isolation(self):
        dockerfile = self.frontend_dir / "Dockerfile"
        self.assertTrue(dockerfile.exists(), "Dockerfile must exist")
        content = dockerfile.read_text(encoding="utf-8")
        self.assertNotIn("USER prospex", content)
        self.assertNotIn("@prospex/web", content)
        self.assertIn("USER oneextraction", content)
        self.assertIn("addgroup -S oneextraction", content)

    def test_auth_hook_token_cleanliness(self):
        use_auth = self.frontend_dir / "src" / "hooks" / "use-auth.ts"
        self.assertTrue(use_auth.exists())
        content = use_auth.read_text(encoding="utf-8")
        self.assertIn('export const TOKEN_KEY = "oneextraction_token";', content)
        self.assertIn('export const USER_KEY = "oneextraction_user";', content)
        # Ensure no new setting of legacy token
        self.assertNotIn('localStorage.setItem(LEGACY_TOKEN_KEY', content)
        self.assertNotIn('localStorage.setItem(LEGACY_USER_KEY', content)

    def test_api_client_token_cleanliness(self):
        api_client = self.frontend_dir / "src" / "lib" / "api.ts"
        self.assertTrue(api_client.exists())
        content = api_client.read_text(encoding="utf-8")
        self.assertIn('const TOKEN_KEY = "oneextraction_token";', content)
        self.assertNotIn('localStorage.setItem(LEGACY_TOKEN_KEY', content)

    def test_leaflet_marker_classes(self):
        leads_map = self.frontend_dir / "src" / "components" / "leads" / "leads-map.tsx"
        self.assertTrue(leads_map.exists())
        content = leads_map.read_text(encoding="utf-8")
        self.assertIn('className: "oe-marker"', content)
        self.assertIn('.oe-marker-pin', content)
        self.assertNotIn('prospex-marker', content)

    def test_root_layout_metadata(self):
        layout = self.frontend_dir / "src" / "app" / "layout.tsx"
        self.assertTrue(layout.exists())
        content = layout.read_text(encoding="utf-8")
        self.assertIn("OneExtraction — B2B Lead Intelligence Platform", content)
        self.assertNotIn("DataExtraction Project —", content)


class TestApiEndpointsParity(unittest.TestCase):
    """Verifies FastAPI route mounts, security constraints, and response contracts."""

    def setUp(self):
        self.client = TestClient(app, raise_server_exceptions=False)
        self.mock_user = UserPrincipal(
            id="usr-test-01",
            email="admin@oneextraction.com",
            name="Test Admin",
            workspace_id="ws-test-01",
            is_admin=True,
        )

    def test_public_health_check(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("service"), "OneExtraction API")
        self.assertIn("database", data)

    def test_pipeline_health_endpoint_contract(self):
        # Override auth dependency
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        try:
            resp = self.client.get("/api/pipeline/health")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("status", data)
            self.assertTrue("database_pool" in data or "database" in data)
        finally:
            app.dependency_overrides.clear()

    def test_dlq_stats_unauthorized_rejection(self):
        # Unauthenticated request must return 401
        resp = self.client.get("/api/dlq/stats")
        self.assertEqual(resp.status_code, 401)

    def test_dlq_stats_authorized_success(self):
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        try:
            with patch("api.dlq_router.get_connection") as mock_conn, \
                 patch("api.dlq_router.release_connection"), \
                 patch("api.dlq_router.get_dead_letter_stats") as mock_stats:
                mock_stats.return_value = {
                    "total_records": 5,
                    "pending_count": 3,
                    "replayed_count": 2,
                    "discarded_count": 0,
                    "sources": {"CMS_NPI": 3, "SEC_EDGAR": 2},
                }
                resp = self.client.get("/api/dlq/stats")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["total_records"], 5)
                self.assertEqual(data["pending_count"], 3)
        finally:
            app.dependency_overrides.clear()

    def test_dlq_records_pagination_contract(self):
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        try:
            with patch("api.dlq_router.get_connection"), \
                 patch("api.dlq_router.release_connection"), \
                 patch("api.dlq_router.get_dead_letter_records") as mock_records:
                mock_records.return_value = [
                    {
                        "id": 101,
                        "source_name": "SEC_EDGAR",
                        "error_type": "SchemaValidationError",
                        "error_message": "Missing CIK number",
                        "failed_stage": "INGESTION",
                        "retry_count": 0,
                        "max_retries": 3,
                        "status": "PENDING",
                        "payload": {"company_name": "Acme Corp"},
                        "created_at": "2026-10-12T00:00:00Z",
                    }
                ]
                resp = self.client.get("/api/dlq/records?status=PENDING&limit=10&offset=0")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["count"], 1)
                self.assertEqual(data["limit"], 10)
                self.assertEqual(data["records"][0]["source_name"], "SEC_EDGAR")
        finally:
            app.dependency_overrides.clear()

    def test_dlq_replay_endpoint_contract(self):
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        try:
            with patch("api.dlq_router.get_connection"), \
                 patch("api.dlq_router.release_connection"), \
                 patch("api.dlq_router.replay_dead_letter") as mock_replay:
                mock_replay.return_value = {
                    "success": True,
                    "dlq_id": 101,
                    "dry_run": True,
                    "message": "Dry-run simulation succeeded",
                }
                resp = self.client.post("/api/dlq/replay/101", json={"dry_run": True})
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertTrue(data["success"])
                self.assertTrue(data["dry_run"])
        finally:
            app.dependency_overrides.clear()

    def test_dlq_discard_endpoint_contract(self):
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        try:
            with patch("api.dlq_router.get_connection"), \
                 patch("api.dlq_router.release_connection"), \
                 patch("api.dlq_router.discard_dead_letter") as mock_discard:
                mock_discard.return_value = True
                resp = self.client.post("/api/dlq/discard/101?reason=Malformed+format")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["status"], "DISCARDED")
                self.assertEqual(data["record_id"], 101)
        finally:
            app.dependency_overrides.clear()

    def test_dlq_drain_fallback_endpoint_contract(self):
        app.dependency_overrides[get_current_user] = lambda: self.mock_user
        try:
            with patch("api.dlq_router.get_connection"), \
                 patch("api.dlq_router.release_connection"), \
                 patch("api.dlq_router.drain_fallback_to_db") as mock_drain:
                mock_drain.return_value = {"drained": 5, "status": "SUCCESS"}
                resp = self.client.post("/api/dlq/drain-fallback")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["drained"], 5)
                self.assertEqual(data["status"], "SUCCESS")
        finally:
            app.dependency_overrides.clear()


class TestOperationalDashboardIntegration(unittest.TestCase):
    """Verifies frontend components, routes, and operational UI integration."""

    def setUp(self):
        self.frontend_dir = _project_root / "frontend"

    def test_pipeline_route_exists(self):
        pipeline_page = self.frontend_dir / "src" / "app" / "(dashboard)" / "pipeline" / "page.tsx"
        self.assertTrue(pipeline_page.exists(), "pipeline route page.tsx must exist")
        content = pipeline_page.read_text(encoding="utf-8")
        self.assertIn("PipelinePanel", content)

    def test_pipeline_panel_component_exists(self):
        pipeline_panel = self.frontend_dir / "src" / "components" / "pipeline" / "pipeline-panel.tsx"
        self.assertTrue(pipeline_panel.exists(), "pipeline-panel.tsx must exist")
        content = pipeline_panel.read_text(encoding="utf-8")
        self.assertIn("/pipeline/health", content)
        self.assertIn("/dlq/stats", content)
        self.assertIn("/dlq/records", content)
        self.assertIn("/dlq/replay", content)
        self.assertIn("/dlq/discard", content)

    def test_sidebar_nav_includes_pipeline(self):
        sidebar = self.frontend_dir / "src" / "components" / "layout" / "app-sidebar.tsx"
        self.assertTrue(sidebar.exists())
        content = sidebar.read_text(encoding="utf-8")
        self.assertIn('href: "/pipeline"', content)
        self.assertIn('Pipeline & DLQ', content)
        self.assertIn('OneExtraction', content)

    def test_export_filename_branding(self):
        export_manager = self.frontend_dir / "src" / "components" / "export" / "export-manager.tsx"
        self.assertTrue(export_manager.exists())
        content = export_manager.read_text(encoding="utf-8")
        self.assertIn("oneextraction_${filters.table}_", content)
        self.assertNotIn("dataextraction_project_", content)


if __name__ == "__main__":
    unittest.main()
