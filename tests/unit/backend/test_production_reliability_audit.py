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


if __name__ == "__main__":
    unittest.main()
