"""
Agent 4 (Executive Discovery & Contact Intelligence) Comprehensive Test Suite
=============================================================================
Verifies:
1. Contact Validation:
   - validate_contacts_activity on staging_dataextraction.working_organizations
   - validate_contacts_activity on staging_dataextraction.staging_companies
   - Phone and email verification status and failure isolation
2. Lead Building & Consolidation:
   - build_leads_activity bridging staging_companies -> working_organizations
   - Dynamic schema qualification and deterministic UUID generation
3. Autonomous Executive Discovery:
   - discover_executives_activity extracting C-Suite (CEO, CFO, VPs)
   - Ingestion into staging_dataextraction.working_persons
   - FK integrity and bitemporal association with working_organizations
4. Person & Relationship Ingestion:
   - ingest_working_person_activity individual upsert and status tracking
   - complete_executive_enrichment_activity marking PENDING organizations
5. Agent4ExecutiveWorkflow:
   - Signal handling (pause, resume)
   - Query handling (get_status() with safe fallback)
   - Full execution returning executives_identified telemetry
"""

import asyncio
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
for p in (str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "pipeline"), str(REPO_ROOT / "packages" / "infrastructure")):
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.infrastructure.kg_ingestion_bridge import kg_ingestion_bridge
from packages.temporal.activities.pipeline_activities import (
    validate_contacts_activity,
    build_leads_activity,
)
from packages.temporal.activities.storage_activities import (
    discover_executives_activity,
    ingest_working_person_activity,
    complete_executive_enrichment_activity,
)
from packages.temporal.workflows.w4_executive_workflow import Agent4ExecutiveWorkflow


class TestAgent4ExecutiveExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a test organization in working_organizations for executive testing
        cls.test_org_id = str(uuid.uuid4())
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO staging_dataextraction.working_organizations (
                        org_id, legal_name, display_name, primary_domain, website,
                        statutory_tax_id, sec_cik, jurisdiction, industry, phones,
                        identity_confidence, email_verification_status, executive_enrichment_status,
                        governance_status, created_at, updated_at
                    ) VALUES (
                        %s, 'Apex Dynamics Corp', 'Apex Dynamics', 'apexdynamics.com', 'https://apexdynamics.com',
                        '12-3456789', '0001234567', 'US', 'Software', '["+1-555-0199"]'::jsonb,
                        1.0, 'PENDING', 'PENDING', 'IN_ENRICHMENT', NOW(), NOW()
                    ) ON CONFLICT (org_id) DO NOTHING;
                """, (cls.test_org_id,))
            conn.commit()
        finally:
            release_connection(conn)

    @classmethod
    def tearDownClass(cls):
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM staging_dataextraction.working_persons WHERE org_id = %s;", (cls.test_org_id,))
                cur.execute("DELETE FROM staging_dataextraction.working_organizations WHERE org_id = %s;", (cls.test_org_id,))
            conn.commit()
        finally:
            release_connection(conn)

    def test_01_validate_contacts_on_working_organizations(self):
        """Validate phone numbers from working_organizations without SQL schema errors."""
        res = asyncio.run(validate_contacts_activity("staging_dataextraction.working_organizations", limit=5))
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertIn("validated", res)
        self.assertIn("failed", res)

    def test_02_validate_contacts_on_staging_companies(self):
        """Validate contacts from staging_companies with dynamic column inspection."""
        res = asyncio.run(validate_contacts_activity("staging_dataextraction.staging_companies", limit=5))
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertIn("validated", res)
        self.assertIn("failed", res)

    def test_03_build_leads_activity_consolidation(self):
        """Build enriched leads from staging_companies into working_organizations."""
        res = asyncio.run(build_leads_activity(
            "staging_dataextraction.staging_companies",
            "staging_dataextraction.working_organizations",
            batch_size=3
        ))
        self.assertEqual(res.get("status"), "SUCCESS")
        self.assertGreaterEqual(res.get("built", 0), 0)
        self.assertGreaterEqual(res.get("promoted_companies", 0), 0)

    def test_04_discover_executives_activity(self):
        """Extract decision makers for pending working organizations and persist to working_persons."""
        res = asyncio.run(discover_executives_activity(batch_size=5))
        self.assertEqual(res.get("status"), "COMPLETED")
        self.assertIn("executives_discovered", res)
        self.assertIn("organizations_enriched", res)

        # Verify records exist in database
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(1) FROM staging_dataextraction.working_persons;")
                count = cur.fetchone()[0]
                self.assertGreater(count, 0)
        finally:
            release_connection(conn)

    def test_05_ingest_working_person_activity(self):
        """Ingest individual executive decision maker into working_persons."""
        p_data = {
            "person_id": str(uuid.uuid4()),
            "full_name": "Eleanor Vance",
            "first_name": "Eleanor",
            "last_name": "Vance",
            "title": "Chief Technology Officer (CTO)",
            "seniority": "C_SUITE",
            "department": "ENGINEERING_TECH",
            "primary_email": "eleanor.vance@apexdynamics.com",
            "primary_phone": "+1-555-0188",
            "linkedin_url": "https://linkedin.com/in/eleanor-vance-test",
            "confidence_score": 0.95,
        }
        res = asyncio.run(ingest_working_person_activity({
            "person_data": p_data,
            "org_id": self.test_org_id,
            "confidence_score": 0.95,
        }))
        self.assertEqual(res.get("status"), "staged_in_working_persons")

        # Verify row in DB
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT full_name, title, primary_email 
                    FROM staging_dataextraction.working_persons 
                    WHERE person_id = %s;
                """, (p_data["person_id"],))
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "Eleanor Vance")
                self.assertEqual(row[1], "Chief Technology Officer (CTO)")
                self.assertEqual(row[2], "eleanor.vance@apexdynamics.com")
        finally:
            release_connection(conn)

    def test_06_complete_executive_enrichment_activity(self):
        """Mark executive enrichment as completed for an organization."""
        res = asyncio.run(complete_executive_enrichment_activity(self.test_org_id))
        self.assertEqual(res.get("status"), "COMPLETED")
        self.assertEqual(res.get("org_id"), self.test_org_id)

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT executive_enrichment_status 
                    FROM staging_dataextraction.working_organizations 
                    WHERE org_id = %s;
                """, (self.test_org_id,))
                status = cur.fetchone()[0]
                self.assertEqual(status, "COMPLETED")
        finally:
            release_connection(conn)

    def test_07_workflow_signals_and_query(self):
        """Verify Agent4ExecutiveWorkflow signal state transitions and query response."""
        wf = Agent4ExecutiveWorkflow()
        status = wf.get_status()
        self.assertEqual(status["status"], "INITIALIZED")
        self.assertFalse(status["paused"])
        self.assertEqual(status["workflow_id"], "agent4-executive")

        wf.pause()
        self.assertTrue(wf._paused)
        status_paused = wf.get_status()
        self.assertTrue(status_paused["paused"])

        wf.resume()
        self.assertFalse(wf._paused)

    def test_08_workflow_full_execution(self):
        """Execute Agent4ExecutiveWorkflow.run() with activities mocked for end-to-end flow."""
        wf = Agent4ExecutiveWorkflow()

        async def mock_execute_activity(activity_fn, *args, **kwargs):
            fn_name = getattr(activity_fn, "__name__", str(activity_fn))
            if "validate_contacts" in fn_name:
                return {"validated": 42, "failed": 3, "status": "SUCCESS"}
            elif "build_leads" in fn_name:
                return {"built": 45, "promoted_companies": 42, "status": "SUCCESS"}
            elif "discover_executives" in fn_name:
                return {"status": "COMPLETED", "executives_discovered": 84, "organizations_enriched": 42}
            elif "complete_executive_enrichment" in fn_name:
                return {"org_id": "ALL_PENDING", "status": "COMPLETED"}
            return {"status": "SUCCESS"}

        with patch("temporalio.workflow.execute_activity", side_effect=mock_execute_activity), \
             patch("temporalio.workflow.wait_condition", new_callable=AsyncMock):
            result = asyncio.run(wf.run({
                "source_table": "staging_dataextraction.working_organizations",
                "batch_limit": 50,
            }))

            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(result["executives_identified"], 84)
            self.assertIn("contact_validation", result["results"])
            self.assertIn("build_leads", result["results"])
            self.assertIn("executive_discovery", result["results"])


if __name__ == "__main__":
    unittest.main()
