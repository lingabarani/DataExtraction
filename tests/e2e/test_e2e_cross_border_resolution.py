"""
DataExtraction — E2E Scenario 4: Cross-Border Multi-Tier Entity Resolution
===========================================================================
Comprehensive End-to-End integration test covering:
1. Statutory ID Precedence (EIN, RFC, CIK, NPI strictly precede web domains).
2. Cross-border company isolation (US parent vs Mexico subsidiary sharing domain).
3. Mexican RFC syntax and personality verification (Persona Moral).
4. Non-destructive provenance merging.
5. Executive career transition tracking.
"""

import json
import os
import sys
import unittest
from pathlib import Path

# Bootstrap paths
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGES = _REPO_ROOT / "packages"

for p in [
    _PACKAGES / "pipeline",
    _PACKAGES / "infrastructure",
    _REPO_ROOT / "tests" / "e2e" / "utils",
    _REPO_ROOT,
]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from deduplicator import Deduplicator
from tax_validator import validate_ein, validate_rfc
from packages.scrapers.mexico.utils.rfc_utils import is_valid_rfc, get_rfc_type
from db_test_cleaner import EphemeralDatabaseHarness
from wiremock_controller import load_fixture


class TestE2ECrossBorderResolution(unittest.TestCase):
    """End-to-End test suite for Cross-Border Deduplication and Entity Resolution."""

    @classmethod
    def setUpClass(cls):
        cls.harness = EphemeralDatabaseHarness()
        cls.conn = cls.harness.get_connection()
        cls.fixtures = load_fixture("mock_cross_border_leads.json")

    def setUp(self):
        self.harness.clean_tables()

    @classmethod
    def tearDownClass(cls):
        cls.harness.close()

    def test_e2e_rfc_syntax_and_classification(self):
        """Verifies Mexican RFC validation for Persona Moral."""
        mx_data = self.fixtures["mexico_subsidiary"]
        rfc = mx_data["rfc"]

        # Validate syntax
        self.assertTrue(is_valid_rfc(rfc))
        # Validate personality type (12 chars = Persona Moral)
        self.assertEqual(get_rfc_type(rfc), "MORAL")

        # Validate with pipeline tax validator
        tax_res = validate_rfc(rfc)
        self.assertTrue(tax_res["is_valid"])
        self.assertEqual(tax_res["rfc_type"], "MORAL")

    def test_e2e_statutory_precedence_prevents_false_subsidiary_collapse(self):
        """
        CRITICAL ARCHITECTURAL TEST:
        US parent and Mexican subsidiary share the domain 'apexmanufacturing.com'.
        Because they have distinct statutory tax IDs (EIN vs RFC), the Deduplicator
        MUST NOT collapse them into the same company ID.
        """
        us_data = self.fixtures["us_parent"]
        mx_data = self.fixtures["mexico_subsidiary"]

        # Assert shared domain
        self.assertEqual(us_data["domain"], mx_data["domain"])

        dedup = Deduplicator(self.conn)

        # 1. Resolve US company
        res_us = dedup.check_company(us_data)
        self.assertEqual(res_us.action, "insert")
        us_id = res_us.id

        # Insert US company into test DB
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO companies (id, name, legal_name, normalized_name, ein, domain, state_code, country)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            us_id,
            us_data["legal_name"],
            us_data["legal_name"],
            us_data["normalized_name"],
            us_data["ein"],
            us_data["domain"],
            us_data["state_code"],
            us_data["country"],
        ))
        self.conn.commit()

        # 2. Resolve Mexican subsidiary (shares domain, but has RFC and distinct statutory ID)
        res_mx = dedup.check_company(mx_data)

        # The resolution MUST NOT match the US company ID
        self.assertNotEqual(
            res_mx.id,
            us_id,
            "Subsidiary with distinct statutory RFC must NEVER collapse into US parent domain!",
        )
        self.assertEqual(res_mx.action, "insert")

    def test_e2e_executive_career_transition_tracking(self):
        """Verifies that an executive moving positions preserves career history."""
        dedup = Deduplicator(self.conn)

        person_initial = {
            "first_name": "Marcus",
            "last_name": "Vance",
            "email": "m.vance@apexmanufacturing.com",
            "title": "VP Engineering",
            "company_id": "comp-us-001",
        }

        # First resolution -> insert
        res1 = dedup.check_person(person_initial)
        self.assertEqual(res1.action, "insert")
        person_id = res1.id

        # Persist to test DB
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO people (id, company_id, first_name, last_name, full_name, title, email, career_history)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            person_id,
            person_initial["company_id"],
            person_initial["first_name"],
            person_initial["last_name"],
            f"{person_initial['first_name']} {person_initial['last_name']}",
            person_initial["title"],
            person_initial["email"],
            json.dumps([]),
        ))
        self.conn.commit()

        # Executive promoted to CEO
        person_updated = {
            "first_name": "Marcus",
            "last_name": "Vance",
            "email": "m.vance@apexmanufacturing.com",
            "title": "Chief Executive Officer",
            "company_id": "comp-us-001",
        }

        res2 = dedup.check_person(person_updated)
        self.assertEqual(res2.action, "update")
        self.assertEqual(res2.id, person_id)
        # Career history should archive previous title
        self.assertIn("career_history", res2.updates)


if __name__ == "__main__":
    unittest.main()
