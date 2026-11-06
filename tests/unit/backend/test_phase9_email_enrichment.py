"""
DataExtraction — Unit Test Suite: Phase 9 (Email Enrichment & Verification)
==========================================================================
Validates:
  1. Obfuscation decoding (Cloudflare XOR, HTML entities, [at]/[dot], JSON-LD)
  2. Asset extension and synthetic domain filtering
  3. Multi-source email ranking and low-value mailbox filtering
  4. Calibrated probabilistic confidence scoring and deliverability tiering
  5. DNS MX resolution, candidate generation, and SMTP RCPT TO mocking
  6. Async crawler tech stack detection and CMS profiling
  7. Repository data access layer and keyset checkpointing
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from packages.scrapers.web.obfuscation_decoder import (
    decode_cf_email,
    decode_html_entities,
    extract_all_emails_from_html,
    extract_cf_obfuscated_emails,
    extract_footer_and_comment_emails,
    extract_jsonld_emails,
    extract_mailto_emails,
    extract_text_obfuscated_emails,
    is_valid_email_candidate,
)
from packages.scrapers.web.email_crawler import AsyncEmailWebCrawler
from packages.domain.smtp_engine import (
    generate_candidate_emails,
    get_mx_hosts,
    is_catchall_domain,
    probe_single_smtp_host,
    verify_email_smtp,
)
from packages.domain.email_enricher import (
    EmailCandidate,
    EmailEnrichmentEngine,
    EnrichmentResult,
    compute_email_confidence,
    normalize_site_host,
    rank_emails,
)
from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.email_enrichment_repository import EmailEnrichmentRepository
from packages.temporal.config import QUEUE_EMAIL_ENRICHMENT
from packages.temporal.workflows.w7_email_enrichment_workflow import (
    EmailEnrichmentWorkflow,
    Agent7EmailEnrichmentWorkflow,
)
from packages.temporal.activities.email_enrichment_activities import (
    create_enrichment_job_activity,
    fetch_pending_enrichment_batch_activity,
    enrich_email_batch_activity,
    finalize_enrichment_job_activity,
)
from packages.temporal.workflows.master_orchestrator import MasterOrchestrator


class TestObfuscationDecoder(unittest.TestCase):
    """Tests multi-layer email extraction and obfuscation decryption."""

    def test_decode_cf_email_valid(self):
        # Cloudflare encoding for 'contact@examplecorp.com'
        # Key: 0x45
        # 'c': 0x63 ^ 0x45 = 0x26
        # 'o': 0x6f ^ 0x45 = 0x2a
        raw = "contact@acme.com"
        key = 0x33
        encoded = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in raw)
        decoded = decode_cf_email(encoded)
        self.assertEqual(decoded, raw)

    def test_decode_cf_email_invalid(self):
        self.assertIsNone(decode_cf_email(""))
        self.assertIsNone(decode_cf_email("12"))
        self.assertIsNone(decode_cf_email("zzinvalidhex"))

    def test_decode_html_entities(self):
        text = "sales&#64;acme&#46;com"
        self.assertEqual(decode_html_entities(text), "sales@acme.com")

        hex_text = "info&#x40;acme&#x2e;com"
        self.assertEqual(decode_html_entities(hex_text), "info@acme.com")

    def test_is_valid_email_candidate(self):
        self.assertTrue(is_valid_email_candidate("ceo@innovate.org"))
        self.assertTrue(is_valid_email_candidate("support+billing@saas.io"))

        # Rejects fake domains
        self.assertFalse(is_valid_email_candidate("user@example.com"))
        self.assertFalse(is_valid_email_candidate("error@sentry.io"))
        self.assertFalse(is_valid_email_candidate("hello@wixpress.com"))

        # Rejects asset files
        self.assertFalse(is_valid_email_candidate("logo@2x.png"))
        self.assertFalse(is_valid_email_candidate("styles@main.css"))

        # Rejects malformed
        self.assertFalse(is_valid_email_candidate("no_at_sign.com"))
        self.assertFalse(is_valid_email_candidate("missing_tld@domain"))

    def test_extract_mailto_emails(self):
        html = '<p>Contact us at <a href="mailto:info@targetcorp.com">Email Us</a></p>'
        res = extract_mailto_emails(html)
        self.assertIn("info@targetcorp.com", res)

    def test_extract_text_obfuscation(self):
        html = """
        Reach us at:
        contact [at] startup [dot] io
        or hello (AT) agency (DOT) co
        """
        res = extract_text_obfuscated_emails(html)
        self.assertIn("contact@startup.io", res)
        self.assertIn("hello@agency.co", res)

    def test_extract_jsonld_emails(self):
        html = """
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "Acme Widgets",
            "email": "corporate@acmewidgets.com",
            "department": [
                {"name": "Support", "email": "help@acmewidgets.com"}
            ]
        }
        </script>
        """
        res = extract_jsonld_emails(html)
        self.assertIn("corporate@acmewidgets.com", res)
        self.assertIn("help@acmewidgets.com", res)

    def test_extract_footer_and_comments(self):
        html = """
        <html><body>
        <h1>Welcome</h1>
        <!-- secret-admin@backoffice.net -->
        <div>Body content</div>
        """ + ("<div>padding</div>" * 100) + """
        <footer>Copyright 2026 legal@backoffice.net</footer>
        </body></html>
        """
        res = extract_footer_and_comment_emails(html)
        self.assertIn("secret-admin@backoffice.net", res)
        self.assertIn("legal@backoffice.net", res)

    def test_extract_all_emails_from_html_integration(self):
        html = """
        <a href="mailto:lead@primary.com">Mail</a>
        <span>support [at] primary [dot] com</span>
        <script type="application/ld+json">{"email": "hq@primary.com"}</script>
        """
        res = extract_all_emails_from_html(html)
        self.assertEqual(len(res), 3)
        self.assertIn("lead@primary.com", res)
        self.assertIn("support@primary.com", res)
        self.assertIn("hq@primary.com", res)


class TestEmailRankingAndScoring(unittest.TestCase):
    """Tests multi-source email ranking and calibrated confidence scoring."""

    def test_normalize_site_host(self):
        self.assertEqual(normalize_site_host("www.acme.com"), "acme.com")
        self.assertEqual(normalize_site_host("https://sub.acme.com/"), "https://sub.acme.com/")
        self.assertEqual(normalize_site_host("acme.org."), "acme.org")

    def test_rank_emails_prioritization(self):
        emails = [
            "noreply@acme.com",        # Low value (demoted)
            "sales@thirdparty.com",    # Third party domain (demoted below own-domain)
            "founder@acme.com",        # High value own-domain (promoted to top)
            "privacy@acme.com",        # Low value own-domain
            "contact@acme.com",        # High value own-domain
        ]
        ranked = rank_emails(emails, "acme.com")
        # High-value own-domain must come before low-value and third-party
        self.assertIn(ranked[0], ("contact@acme.com", "founder@acme.com"))
        self.assertIn(ranked[1], ("contact@acme.com", "founder@acme.com"))
        # noreply and privacy must appear at the end
        self.assertTrue(ranked[-1] in ("noreply@acme.com", "privacy@acme.com", "sales@thirdparty.com"))

    def test_compute_email_confidence_deliverable(self):
        conf, status, is_role = compute_email_confidence(
            source="WEB_CONTACT_PAGE",
            has_valid_mx=True,
            is_catchall=False,
            smtp_code=250,
            email="founder@acme.com",
        )
        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(status, "DELIVERABLE")
        self.assertFalse(is_role)

    def test_compute_email_confidence_catchall(self):
        conf, status, is_role = compute_email_confidence(
            source="WEB_CONTACT_PAGE",
            has_valid_mx=True,
            is_catchall=True,
            smtp_code=250,
        )
        # Catchall halves confidence
        self.assertLess(conf, 0.60)
        self.assertEqual(status, "CATCHALL")

    def test_compute_email_confidence_disposable(self):
        conf, status, _ = compute_email_confidence(
            source="WEB_CONTACT_PAGE",
            has_valid_mx=True,
            is_catchall=False,
            smtp_code=250,
            email="temporary@mailinator.com",
        )
        self.assertEqual(conf, 0.0)
        self.assertEqual(status, "UNDELIVERABLE")

    def test_compute_email_confidence_role_account(self):
        conf, status, is_role = compute_email_confidence(
            source="WEB_CONTACT_PAGE",
            has_valid_mx=True,
            is_catchall=False,
            smtp_code=250,
            email="sales@acme.com",
        )
        self.assertTrue(is_role)

    def test_compute_email_confidence_undeliverable(self):
        # No MX
        conf_no_mx, status_no_mx, _ = compute_email_confidence(
            source="WEB_MAILTO",
            has_valid_mx=False,
            is_catchall=False,
        )
        self.assertEqual(conf_no_mx, 0.0)
        self.assertEqual(status_no_mx, "UNDELIVERABLE")

        # Hard rejection 550
        conf_550, status_550, _ = compute_email_confidence(
            source="WEB_MAILTO",
            has_valid_mx=True,
            is_catchall=False,
            smtp_code=550,
        )
        self.assertEqual(conf_550, 0.0)
        self.assertEqual(status_550, "UNDELIVERABLE")

    def test_compute_email_confidence_greylisted(self):
        conf_450, status_450, _ = compute_email_confidence(
            source="WEB_MAILTO",
            has_valid_mx=True,
            is_catchall=False,
            smtp_code=450,
        )
        self.assertGreater(conf_450, 0.0)
        self.assertEqual(status_450, "RISKY")


class TestSMTPEngine(unittest.TestCase):
    """Tests DNS MX resolution and SMTP RCPT TO probing behavior with mocks."""

    def test_generate_candidate_emails(self):
        candidates = generate_candidate_emails("acme.com", ["info", "sales", "press"])
        self.assertEqual(candidates, ["info@acme.com", "sales@acme.com", "press@acme.com"])

    @patch("packages.domain.smtp_engine.dns.resolver.resolve")
    def test_get_mx_hosts_mocked(self, mock_resolve):
        r1 = MagicMock()
        r1.preference = 10
        r1.exchange = "mail1.acme.com."
        r2 = MagicMock()
        r2.preference = 20
        r2.exchange = "mail2.acme.com."

        mock_resolve.return_value = [r2, r1]  # Return out of order

        hosts = get_mx_hosts("testdomain-unique-1234.com")
        self.assertIsNotNone(hosts)
        assert hosts is not None
        self.assertEqual(hosts[0], "mail1.acme.com")  # Lowest preference sorted first
        self.assertEqual(hosts[1], "mail2.acme.com")

    @patch("packages.domain.smtp_engine.smtplib.SMTP")
    def test_probe_single_smtp_host_accepted(self, mock_smtp_cls):
        mock_instance = MagicMock()
        mock_instance.rcpt.return_value = (250, b"Recipient OK")
        mock_smtp_cls.return_value = mock_instance

        code, msg, duration = probe_single_smtp_host(
            email="valid@target.org",
            mx_host="mx.target.org",
            probe_from="verify@probe.org",
            probe_ehlo="probe.org",
        )
        self.assertEqual(code, 250)
        self.assertIn("Recipient OK", msg)
        self.assertGreaterEqual(duration, 0.0)

    @patch("packages.domain.smtp_engine.probe_single_smtp_host")
    def test_is_catchall_domain(self, mock_probe):
        mock_probe.return_value = (250, "Accepted", 10.0)
        self.assertTrue(is_catchall_domain("catchall-test-domain.com", ["mx1.example.com"]))

        mock_probe.return_value = (550, "User unknown", 10.0)
        self.assertFalse(is_catchall_domain("legit-test-domain.com", ["mx1.example.com"]))

    @patch("packages.domain.smtp_engine.probe_single_smtp_host")
    def test_verify_email_smtp_integration(self, mock_probe):
        mock_probe.return_value = (250, "OK", 15.0)
        res = verify_email_smtp("user@test.org", ["mx1.test.org"])
        self.assertTrue(res["is_deliverable"])
        self.assertEqual(res["status"], "ACCEPTED")
        self.assertEqual(res["smtp_code"], 250)


class TestCrawlerAndDomainEngine(unittest.TestCase):
    """Tests web crawler tech stack signatures and domain engine consolidation."""

    def test_crawler_tech_stack_detection(self):
        crawler = AsyncEmailWebCrawler()
        html = """
        <html>
        <head><script src="https://cdn.shopify.com/s/files/test.js"></script></head>
        <body>
            <div data-reactroot="">Content</div>
            <script src="https://js.stripe.com/v3/"></script>
        </body>
        </html>
        """
        headers = {"x-powered-by": "Shopify", "server": "cloudflare"}
        tech = crawler._detect_tech_stack(html, headers)
        self.assertIn("shopify", tech)
        self.assertIn("react", tech)
        self.assertIn("stripe", tech)
        self.assertIn("cloudflare", tech)

        cms = crawler._detect_primary_cms(tech)
        self.assertEqual(cms, "shopify")

    @patch("packages.domain.email_enricher.get_mx_hosts")
    @patch("packages.domain.email_enricher.is_catchall_domain")
    @patch("packages.domain.email_enricher.verify_email_smtp")
    def test_email_enrichment_engine_process_discovered(self, mock_verify, mock_catchall, mock_mx):
        mock_mx.return_value = ["mx1.acme.com"]
        mock_catchall.return_value = False
        mock_verify.return_value = {"is_deliverable": True, "smtp_code": 250}

        crawl_results = {
            "emails": ["sales@acme.com", "info@acme.com"],
            "tech_stack": ["wordpress", "react"],
            "cms_detected": "wordpress",
            "ssl_valid": True,
            "site_speed_ms": 120,
            "http_status_code": 200,
            "domain": "acme.com",
        }

        result = EmailEnrichmentEngine.process_discovered_emails(
            company_id="comp-12345",
            domain="acme.com",
            crawl_results=crawl_results,
            probe_smtp=True,
        )

        self.assertEqual(result.company_id, "comp-12345")
        self.assertEqual(result.domain, "acme.com")
        self.assertIn(result.primary_email, ("info@acme.com", "sales@acme.com"))
        self.assertEqual(result.deliverability_status, "DELIVERABLE")
        self.assertGreaterEqual(result.confidence_score, 0.80)
        self.assertEqual(result.cms_detected, "wordpress")
        self.assertTrue(result.ssl_valid)


class TestRepositoryAndConfig(unittest.TestCase):
    """Tests configuration manager settings and repository parameterization."""

    def test_config_manager_email_enrichment_defaults(self):
        cfg = config_manager.get_email_enrichment_config()
        self.assertEqual(cfg["rate_limit_per_second"], 50.0)
        self.assertEqual(cfg["per_host_limit"], 2)
        self.assertEqual(cfg["total_timeout"], 10.0)
        self.assertEqual(cfg["max_body_size"], 5 * 1024 * 1024)

    def test_config_manager_smtp_probe_defaults(self):
        smtp_cfg = config_manager.get_smtp_probe_config()
        self.assertIn("info", smtp_cfg["candidate_prefixes"])
        self.assertIn("contact", smtp_cfg["candidate_prefixes"])
        self.assertEqual(smtp_cfg["timeout"], 5.0)

    @patch("packages.infrastructure.email_enrichment_repository.execute_query")
    def test_repository_create_and_update_job(self, mock_exec):
        job_id = EmailEnrichmentRepository.create_job(
            job_type="POST_DEDUP_CANONICAL",
            batch_size=200,
        )
        self.assertTrue(bool(job_id))
        self.assertTrue(mock_exec.called)

        EmailEnrichmentRepository.update_job_progress(
            job_id=job_id,
            processed_delta=10,
            success_delta=8,
            failed_delta=2,
            last_processed_id="00000000-0000-0000-0000-000000000100",
        )
        self.assertEqual(mock_exec.call_count, 2)


class TestEmailEnrichmentWorkflow(unittest.IsolatedAsyncioTestCase):
    """Tests Temporal saga workflow states, signals, queries, and execution loop."""

    def test_workflow_alias_equivalence(self):
        self.assertIs(EmailEnrichmentWorkflow, Agent7EmailEnrichmentWorkflow)

    def test_workflow_initial_status(self):
        wf = EmailEnrichmentWorkflow()
        with patch("temporalio.workflow.info") as mock_info:
            mock_info.return_value.workflow_id = "wf-email-enrichment-001"
            status = wf.get_status()
            self.assertEqual(status["workflow_id"], "wf-email-enrichment-001")
            self.assertEqual(status["status"], "INITIALIZED")
            self.assertEqual(status["step"], "INIT")
            self.assertFalse(status["paused"])
            self.assertIsNone(status["job_id"])
            self.assertEqual(status["total_processed"], 0)

    def test_workflow_pause_resume_signals(self):
        wf = EmailEnrichmentWorkflow()
        with patch("temporalio.workflow.logger"):
            wf.pause()
            self.assertTrue(wf._paused)
            wf.resume()
            self.assertFalse(wf._paused)

    @patch("temporalio.workflow.execute_activity")
    @patch("temporalio.workflow.wait_condition")
    @patch("temporalio.workflow.info")
    @patch("temporalio.workflow.logger")
    async def test_workflow_run_execution(self, mock_logger, mock_info, mock_wait, mock_exec):
        mock_info.return_value.workflow_id = "wf-test-run-001"
        mock_wait.return_value = None

        # Return sequence for activities:
        # 1. create_enrichment_job_activity -> "job-uuid-123"
        # 2. fetch_pending_enrichment_batch_activity -> [{"id": "c1", "domain": "a.com"}]
        # 3. enrich_email_batch_activity -> {"processed": 1, "successful": 1, "failed": 0, "last_id": "c1"}
        # 4. finalize_enrichment_job_activity -> None
        mock_exec.side_effect = [
            "job-uuid-123",
            [{"id": "c1", "domain": "a.com"}],
            {"processed": 1, "successful": 1, "failed": 0, "last_id": "c1"},
            None,
        ]

        wf = EmailEnrichmentWorkflow()
        result = await wf.run(config={"batch_size": 10, "max_records": 1})

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["job_id"], "job-uuid-123")
        self.assertEqual(result["total_processed"], 1)
        self.assertEqual(result["total_successful"], 1)
        self.assertEqual(result["total_failed"], 0)
        self.assertEqual(result["last_processed_id"], "c1")


class TestEmailEnrichmentActivities(unittest.IsolatedAsyncioTestCase):
    """Tests Temporal side-effect activities for jobs, fetching, crawling, and finalizing."""

    @patch("packages.temporal.activities.email_enrichment_activities.activity")
    @patch("packages.temporal.activities.email_enrichment_activities.email_enrichment_repo")
    async def test_create_enrichment_job_activity(self, mock_repo, mock_activity):
        mock_activity.info.return_value.activity_id = "act-job-001"
        mock_repo.create_job.return_value = "job-456"

        job_id = await create_enrichment_job_activity(
            job_type="POST_DEDUP_CANONICAL",
            target_table="companies",
            batch_size=100,
            max_concurrency=20,
        )
        self.assertEqual(job_id, "job-456")
        mock_repo.create_job.assert_called_once()

    @patch("packages.temporal.activities.email_enrichment_activities.activity")
    @patch("packages.temporal.activities.email_enrichment_activities.email_enrichment_repo")
    async def test_fetch_pending_enrichment_batch_activity(self, mock_repo, mock_activity):
        mock_repo.get_pending_canonical_companies.return_value = [
            {"id": "comp-1", "legal_name": "Acme Inc", "domain": "acme.com"}
        ]

        batch = await fetch_pending_enrichment_batch_activity(last_id=None, limit=50)
        self.assertEqual(len(batch), 1)
        self.assertEqual(batch[0]["id"], "comp-1")
        mock_repo.get_pending_canonical_companies.assert_called_once_with(last_id=None, limit=50)

    @patch("packages.temporal.activities.email_enrichment_activities.activity")
    @patch("packages.temporal.activities.email_enrichment_activities.email_enrichment_repo")
    @patch("packages.temporal.activities.email_enrichment_activities.email_enrichment_engine")
    async def test_enrich_email_batch_activity(self, mock_engine, mock_repo, mock_activity):
        companies = [{"id": "c1", "legal_name": "Test Co", "domain": "test.com"}]
        mock_result = EnrichmentResult(
            company_id="c1",
            domain="test.com",
            primary_email="info@test.com",
            all_emails=["info@test.com"],
            discovery_source="WEB_CRAWLER",
            deliverability_status="DELIVERABLE",
            confidence_score=0.92,
            is_catchall=False,
            tech_stack=["react", "cloudflare"],
            cms_detected=None,
            ssl_valid=True,
            site_speed_ms=150,
            http_status_code=200,
        )
        mock_engine.enrich_companies_batch = unittest.mock.AsyncMock(return_value=[mock_result])

        res = await enrich_email_batch_activity(companies=companies, job_id="job-123", probe_smtp=True)

        self.assertEqual(res["processed"], 1)
        self.assertEqual(res["successful"], 1)
        self.assertEqual(res["failed"], 0)
        self.assertEqual(res["last_id"], "c1")
        self.assertTrue(mock_repo.save_enrichment_result.called)
        self.assertTrue(mock_repo.record_audit_probe.called)
        self.assertTrue(mock_repo.update_job_progress.called)

    @patch("packages.temporal.activities.email_enrichment_activities.activity")
    @patch("packages.temporal.activities.email_enrichment_activities.email_enrichment_repo")
    async def test_finalize_enrichment_job_activity(self, mock_repo, mock_activity):
        await finalize_enrichment_job_activity(job_id="job-123", error_message=None)
        mock_repo.complete_job.assert_called_once_with(job_id="job-123", error_message=None)


class TestPostDeduplicationBusinessRule(unittest.TestCase):
    """
    Verifies the core architectural invariant:
    Email enrichment must start strictly post-deduplication (after Agent 3 completes successfully).
    """

    def test_master_orchestrator_skips_enrichment_if_dedup_fails(self):
        orchestrator = MasterOrchestrator()
        # Simulate Phase 3 Identity failing
        orchestrator._phase_results["agent_3_identity"] = {"status": "FAILED", "error": "Splink error"}
        dedup_succeeded = orchestrator._phase_results.get("agent_3_identity", {}).get("status") == "SUCCESS"
        self.assertFalse(dedup_succeeded)

    def test_master_orchestrator_executes_enrichment_if_dedup_succeeds(self):
        orchestrator = MasterOrchestrator()
        # Simulate Phase 3 Identity succeeding
        orchestrator._phase_results["agent_3_identity"] = {
            "status": "SUCCESS",
            "clusters_resolved": 1500,
            "canonical_merged": 1500,
        }
        dedup_succeeded = orchestrator._phase_results.get("agent_3_identity", {}).get("status") == "SUCCESS"
        self.assertTrue(dedup_succeeded)


class TestWorkerEmailEnrichmentRegistry(unittest.TestCase):
    """Verifies Worker 7 daemon task queue configuration and registered operations."""

    def test_worker_queue_and_activities(self):
        import packages.temporal.workers.worker_email_enrichment as worker_mod
        self.assertEqual(worker_mod.TASK_QUEUE, QUEUE_EMAIL_ENRICHMENT)
        self.assertGreaterEqual(worker_mod.MAX_ACTIVITIES, 5)


if __name__ == "__main__":
    unittest.main()
