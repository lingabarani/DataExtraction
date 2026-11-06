"""
DataExtraction — Unit Test Suite: Phase 10 (Email Enrichment API Gateway & Scheduler)
=====================================================================================
Validates:
  1. API Gateway endpoints for email discovery and verification:
     - POST /api/enrichment/email/jobs (202 Accepted, admin guard)
     - GET  /api/enrichment/email/jobs/{job_id} (200 OK / 404 Not Found)
     - GET  /api/enrichment/email/jobs (200 OK, paginated list)
     - GET  /api/enrichment/email/audit/{company_id} (200 OK, probe traces)
     - GET  /api/enrichment/email/results/{company_id} (200 OK / 404 Not Found)
     - POST /api/enrichment/email/probe-single (200 OK, live crawl & SMTP probe)
  2. Native Temporal Scheduler configuration and registration:
     - config/schedules.yaml specification
     - register_schedules.py workflow and queue mappings
     - create_schedule mock execution
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from packages.api.main import create_app
from packages.api.dependencies import UserPrincipal, get_current_user, require_admin
from packages.domain.email_enricher import EnrichmentResult
from packages.temporal.config import QUEUE_EMAIL_ENRICHMENT
from packages.temporal.schedules.register_schedules import (
    CONFIG_PATH,
    TASK_QUEUE_MAP,
    WORKFLOW_MAP,
    register_schedules,
)


class TestEmailEnrichmentApi(unittest.TestCase):
    """Tests FastAPI router endpoints for email enrichment jobs, results, audit, and probes."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.admin_user = UserPrincipal(
            id="admin-user-001",
            email="admin@dataextraction.enterprise",
            name="Admin Tester",
            is_admin=True,
        )
        cls.app.dependency_overrides[get_current_user] = lambda: cls.admin_user
        cls.app.dependency_overrides[require_admin] = lambda: cls.admin_user
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.app.dependency_overrides.clear()

    @patch("packages.api.routers.enrichment_router.get_temporal_client")
    def test_trigger_email_enrichment_job_success(self, mock_get_client):
        mock_client = AsyncMock()
        mock_handle = MagicMock()
        mock_handle.id = "wf-email-enrich-12345"
        mock_handle.result_run_id = "run-uuid-abcde"
        mock_client.start_workflow.return_value = mock_handle
        mock_get_client.return_value = mock_client

        payload = {
            "batch_size": 150,
            "max_records": 1000,
            "probe_smtp": True,
            "target_table": "companies",
        }
        resp = self.client.post("/api/enrichment/email/jobs", json=payload)
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertEqual(data["status"], "ACCEPTED")
        self.assertEqual(data["workflow_id"], "wf-email-enrich-12345")
        self.assertEqual(data["run_id"], "run-uuid-abcde")
        self.assertEqual(data["task_queue"], QUEUE_EMAIL_ENRICHMENT)

    @patch("packages.infrastructure.email_enrichment_repository.email_enrichment_repo.get_job_by_id")
    def test_get_email_enrichment_job_found(self, mock_get_job):
        mock_get_job.return_value = {
            "id": "job-uuid-999",
            "job_type": "POST_DEDUP_CANONICAL",
            "status": "RUNNING",
            "target_table": "companies",
            "batch_size": 200,
            "max_concurrency": 50,
            "total_records": 500,
            "processed_records": 100,
            "successful_discoveries": 85,
            "failed_records": 15,
            "last_processed_id": "c-100",
            "started_at": "2026-10-29T03:00:00Z",
            "completed_at": None,
            "error_message": None,
            "metadata": {},
        }
        resp = self.client.get("/api/enrichment/email/jobs/job-uuid-999")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], "job-uuid-999")
        self.assertEqual(data["status"], "RUNNING")
        self.assertEqual(data["successful_discoveries"], 85)

    @patch("packages.infrastructure.email_enrichment_repository.email_enrichment_repo.get_job_by_id")
    def test_get_email_enrichment_job_not_found(self, mock_get_job):
        mock_get_job.return_value = None
        resp = self.client.get("/api/enrichment/email/jobs/nonexistent-id")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json()["detail"].lower())

    @patch("packages.infrastructure.email_enrichment_repository.email_enrichment_repo.get_recent_jobs")
    def test_list_email_enrichment_jobs(self, mock_get_recent):
        mock_get_recent.return_value = [
            {
                "id": "job-1",
                "job_type": "POST_DEDUP_CANONICAL",
                "status": "COMPLETED",
                "target_table": "companies",
                "batch_size": 200,
                "processed_records": 200,
                "successful_discoveries": 180,
                "failed_records": 20,
                "started_at": "2026-10-29T02:00:00Z",
                "completed_at": "2026-10-29T02:15:00Z",
                "error_message": None,
            }
        ]
        resp = self.client.get("/api/enrichment/email/jobs?limit=10&offset=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "job-1")

    @patch("packages.infrastructure.email_enrichment_repository.email_enrichment_repo.get_audit_for_company")
    def test_get_email_discovery_audit(self, mock_audit):
        mock_audit.return_value = [
            {
                "id": 1,
                "job_id": "job-1",
                "company_id": "comp-123",
                "target_domain": "acme.com",
                "probed_email": "contact@acme.com",
                "probe_type": "BATCH_DISCOVERY",
                "mx_host": "mail.acme.com",
                "smtp_code": 250,
                "smtp_response": "2.1.5 Recipient OK",
                "duration_ms": 45.2,
                "is_success": True,
                "error_trace": None,
                "created_at": "2026-10-29T03:05:00Z",
            }
        ]
        resp = self.client.get("/api/enrichment/email/audit/comp-123")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["target_domain"], "acme.com")
        self.assertTrue(data[0]["is_success"])

    @patch("packages.infrastructure.email_enrichment_repository.email_enrichment_repo.get_enrichment_result_by_company_id")
    def test_get_email_enrichment_result_found(self, mock_res):
        mock_res.return_value = {
            "id": "res-1",
            "job_id": "job-1",
            "company_id": "comp-123",
            "domain": "acme.com",
            "primary_email": "info@acme.com",
            "all_emails": ["info@acme.com", "sales@acme.com"],
            "discovery_source": "WEB_CRAWLER",
            "deliverability_status": "DELIVERABLE",
            "confidence_score": 0.94,
            "is_catchall": False,
            "tech_stack": ["wordpress", "cloudflare"],
            "cms_detected": "wordpress",
            "ssl_valid": True,
            "site_speed_ms": 110,
            "http_status_code": 200,
            "updated_at": "2026-10-29T03:06:00Z",
        }
        resp = self.client.get("/api/enrichment/email/results/comp-123")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["primary_email"], "info@acme.com")
        self.assertEqual(data["deliverability_status"], "DELIVERABLE")
        self.assertEqual(data["confidence_score"], 0.94)

    @patch("packages.infrastructure.email_enrichment_repository.email_enrichment_repo.get_enrichment_result_by_company_id")
    def test_get_email_enrichment_result_not_found(self, mock_res):
        mock_res.return_value = None
        resp = self.client.get("/api/enrichment/email/results/missing-company")
        self.assertEqual(resp.status_code, 404)

    @patch("packages.api.routers.enrichment_router.AsyncEmailWebCrawler.crawl_site")
    @patch("packages.api.routers.enrichment_router.email_enrichment_engine.process_discovered_emails")
    def test_probe_single_domain_success(self, mock_process, mock_crawl):
        mock_crawl.return_value = {
            "emails": ["press@tesla.com", "ir@tesla.com"],
            "tech_stack": ["react", "cloudflare"],
            "cms_detected": None,
            "ssl_valid": True,
            "site_speed_ms": 95,
            "http_status_code": 200,
            "domain": "tesla.com",
        }
        mock_process.return_value = EnrichmentResult(
            company_id="probe-tesla.com",
            domain="tesla.com",
            primary_email="ir@tesla.com",
            all_emails=["ir@tesla.com", "press@tesla.com"],
            discovery_source="WEB_CRAWLER",
            deliverability_status="DELIVERABLE",
            confidence_score=0.95,
            is_catchall=False,
            tech_stack=["react", "cloudflare"],
            cms_detected=None,
            ssl_valid=True,
            site_speed_ms=95,
            http_status_code=200,
        )

        payload = {"domain": "tesla.com", "website_url": "https://www.tesla.com", "probe_smtp": True}
        resp = self.client.post("/api/enrichment/email/probe-single", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["domain"], "tesla.com")
        self.assertEqual(data["primary_email"], "ir@tesla.com")
        self.assertEqual(data["deliverability_status"], "DELIVERABLE")
        self.assertEqual(data["confidence_score"], 0.95)
        self.assertIn("react", data["tech_stack"])
        self.assertTrue(data["ssl_valid"])
        self.assertGreaterEqual(data["duration_ms"], 0.0)


class TestEmailEnrichmentScheduler(unittest.IsolatedAsyncioTestCase):
    """Tests Temporal native scheduler configuration, queue bindings, and registration."""

    def test_schedules_yaml_contains_nightly_email_enrichment(self):
        import yaml
        self.assertTrue(CONFIG_PATH.exists(), f"Schedule configuration must exist at {CONFIG_PATH}")
        config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        self.assertIn("schedules", config)
        schedules = config["schedules"]
        self.assertIn("nightly_email_enrichment", schedules)

        sched = schedules["nightly_email_enrichment"]
        self.assertEqual(sched["id"], "nightly-canonical-email-enrichment")
        self.assertEqual(sched["workflow"], "EmailEnrichmentWorkflow")
        self.assertEqual(sched["task_queue"], "email-enrichment-queue")
        self.assertEqual(sched["cron"], "0 3 * * *")
        self.assertEqual(sched["input"]["batch_size"], 500)
        self.assertTrue(sched["input"]["probe_smtp"])
        self.assertTrue(sched["input"]["verify_dedup_completed"])

    def test_workflow_and_task_queue_mappings(self):
        self.assertIn("EmailEnrichmentWorkflow", WORKFLOW_MAP)
        self.assertIn("Agent7EmailEnrichmentWorkflow", WORKFLOW_MAP)
        self.assertEqual(TASK_QUEUE_MAP["EmailEnrichmentWorkflow"], QUEUE_EMAIL_ENRICHMENT)
        self.assertEqual(TASK_QUEUE_MAP["Agent7EmailEnrichmentWorkflow"], QUEUE_EMAIL_ENRICHMENT)

    async def test_register_schedules_registers_email_enrichment(self):
        mock_client = AsyncMock()
        test_config = {
            "schedules": {
                "nightly_email_enrichment": {
                    "id": "nightly-canonical-email-enrichment",
                    "workflow": "EmailEnrichmentWorkflow",
                    "task_queue": QUEUE_EMAIL_ENRICHMENT,
                    "cron": "0 3 * * *",
                    "input": {"batch_size": 500, "probe_smtp": True},
                    "paused": False,
                }
            }
        }

        await register_schedules(mock_client, test_config)
        self.assertEqual(mock_client.create_schedule.call_count, 1)
        args, kwargs = mock_client.create_schedule.call_args
        self.assertEqual(args[0], "nightly-canonical-email-enrichment")
        schedule_obj = args[1]
        self.assertEqual(schedule_obj.spec.cron_expressions, ["0 3 * * *"])
        self.assertEqual(schedule_obj.action.task_queue, QUEUE_EMAIL_ENRICHMENT)


if __name__ == "__main__":
    unittest.main()
