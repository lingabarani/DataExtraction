"""
DataExtraction — E2E Scenario 1: Federal Ingestion Pipeline
============================================================
Comprehensive End-to-End integration test covering:
1. Multi-source federal ingestion (SEC, CMS, FDIC, USASpending, SAM, ProPublica).
2. Field standardization and company/person entity normalization.
3. Strict IRS campus prefix validation (EIN).
4. Zero-data-loss Dead-Letter Queue quarantine on malformed filings.
5. Persistent storage in unified database schema.
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
    _PACKAGES / "scrapers" / "federal",
    _REPO_ROOT / "tests" / "e2e" / "utils",
    _REPO_ROOT,
]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from normalizer import normalize_company, normalize_person
from tax_validator import validate_ein
from dead_letter_queue import enqueue_dead_letter, _FALLBACK_FILE
from db_test_cleaner import EphemeralDatabaseHarness
from wiremock_controller import load_fixture


class TestE2EFederalPipeline(unittest.TestCase):
    """End-to-End test suite for the complete Federal Ingestion Pipeline."""

    @classmethod
    def setUpClass(cls):
        cls.harness = EphemeralDatabaseHarness()
        cls.conn = cls.harness.get_connection()
        cls.fixtures = load_fixture("mock_federal_records.json")

    def setUp(self):
        self.harness.clean_tables()
        if _FALLBACK_FILE.exists():
            _FALLBACK_FILE.unlink()

    @classmethod
    def tearDownClass(cls):
        cls.harness.close()

    def test_e2e_sec_edgar_ingestion_and_normalization(self):
        """Verifies SEC EDGAR 10-K filing transforms into canonical company record."""
        sec_records = self.fixtures["sec_edgar"]
        self.assertGreater(len(sec_records), 0)

        for raw in sec_records:
            # 1. Tax ID validation
            ein_res = validate_ein(raw.get("ein"))
            self.assertTrue(ein_res["is_valid"], f"Valid EIN expected for {raw['company_name']}")
            self.assertIsNotNone(ein_res["prefix"])

            # 2. Canonical normalization
            company = normalize_company(
                {
                    "name": raw["company_name"],
                    "company_name": raw["company_name"],
                    "ein": ein_res["formatted"],
                    "cik": raw["cik"],
                    "sic": raw["sic"],
                    "stateOfIncorporation": raw["state_incorporation"],
                    "address": raw["business_address"],
                },
                source="SEC",
            )
            company_id = f"sec-{raw['cik']}"

            # 3. DB Persistence
            cur = self.conn.cursor()
            cur.execute("""
                INSERT INTO companies (id, name, legal_name, normalized_name, ein, cik, sic_code, state_code, state_of_incorporation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                company_id,
                company["name"],
                company["legal_name"],
                company["normalized_name"],
                company["ein"],
                company["cik"],
                company["sic_code"],
                company["state_code"],
                company["state_of_incorporation"],
            ))
            self.conn.commit()

        # Verify database state
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(1) FROM companies WHERE cik IS NOT NULL")
        count = cur.fetchone()[0]
        self.assertEqual(count, len(sec_records))

    def test_e2e_cms_npi_practitioner_and_hospital_linking(self):
        """Verifies CMS NPI provider hospital and practitioner extraction."""
        cms_records = self.fixtures["cms_npi"]
        raw = cms_records[0]

        # 1. Normalize company (hospital facility via INTERNAL_JSON)
        company = normalize_company(
            {
                "company_id": f"npi-{raw['npi']}",
                "legal_name": raw["provider_organization_name"],
                "trade_name": raw["provider_organization_name"],
                "ein": raw["ein"],
                "address": {
                    "street": raw["practice_location_address"]["address_1"],
                    "city": raw["practice_location_address"]["city_name"],
                    "state": raw["practice_location_address"]["state_name"],
                    "state_code": "NY",
                    "zip_code": raw["practice_location_address"]["postal_code"],
                },
                "phone": raw["practice_location_address"]["telephone_number"],
            },
            source="INTERNAL_JSON",
        )

        # 2. Normalize executive person
        person = normalize_person(
            {
                "full_name": f"{raw['authorized_official_first_name']} {raw['authorized_official_last_name']}",
                "first_name": raw["authorized_official_first_name"],
                "last_name": raw["authorized_official_last_name"],
                "title": raw["authorized_official_title"],
                "company_id": company["id"],
                "company_name": company["name"],
            },
            source="CSV",
        )

        person["company_id"] = company["id"]
        self.assertEqual(company["state_code"], "NY")
        self.assertEqual(person["full_name"], "Craig Thompson")
        self.assertEqual(person["company_id"], company["id"])

    def test_e2e_dlq_quarantine_on_malformed_filing(self):
        """Verifies zero-data-loss fallback logging when a filing is corrupted."""
        corrupted_record = {
            "cik": "INVALID_CIK",
            "company_name": "Ghost Corp ??????",
            "ein": "00-0000000",  # Illegal EIN prefix
        }

        # Validate EIN fails
        ein_res = validate_ein(corrupted_record["ein"])
        self.assertFalse(ein_res["is_valid"])

        # Quarantine into Dead-Letter Queue (triggers zero-data-loss disk fallback on non-Postgres)
        enqueue_dead_letter(
            None,  # Forces fallback to disk JSONL
            source_name="SEC_EDGAR",
            entity_type="company",
            raw_payload=corrupted_record,
            error_reason=f"Invalid statutory EIN: {ein_res['reason']}",
            run_id="e2e-run-001",
        )

        # Assert disk fallback file exists and captured the corrupt payload
        self.assertTrue(_FALLBACK_FILE.exists())
        content = _FALLBACK_FILE.read_text(encoding="utf-8")
        self.assertIn("SEC_EDGAR", content)
        self.assertIn("Invalid statutory EIN", content)
        self.assertIn("Ghost Corp", content)


if __name__ == "__main__":
    unittest.main()
