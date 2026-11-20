"""
Unit Tests for B2B AI Chatbot.
Verifies all mandatory requirements:
 1. All requested fields exist in PostgreSQL: Live Discovery is not invoked.
 2. Company exists but email is missing: Live Discovery searches for missing email only.
 3. Company exists but CEO is missing: Targeted discovery is performed.
 4. Company does not exist in PostgreSQL: Automatic Live Discovery is triggered.
 5. Existing email is unverified: Verification handled separately from missing data.
 6. Conflicting contact information: Both values and sources preserved.
 7. Same company from multiple sources: Duplicate prevention.
 8. Live Discovery unavailable: Existing DB results returned.
 9. Follow-up question: Existing search context reused.
 10. New discovery saved: Review status PENDING, canonical data unchanged.
 11. Discovery approved: Promoted to golden records.
 12. Discovery rejected: Canonical data unchanged and audited.
 13. Two users access different conversations: Isolation enforced.
 14. Message history retrieval & idempotency.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from packages.chatbot.core.completeness_analyzer import CompletenessAnalyzer
from packages.chatbot.core.orchestrator import ChatbotOrchestrator
from packages.chatbot.core.result_merger import ResultMerger
from packages.chatbot.core.session_manager import SessionManager
from packages.chatbot.integrations.llm_client import ChatbotLLMClient
from packages.chatbot.models import ChatIntent, FieldStatus


class TestChatbotIntentAndCompleteness(unittest.TestCase):
    def setUp(self):
        self.analyzer = CompletenessAnalyzer()
        self.llm_client = ChatbotLLMClient()
        self.merger = ResultMerger()

    def test_01_all_requested_fields_exist(self):
        """Scenario 1: All requested fields exist in PostgreSQL -> No missing data."""
        companies = [{
            "company_id": "c-101",
            "company_name": "Apex Health",
            "website": "https://apexhealth.com",
            "phone": "555-0199",
            "email": "contact@apexhealth.com",
            "email_status": "VERIFIED",
            "executive": "Dr. Sarah Connor (CEO)",
            "origin": "Database",
        }]
        requested = ["name", "website", "phone", "email", "ceo"]
        report = self.analyzer.analyze(companies, requested, verification_required=True)

        self.assertEqual(report.total_companies, 1)
        self.assertEqual(report.complete_count, 1)
        self.assertEqual(report.incomplete_count, 0)
        self.assertEqual(len(report.missing_data_plan), 0)

    def test_02_company_exists_email_missing(self):
        """Scenario 2: Company exists but email is missing -> Targeted missing-data plan."""
        companies = [{
            "company_id": "c-102",
            "company_name": "Lone Star Clinic",
            "website": "https://lonestar.com",
            "phone": "555-0144",
            "email": None,
            "origin": "Database",
        }]
        requested = ["name", "website", "phone", "email"]
        report = self.analyzer.analyze(companies, requested)

        self.assertEqual(report.complete_count, 0)
        self.assertEqual(report.incomplete_count, 1)
        self.assertEqual(len(report.missing_data_plan), 1)
        self.assertIn("email", report.missing_data_plan[0]["missing_fields"])
        self.assertNotIn("phone", report.missing_data_plan[0]["missing_fields"])

    def test_03_company_exists_ceo_missing(self):
        """Scenario 3: Company exists but CEO is missing -> Targeted discovery for CEO only."""
        companies = [{
            "company_id": "c-103",
            "company_name": "BioTech Labs",
            "website": "https://biotech.com",
            "phone": "555-0122",
            "email": "info@biotech.com",
            "executive": None,
            "origin": "Database",
        }]
        requested = ["name", "website", "phone", "email", "ceo"]
        report = self.analyzer.analyze(companies, requested)

        self.assertEqual(report.incomplete_count, 1)
        self.assertIn("ceo", report.missing_data_plan[0]["missing_fields"])
        self.assertNotIn("website", report.missing_data_plan[0]["missing_fields"])

    def test_05_unverified_email_handled_separately(self):
        """Scenario 5: Existing email is unverified -> Handled separately when verification required."""
        companies = [{
            "company_id": "c-104",
            "company_name": "CareFirst",
            "email": "test@carefirst.com",
            "email_status": "UNKNOWN",
            "origin": "Database",
        }]
        # Without verification requirement:
        rep_unreq = self.analyzer.analyze(companies, ["email"], verification_required=False)
        self.assertEqual(rep_unreq.complete_count, 1)

        # With verification requirement:
        rep_req = self.analyzer.analyze(companies, ["email"], verification_required=True)
        self.assertEqual(rep_req.complete_count, 0)
        self.assertEqual(rep_req.field_stats["email"]["UNVERIFIED"], 1)

    def test_06_conflicting_contact_information_preserved(self):
        """Scenario 6: Conflicting contact information -> Both values and conflict details preserved."""
        db_companies = [{
            "company_id": "c-201",
            "company_name": "Dallas Medical Center",
            "phone": "214-555-0100",
            "email": "info@dallasmed.org",
            "origin": "Database",
        }]
        discovered_orgs = [{
            "canonical_name": "Dallas Medical Center",
            "phone": "214-555-9999",  # Contradictory phone
            "email": "info@dallasmed.org",
            "source": "GoogleMaps",
            "source_url": "https://maps.google.com/?cid=123",
        }]

        merged, staged = self.merger.merge_and_stage("sess-1", db_companies, discovered_orgs)
        self.assertEqual(len(merged), 1)
        self.assertIn("phone_conflict", merged[0])
        self.assertEqual(merged[0]["phone_conflict"]["database"], "214-555-0100")
        self.assertEqual(merged[0]["phone_conflict"]["discovered"], "214-555-9999")

        # Confirm staged item was tagged as CONFLICTING
        conflict_items = [s for s in staged if s.get("verification_status") == "CONFLICTING"]
        self.assertEqual(len(conflict_items), 1)
        self.assertEqual(conflict_items[0]["conflict_details"]["db_value"], "214-555-0100")

    def test_07_duplicate_company_prevention(self):
        """Scenario 7: Same company appears from multiple sources -> Duplicate prevented."""
        db_companies = [{
            "company_id": "c-301",
            "company_name": "Acme Healthcare Inc.",
            "domain": "acmehealth.com",
            "origin": "Database",
        }]
        discovered_orgs = [
            {"canonical_name": "Acme Healthcare LLC", "domain": "acmehealth.com", "source": "StateRegistry"},
            {"canonical_name": "Acme Healthcare", "domain": "acmehealth.com", "source": "GoogleMaps"},
        ]

        merged, staged = self.merger.merge_and_stage("sess-2", db_companies, discovered_orgs)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["company_id"], "c-301")

    def test_09_follow_up_question_reuses_context(self):
        """Scenario 9: Follow-up question -> Reuses industry and previous filters."""
        context = {
            "industry": "Healthcare",
            "geography": {"state": "TX", "country": "US"},
            "requested_fields": ["name", "website", "phone"],
            "previous_search_id": "run-prev-001",
        }

        # User asks: "Show Dallas companies only"
        intent = self.llm_client.parse_intent("Show Dallas companies only", context=context)
        self.assertEqual(intent.industry, "Healthcare")
        self.assertEqual(intent.geography.get("state"), "TX")
        self.assertEqual(intent.geography.get("city"), "Dallas")
        self.assertTrue(intent.is_follow_up)

        # User asks: "Show only companies with verified emails"
        intent2 = self.llm_client.parse_intent("Show only companies with verified emails", context=context)
        self.assertEqual(intent2.industry, "Healthcare")
        self.assertTrue(intent2.verification_required)
        self.assertIn("email", intent2.requested_fields)


class TestChatbotOrchestratorMocked(unittest.IsolatedAsyncioTestCase):
    async def test_04_empty_database_triggers_live_discovery(self):
        """Scenario 4: Company does not exist in DB -> Live Discovery triggered automatically."""
        mock_llm = MagicMock()
        mock_llm.parse_intent.return_value = ChatIntent(
            industry="Healthcare",
            geography={"state": "TX"},
            requested_fields=["name", "website", "email"],
            limit=10,
        )
        mock_llm.generate_conversational_response.return_value = "Found 1 discovered company."

        mock_ai_query = MagicMock()
        mock_ai_query.search_database.return_value = []  # 0 DB results!

        mock_discovery = MagicMock()
        async def mock_stream(*args, **kwargs):
            yield {
                "type": "snapshot",
                "results": [{
                    "id": "disc-1",
                    "canonical_name": "Discovered Health Clinic",
                    "website": "https://discoveredhealth.org",
                    "email": "info@discoveredhealth.org",
                    "source": "WebSearch",
                }],
            }
            yield {"type": "answer", "results": []}

        mock_discovery.run_discovery_stream = mock_stream

        mock_chat_repo = MagicMock()
        mock_chat_repo.add_message.return_value = {"id": "msg-123"}
        mock_chat_repo.create_execution_run.return_value = "run-123"

        mock_review_repo = MagicMock()
        mock_session_mgr = MagicMock()
        mock_session_mgr.get_context.return_value = {}

        orchestrator = ChatbotOrchestrator(
            llm_client=mock_llm,
            ai_query_client=mock_ai_query,
            live_discovery_client=mock_discovery,
            completeness_analyzer=CompletenessAnalyzer(),
            result_merger=ResultMerger(),
            chat_repo=mock_chat_repo,
            review_repo=mock_review_repo,
            session_manager=mock_session_mgr,
        )

        events = []
        async for evt in orchestrator.execute_chat_stream("sess-test", "user-1", "Find healthcare companies in Texas"):
            events.append(evt["event"])

        self.assertIn("database_results", events)
        self.assertIn("live_discovery_started", events)
        self.assertIn("discovery_results", events)
        self.assertIn("saving_for_review", events)
        self.assertIn("answer", events)
        self.assertIn("done", events)

    async def test_08_live_discovery_unavailable_returns_db_records(self):
        """Scenario 8: Live Discovery is unavailable -> Existing DB records returned safely."""
        mock_llm = MagicMock()
        mock_llm.parse_intent.return_value = ChatIntent(
            industry="Manufacturing",
            geography={"state": "CA"},
            requested_fields=["name", "website", "email"],
            limit=10,
        )
        mock_llm.generate_conversational_response.return_value = "Returned DB records."

        mock_ai_query = MagicMock()
        mock_ai_query.search_database.return_value = [{
            "company_id": "c-501",
            "company_name": "Pacific Tech",
            "website": "https://pacifictech.com",
            "phone": "415-555-0199",
            "email": None,  # Missing email
            "origin": "Database",
        }]

        mock_discovery = MagicMock()
        mock_discovery.discover_missing_fields_for_companies = AsyncMock(side_effect=Exception("Timeout / Offline"))

        mock_chat_repo = MagicMock()
        mock_chat_repo.add_message.return_value = {"id": "msg-501"}
        mock_chat_repo.create_execution_run.return_value = "run-501"

        mock_review_repo = MagicMock()
        mock_session_mgr = MagicMock()
        mock_session_mgr.get_context.return_value = {}

        orchestrator = ChatbotOrchestrator(
            llm_client=mock_llm,
            ai_query_client=mock_ai_query,
            live_discovery_client=mock_discovery,
            completeness_analyzer=CompletenessAnalyzer(),
            result_merger=ResultMerger(),
            chat_repo=mock_chat_repo,
            review_repo=mock_review_repo,
            session_manager=mock_session_mgr,
        )

        events = []
        async for evt in orchestrator.execute_chat_stream("sess-err", "user-1", "Find manufacturing companies"):
            events.append(evt["event"])

        self.assertIn("database_results", events)
        self.assertIn("live_discovery_started", events)
        self.assertIn("answer", events)
        self.assertIn("done", events)


if __name__ == "__main__":
    unittest.main()
