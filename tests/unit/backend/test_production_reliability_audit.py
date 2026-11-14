"""
Production Reliability Audit Verification Suite
================================================
Validates all enterprise hardening fixes:
1. Temporal Worker 1 registers MasterOrchestrator.
2. Temporal activities use non-blocking asyncio.to_thread wrappers.
3. Map Extraction router is fully mounted in the API gateway.
4. Duplicates router handles SQL views cleanly without TABLESAMPLE syntax.
5. All 7 workers configure canonical task queues and workflows.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestProductionReliabilityAudit(unittest.TestCase):

    def test_worker_registry_registers_master_orchestrator(self):
        """Worker 1 must register MasterOrchestrator on registry-ingestion-queue."""
        worker_file = REPO_ROOT / "packages" / "temporal" / "workers" / "worker_registry.py"
        content = worker_file.read_text(encoding="utf-8")
        self.assertIn("MasterOrchestrator", content)
        self.assertIn("from packages.temporal.workflows.master_orchestrator import MasterOrchestrator", content)

    def test_federal_activities_use_asyncio_thread(self):
        """Federal scraper subprocesses must run via asyncio.to_thread to avoid blocking event loop."""
        activities_file = REPO_ROOT / "packages" / "temporal" / "activities" / "federal_activities.py"
        content = activities_file.read_text(encoding="utf-8")
        self.assertIn("await asyncio.to_thread(_run_scraper, \"fetch_cms_npi.py\"", content)
        self.assertIn("await asyncio.to_thread(_run_scraper, \"fetch_sec_edgar.py\"", content)
        self.assertIn("await asyncio.to_thread(_run_scraper, \"fetch_fdic.py\"", content)
        self.assertIn("await asyncio.to_thread(_run_scraper, \"fetch_usaspending.py\"", content)
        self.assertIn("await asyncio.to_thread(_run_scraper, \"fetch_propublica.py\"", content)
        self.assertIn("await asyncio.to_thread(_run_scraper, \"fetch_sam_gov.py\"", content)

    def test_duplicates_router_no_tablesample(self):
        """Duplicates router must not use TABLESAMPLE since us_leads is a PostgreSQL view."""
        dup_file = REPO_ROOT / "packages" / "api" / "routers" / "duplicates_router.py"
        content = dup_file.read_text(encoding="utf-8")
        self.assertNotIn("TABLESAMPLE", content)
        self.assertIn("random() < 0.05", content)

    def test_map_extraction_router_mounted_in_gateway(self):
        """API gateway must mount map_extraction_router with endpoints."""
        from packages.api.main import create_app
        app = create_app()
        paths = app.openapi()["paths"]
        self.assertIn("/api/map-extraction/states", paths)
        self.assertIn("/api/map-extraction/fields", paths)
        self.assertIn("/api/map-extraction/status", paths)
        self.assertIn("/api/map-extraction/mirrors", paths)
        self.assertIn("/api/map-extraction/config", paths)

    def test_all_seven_workers_configured(self):
        """Audit all 7 worker files for queue declarations."""
        workers_dir = REPO_ROOT / "packages" / "temporal" / "workers"
        worker_files = [
            "worker_registry.py",
            "worker_geospatial.py",
            "worker_identity.py",
            "worker_email_enrichment.py",
            "worker_executive.py",
            "worker_governance.py",
            "worker_search.py",
        ]
        for wf_name in worker_files:
            p = workers_dir / wf_name
            self.assertTrue(p.exists(), f"Worker {wf_name} missing")
            content = p.read_text(encoding="utf-8")
            self.assertIn("TASK_QUEUE", content)
            self.assertIn("Worker(", content)

    def test_master_orchestrator_forwards_config_to_all_phases(self):
        """MasterOrchestrator must forward data_count and parameters to all child phases."""
        wf_file = REPO_ROOT / "packages" / "temporal" / "workflows" / "master_orchestrator.py"
        content = wf_file.read_text(encoding="utf-8")
        self.assertIn('a1_cfg["sources"] = config["sources"]', content)
        self.assertIn('a1_cfg["data_count"] = config["data_count"]', content)
        self.assertIn('a2_cfg["data_count"] = config["data_count"]', content)
        self.assertIn('a3_cfg["data_count"] = config["data_count"]', content)
        self.assertIn('a4_cfg["data_count"] = config["data_count"]', content)
        self.assertIn('a5_cfg["data_count"] = config["data_count"]', content)
        self.assertIn('a6_cfg["data_count"] = config["data_count"]', content)
        self.assertIn('a7_cfg["data_count"] = config["data_count"]', content)

    def test_export_router_mounted_and_handles_onereach(self):
        """Export router must be mounted and define CSV, JSON, and OneReach export endpoints."""
        from packages.api.main import create_app
        app = create_app()
        paths = app.openapi()["paths"]
        self.assertIn("/api/export/leads", paths)
        self.assertIn("/api/export/onereach", paths)

    def test_active_status_endpoint_and_normalization(self):
        """Orchestration router must expose /active/status and normalize status for the UI."""
        from packages.api.main import create_app
        from packages.api.routers.orchestration_router import _normalize_saga_status_for_ui
        app = create_app()
        paths = app.openapi()["paths"]
        self.assertIn("/api/orchestration/active/status", paths)

        # Test normalization
        raw = {
            "workflow_id": "test-123",
            "phase": "REGISTRY_INGESTION",
            "status": "RUNNING",
            "metrics": {"organizations_processed": 1500},
            "logs": [{"timestamp": "12:00:00", "agent": "AGENT 1", "message": "Harvesting", "type": "info"}],
        }
        normalized = _normalize_saga_status_for_ui(raw)
        self.assertEqual(normalized["current_stage"], "REGISTRY_INGESTION")
        self.assertEqual(normalized["current_agent"], "Agent 1 (Registry Harvester)")
        self.assertEqual(normalized["records_processed"], 1500)
        self.assertIn("REGISTRY_INGESTION", normalized["stages"])
        self.assertEqual(normalized["stages"]["REGISTRY_INGESTION"]["status"], "RUNNING")
        self.assertEqual(normalized["log"]["message"], "Harvesting")

    def test_now_ts_is_valid_iso_format(self):
        """now_ts must return valid ISO 8601 string to prevent 'Invalid Date' in UI."""
        from datetime import datetime
        from packages.api.routers.orchestration_router import now_ts
        ts = now_ts()
        dt = datetime.fromisoformat(ts)
        self.assertIsNotNone(dt.tzinfo)

    def test_dynamic_duration_not_hardcoded_to_one(self):
        """_normalize_saga_status_for_ui must not hardcode duration_seconds to 1."""
        from packages.api.routers.orchestration_router import _normalize_saga_status_for_ui
        raw = {
            "workflow_id": "test-dur",
            "phase": "REGISTRY_INGESTION",
            "status": "RUNNING",
            "results": {
                "REGISTRY_INGESTION": {"status": "COMPLETED", "duration_seconds": 42.5}
            },
            "started_at": 100.0,
        }
        normalized = _normalize_saga_status_for_ui(raw)
        stage_dur = normalized["stages"]["REGISTRY_INGESTION"]["duration_seconds"]
        self.assertEqual(stage_dur, 42.5)

    def test_orchestration_start_returns_503_when_temporal_offline(self):
        """POST /api/orchestration/start must reject with HTTP 503 if Temporal is offline."""
        import asyncio
        from unittest.mock import patch
        from fastapi import HTTPException
        from packages.api.routers.orchestration_router import start_master_saga, StartSagaRequest
        from packages.api.dependencies import UserPrincipal
        from packages.temporal.client import reset_temporal_client
        reset_temporal_client()

        test_principal = UserPrincipal(id="admin-001", email="admin@dataextraction.com", name="Admin", is_admin=True)
        req = StartSagaRequest(data_count=100)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            with patch("packages.api.routers.orchestration_router.get_temporal_client", side_effect=RuntimeError("Temporal server unreachable")):
                with self.assertRaises(HTTPException) as ctx:
                    loop.run_until_complete(start_master_saga(req, current_user=test_principal))
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertEqual(ctx.exception.detail["error"], "TEMPORAL_CLUSTER_UNAVAILABLE")
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_temporal_server_and_workers_supervisor_scripts(self):
        """Operations supervisor scripts must exist and cover all 7 agent workers."""
        server_script = REPO_ROOT / "scripts" / "ops" / "start_temporal_server.py"
        worker_script = REPO_ROOT / "scripts" / "ops" / "start_all_workers.py"
        self.assertTrue(server_script.exists(), "start_temporal_server.py missing")
        self.assertTrue(worker_script.exists(), "start_all_workers.py missing")

        content = worker_script.read_text(encoding="utf-8")
        self.assertIn("worker-1-registry", content)
        self.assertIn("worker-2-geospatial", content)
        self.assertIn("worker-3-identity", content)
        self.assertIn("worker-7-email", content)
        self.assertIn("worker-4-executive", content)
        self.assertIn("worker-5-governance", content)
        self.assertIn("worker-6-search", content)


if __name__ == "__main__":
    unittest.main()
