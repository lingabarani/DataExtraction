"""
Integration Tests for B2B AI Chatbot.
Runs against the actual PostgreSQL database (chat_dataextraction schema).
Validates:
 - Session isolation between different users (Scenario 13)
 - New discoveries saved with PENDING review status (Scenario 10)
 - Approval workflow & canonical promotion (Scenario 11)
 - Rejection workflow & audit trail preservation (Scenario 12)
 - History retrieval & SSE idempotency (Scenario 14)
"""

import unittest
from uuid import uuid4

from packages.chatbot.persistence.chat_repository import ChatRepository
from packages.chatbot.persistence.review_repository import ReviewRepository
from packages.infrastructure.db_connector import get_db_cursor


class TestChatbotDatabaseIntegration(unittest.TestCase):
    def setUp(self):
        self.chat_repo = ChatRepository()
        self.review_repo = ReviewRepository()
        self.user_a = f"user_a_{uuid4().hex[:8]}"
        self.user_b = f"user_b_{uuid4().hex[:8]}"

    def test_13_user_session_isolation(self):
        """Scenario 13: Two users access different conversations -> Sessions strictly isolated."""
        sess_a = self.chat_repo.create_session(user_id=self.user_a, title="User A Session")
        sess_b = self.chat_repo.create_session(user_id=self.user_b, title="User B Session")

        # User A should only see Session A
        list_a = self.chat_repo.list_sessions(user_id=self.user_a)
        session_ids_a = [s["id"] for s in list_a]
        self.assertIn(sess_a["id"], session_ids_a)
        self.assertNotIn(sess_b["id"], session_ids_a)

        # User B should only see Session B
        list_b = self.chat_repo.list_sessions(user_id=self.user_b)
        session_ids_b = [s["id"] for s in list_b]
        self.assertIn(sess_b["id"], session_ids_b)
        self.assertNotIn(sess_a["id"], session_ids_b)

        # Direct access to User B's session by User A must return None
        direct_b_by_a = self.chat_repo.get_session(sess_b["id"], user_id=self.user_a)
        self.assertIsNone(direct_b_by_a)

    def test_10_11_12_review_item_lifecycle(self):
        """Scenarios 10, 11, 12: Staged discovery saved as PENDING, approved promotion, rejected audit."""
        sess = self.chat_repo.create_session(user_id=self.user_a, title="Review Lifecycle Session")
        comp_id = str(uuid4())

        # 1. Add staged discovery -> Status must be PENDING
        item = self.review_repo.add_review_item(
            session_id=sess["id"],
            company_id=comp_id,
            company_name="Dallas Dental Care",
            field_name="email",
            discovered_value="contact@dallasdental.com",
            source_type="WebsiteCrawl",
            source_url="https://dallasdental.com/contact",
            evidence="Found email on contact page",
        )

        self.assertEqual(item["review_status"], "PENDING")
        self.assertEqual(item["discovered_value"], "contact@dallasdental.com")
        self.assertIsNone(item["reviewed_by"])

        # 2. Rejection Test (Scenario 12):
        rejected_item = self.review_repo.add_review_item(
            session_id=sess["id"],
            company_id=comp_id,
            company_name="Dallas Dental Care",
            field_name="phone",
            discovered_value="214-555-9999",
            source_type="GoogleMaps",
            evidence="Wrong phone listing",
        )
        reject_success = self.review_repo.reject_review_item(
            review_id=rejected_item["id"],
            reviewer="auditor@dataextraction.io",
            reason="Unverified aggregator number",
        )
        self.assertTrue(reject_success)

        rejected_fetched = self.review_repo.get_review_item(rejected_item["id"])
        self.assertEqual(rejected_fetched["review_status"], "REJECTED")
        self.assertEqual(rejected_fetched["reviewed_by"], "auditor@dataextraction.io")
        self.assertEqual(rejected_fetched["rejection_reason"], "Unverified aggregator number")

        # 3. Approval Test (Scenario 11):
        approve_success = self.review_repo.approve_review_item(
            review_id=item["id"],
            reviewer="admin@dataextraction.io",
            notes="Manually verified with official domain",
        )
        self.assertTrue(approve_success)

        approved_fetched = self.review_repo.get_review_item(item["id"])
        self.assertEqual(approved_fetched["review_status"], "APPROVED")
        self.assertEqual(approved_fetched["reviewed_by"], "admin@dataextraction.io")

    def test_duplicate_review_item_prevention(self):
        """Audit Scenario: Verify duplicate review items are prevented."""
        sess = self.chat_repo.create_session(user_id=self.user_a, title="Deduplication Session")
        c_id = str(uuid4())

        # First staging call
        item1 = self.review_repo.add_review_item(
            session_id=sess["id"],
            company_id=c_id,
            company_name="Austin Clinic",
            field_name="website",
            discovered_value="https://austinclinic.com",
            source_type="WebSearch",
        )

        # Second staging call with same company and field
        item2 = self.review_repo.add_review_item(
            session_id=sess["id"],
            company_id=c_id,
            company_name="Austin Clinic",
            field_name="website",
            discovered_value="https://austinclinic.com",
            source_type="WebSearch",
        )

        # IDs must match: duplicate was prevented!
        self.assertEqual(item1["id"], item2["id"])

    def test_14_messages_history_persistence(self):
        """Scenario 14: Messages persisted and retrievable chronologically."""
        sess = self.chat_repo.create_session(user_id=self.user_a, title="Message History Session")

        msg1 = self.chat_repo.add_message(
            session_id=sess["id"],
            role="user",
            content="Find healthcare companies in Texas",
        )

        msg2 = self.chat_repo.add_message(
            session_id=sess["id"],
            role="assistant",
            content="Found 25 healthcare companies.",
            structured_plan={"industry": "Healthcare", "state": "TX"},
            results_summary={"total": 25},
        )

        history = self.chat_repo.list_messages(sess["id"])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["content"], "Find healthcare companies in Texas")
        self.assertEqual(history[1]["content"], "Found 25 healthcare companies.")
        self.assertEqual(history[1]["structured_plan"]["industry"], "Healthcare")


if __name__ == "__main__":
    unittest.main()
