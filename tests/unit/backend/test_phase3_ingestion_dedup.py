"""
Phase 3 Test Suite: Data Ingestion & Entity Resolution Hardening

Comprehensive verification of:
1. EnterpriseHttpClient: connection pooling, exponential backoff, SEC rate limiting & Fair Access headers.
2. Zero Synthetic Executive Officer generation across SEC EDGAR, ProPublica, FDIC, SAM.gov, USASpending.
3. Multi-tier Entity Resolution in Deduplicator: deterministic statutory IDs (EIN, RFC, CIK, NPI) precedence over domain.
4. Non-destructive Provenance Merging in source_records JSONB.
5. Executive Career History Tracking upon role/company transition.
6. Cache Pre-warming via warm_company_cache.
"""

import json
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

# Ensure imports work in DataExtraction monorepo
import sys
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

from http_client import EnterpriseHttpClient, RateLimiter, get_http_client
from deduplicator import Deduplicator, DedupResult, _merge_updates, _safe_json_loads
from fetch_sec_edgar import _make_org_lead, _make_officer_lead
from fetch_propublica import _make_lead as make_propublica_lead
from fetch_fdic import fetch_fdic
from fetch_sam_gov import _make_lead as make_sam_lead
from fetch_usaspending import _make_lead as make_usaspending_lead


class TestEnterpriseHttpClient(unittest.TestCase):
    """Verifies HTTP ingestion client enterprise resilience and rate limiting."""

    def test_http_client_singleton_and_pooling(self):
        client = get_http_client()
        self.assertIsInstance(client, EnterpriseHttpClient)
        self.assertIsNotNone(client.session)
        # Check HTTP adapters mounted for http and https
        adapter_https = client.session.adapters.get("https://")
        self.assertIsNotNone(adapter_https)
        self.assertEqual(adapter_https._pool_connections, 25)
        self.assertEqual(adapter_https._pool_maxsize, 50)

    def test_sec_rate_limiter_enforcement(self):
        limiter = RateLimiter(max_rate_per_sec=8.0)
        start = time.time()
        # Acquire 3 tokens
        for _ in range(3):
            limiter.acquire("data.sec.gov")
        elapsed = time.time() - start
        # 3 calls at 8 RPS takes at least ~0.20 seconds
        self.assertGreaterEqual(elapsed, 0.20)

    def test_sec_fair_access_user_agent_injection(self):
        client = EnterpriseHttpClient()
        with patch.object(client.session, "send") as mock_send:
            mock_resp = requests.Response()
            mock_resp.status_code = 200
            mock_resp._content = b'{"status": "ok"}'
            mock_send.return_value = mock_resp

            resp = client.get("https://data.sec.gov/submissions/CIK0000320193.json")
            self.assertEqual(resp.status_code, 200)

            # Verify User-Agent header passed to send contains Sample Company / email format
            sent_request = mock_send.call_args[0][0]
            ua = sent_request.headers.get("User-Agent", "")
            self.assertIn("@", ua)
            self.assertIn("OneExtraction", ua)

    def test_exponential_backoff_retry_on_server_error(self):
        client = EnterpriseHttpClient(max_retries=3, backoff_factor=0.05)
        # Verify urllib3 Retry configuration on adapter
        adapter = client.session.adapters.get("https://")
        retries = adapter.max_retries
        self.assertEqual(retries.total, 3)
        self.assertIn(429, retries.status_forcelist)
        self.assertIn(503, retries.status_forcelist)
        self.assertIn(504, retries.status_forcelist)


class TestZeroSyntheticExecutiveOfficerGeneration(unittest.TestCase):
    """Verifies that no fetcher generates fake Corporate Officer / Director personas."""

    def test_sec_edgar_clean_organization_lead_when_no_officers(self):
        """When an SEC company filing has no officers, store clean org lead with NO synthetic title."""
        contact_info = {
            "sic": "3571",
            "state_code": "CA",
            "domain": "apple.com",
            "address": {"city": "Cupertino", "stateOrCountry": "CA"},
        }
        contact = {"email": None, "phone": "+14089961010"}
        lead = _make_org_lead(
            cik="0000320193",
            name="APPLE INC",
            ticker="AAPL",
            contact_info=contact_info,
            contact=contact,
            score=90
        )
        self.assertEqual(lead["id"], "sec_0000320193_org")
        self.assertIsNone(lead["full_name"])
        self.assertIsNone(lead["first_name"])
        self.assertIsNone(lead["last_name"])
        self.assertIsNone(lead["title"])
        self.assertIsNone(lead["standardized_title"])
        self.assertIsNone(lead["seniority_level"])
        self.assertIsNone(lead["department"])
        self.assertIsNone(lead["is_current"])
        # Verify person payload is explicitly marked as organization-level
        person_obj = json.loads(lead["person"])
        self.assertTrue(person_obj.get("is_organization_level"))
        self.assertNotIn("Corporate Officer", lead["person"])

    def test_sec_edgar_real_officer_lead(self):
        """When SEC filing contains real officers, store real officer lead."""
        contact_info = {
            "sic": "3571",
            "state_code": "CA",
            "domain": "apple.com",
            "address": {"city": "Cupertino", "stateOrCountry": "CA"},
        }
        contact = {"email": "tim.cook@apple.com", "phone": "+14089961010"}
        officer = {"name": "Tim Cook", "title": "Chief Executive Officer"}
        lead = _make_officer_lead(
            cik="0000320193",
            name="APPLE INC",
            ticker="AAPL",
            contact_info=contact_info,
            off=officer,
            contact=contact,
            score=95
        )
        self.assertEqual(lead["full_name"], "Tim Cook")
        self.assertEqual(lead["first_name"], "Tim")
        self.assertEqual(lead["last_name"], "Cook")
        self.assertEqual(lead["title"], "Chief Executive Officer")
        self.assertEqual(lead["standardized_title"], "Chief Executive Officer")
        self.assertEqual(lead["seniority_level"], "C_SUITE")
        self.assertTrue(lead["is_current"])

    def test_propublica_zero_synthetic_officer(self):
        """ProPublica without officer produces org lead, NOT fake Executive Director."""
        org = {
            "name": "COMMUNITY CHARITY FOUNDATION",
            "ein": "123456789",
            "city": "Austin",
            "state": "TX",
        }
        lead = make_propublica_lead(org, officer=None)
        self.assertIsNotNone(lead)
        self.assertEqual(lead["id"], "pp_123456789_org")
        self.assertIsNone(lead["full_name"])
        self.assertIsNone(lead["title"])
        self.assertIsNone(lead["standardized_title"])
        self.assertIsNone(lead["seniority_level"])
        self.assertIsNone(lead["department"])
        person_obj = json.loads(lead["person"])
        self.assertTrue(person_obj.get("is_organization_level"))

        # Real officer
        officer = {"name": "Sarah Connor", "title": "Board President", "compensation": 120000}
        lead_with_officer = make_propublica_lead(org, officer=officer)
        self.assertEqual(lead_with_officer["full_name"], "Sarah Connor")
        self.assertEqual(lead_with_officer["title"], "Board President")
        self.assertEqual(lead_with_officer["seniority_level"], "DIRECTOR")

    def test_sam_gov_zero_synthetic_poc(self):
        """SAM.gov entity with no POC produces org lead, NOT fake Point of Contact."""
        entity = {
            "registration": {
                "legalBusinessName": "DEFENSE LOGISTICS CORP",
                "ueiSAM": "XYZ123456789",
                "primaryNaics": "541512",
                "physicalAddress": {"city": "Huntsville", "stateOrProvinceCode": "AL", "zipCode": "35801"}
            }
        }
        lead = make_sam_lead(entity)
        self.assertIsNotNone(lead)
        self.assertIsNone(lead["full_name"])
        self.assertIsNone(lead["title"])
        self.assertIsNone(lead["standardized_title"])
        self.assertIsNone(lead["seniority_level"])
        self.assertIsNone(lead["department"])
        person_obj = json.loads(lead["person"])
        self.assertTrue(person_obj.get("is_organization_level"))

    def test_usaspending_zero_synthetic_officer(self):
        """USASpending contractor produces org lead, NOT synthetic Primary Contact."""
        award = {
            "Recipient Name": "LOCKHEED MARTIN CORP",
            "recipient_id": "rec_001",
            "NAICS Code": "336411",
            "NAICS Description": "Aircraft Manufacturing",
            "Place of Performance City Name": "Bethesda",
            "Place of Performance State Code": "MD",
            "Place of Performance Zip5": "20817",
            "Award Amount": 5000000
        }
        lead = make_usaspending_lead(award)
        self.assertIsNotNone(lead)
        self.assertIsNone(lead["full_name"])
        self.assertIsNone(lead["title"])
        self.assertIsNone(lead["standardized_title"])
        self.assertIsNone(lead["seniority_level"])
        person_obj = json.loads(lead["person"])
        self.assertTrue(person_obj.get("is_organization_level"))


class TestEntityResolutionAndDeduplicator(unittest.TestCase):
    """Verifies multi-tier entity resolution, deterministic ID precedence, and career tracking."""

    def setUp(self):
        # In-memory mock connection for unit testing
        self.mock_conn = MagicMock()
        self.dedup = Deduplicator(self.mock_conn, run_id="test_run_01")

    def test_deterministic_id_precedence_over_domain(self):
        """
        Subsidaries or franchises sharing a parent domain with different EINs/RFCs
        MUST NOT be collapsed into the same canonical company.
        """
        # Company A: Marriott Downtown with EIN 11-1111111 and domain marriott.com
        comp_a = {
            "id": "co_marriott_downtown",
            "name": "Marriott Downtown LLC",
            "normalized_name": "MARRIOTT DOWNTOWN",
            "ein": "11-1111111",
            "domain": "marriott.com",
            "state_code": "NY",
            "api_source": "IRS"
        }
        # Pre-cache Company A
        res_a = self.dedup.check_company(comp_a)
        self.assertEqual(res_a.action, "insert")
        self.assertEqual(res_a.id, "co_marriott_downtown")

        # Company B: Marriott Airport with EIN 22-2222222 and SAME domain marriott.com
        # Because EIN 22-2222222 is searched before domain, it must NOT resolve to Company A!
        comp_b = {
            "id": "co_marriott_airport",
            "name": "Marriott Airport LLC",
            "normalized_name": "MARRIOTT AIRPORT",
            "ein": "22-2222222",
            "domain": "marriott.com",
            "state_code": "CA",
            "api_source": "FDIC"
        }
        res_b = self.dedup.check_company(comp_b)
        # Because EIN differs and is not in DB, it should be treated as a separate INSERT
        self.assertEqual(res_b.action, "insert")
        self.assertEqual(res_b.id, "co_marriott_airport")
        self.assertNotEqual(res_a.id, res_b.id)

    def test_ein_match_triggers_update(self):
        """Matching by exact EIN triggers update."""
        comp_1 = {
            "id": "co_tech_corp",
            "name": "Tech Corp",
            "ein": "99-8887776",
            "domain": "techcorp.io",
            "api_source": "SEC"
        }
        self.dedup.check_company(comp_1)

        # Incoming record with same EIN but different source and new phone
        comp_2 = {
            "name": "Tech Corp Global",
            "ein": "99-8887776",
            "phone": "+14155551234",
            "api_source": "SAM_GOV"
        }
        res_2 = self.dedup.check_company(comp_2)
        self.assertEqual(res_2.action, "update")
        self.assertEqual(res_2.id, "co_tech_corp")
        self.assertEqual(res_2.match_field, "ein")
        self.assertEqual(res_2.updates.get("phone"), "+14155551234")

    def test_non_destructive_provenance_merge(self):
        """Existing non-null data is preserved while new sources are appended to source_records."""
        existing = {
            "id": "co_001",
            "name": "Acme Industries",
            "phone": "+12125550000",
            "domain": "acme.com",
            "data_quality_score": 75,
            "api_source": "DENUE",
            "source_records": json.dumps([{
                "source": "DENUE",
                "id": "den_100",
                "recorded_at": "2026-01-01T00:00:00Z",
                "is_primary": True
            }])
        }
        incoming = {
            "id": "siem_200",
            "name": "Acme Industries SA",
            "phone": None,  # Should NOT overwrite existing phone
            "website": "https://acme.com",  # Should fill in missing website
            "data_quality_score": 85,  # Higher score promoted
            "api_source": "SIEM"
        }

        updates = _merge_updates(existing, incoming, entity_type="company")
        self.assertEqual(updates.get("website"), "https://acme.com")
        self.assertEqual(updates.get("data_quality_score"), 85)
        self.assertNotIn("phone", updates)  # Existing phone was preserved

        # Verify source_records provenance appended
        sources = json.loads(updates["source_records"])
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0]["source"], "DENUE")
        self.assertEqual(sources[1]["source"], "SIEM")
        self.assertEqual(updates.get("source_count"), 2)

    def test_executive_career_history_tracking(self):
        """When an executive moves to a new company/title, the old position is archived to career_history."""
        # Existing executive record
        existing_exec = {
            "id": "per_exec_123",
            "full_name": "Satya Nadella",
            "title": "Executive Vice President",
            "standardized_title": "EVP",
            "company_id": "co_cloud_div",
            "company_name": "Microsoft Cloud & Enterprise",
            "seniority_level": "VP",
            "linkedin_url": "https://linkedin.com/in/satyanadella",
            "email": "satya@microsoft.com",
            "career_history": "[]",
            "is_current": True
        }

        # Mock DB fetch to return existing record
        self.dedup._fetch_person = MagicMock(return_value=existing_exec)
        self.dedup._find_person = MagicMock(return_value=existing_exec)

        # Incoming new job: Promoted to CEO of Microsoft Corporation
        incoming_job = {
            "linkedin_url": "https://linkedin.com/in/satyanadella",
            "full_name": "Satya Nadella",
            "title": "Chief Executive Officer",
            "standardized_title": "CEO",
            "company_id": "co_microsoft_corp",
            "company_name": "Microsoft Corporation",
            "seniority_level": "C_SUITE",
            "is_current": True
        }

        res = self.dedup.check_person(incoming_job)
        self.assertEqual(res.action, "update")
        self.assertEqual(res.id, "per_exec_123")
        self.assertEqual(res.updates.get("title"), "Chief Executive Officer")
        self.assertEqual(res.updates.get("company_id"), "co_microsoft_corp")
        self.assertTrue(res.updates.get("is_current"))

        # Verify career_history contains archived previous role
        career = json.loads(res.updates.get("career_history"))
        self.assertEqual(len(career), 1)
        self.assertEqual(career[0]["title"], "Executive Vice President")
        self.assertEqual(career[0]["company_id"], "co_cloud_div")
        self.assertFalse(career[0]["is_current"])

    def test_warm_company_cache(self):
        """Pre-warms company cache for high-throughput batching."""
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("co_1", "apple.com", "94-2404110", "0000320193"),
            ("co_2", "google.com", "77-0493581", "0001652044"),
        ]
        self.mock_conn.cursor.return_value = mock_cur

        self.dedup.warm_company_cache(
            domains=["apple.com", "google.com"],
            eins=["94-2404110", "77-0493581"],
            ciks=["0000320193", "0001652044"]
        )

        stats = self.dedup.cache_stats()
        self.assertGreater(stats["company_cache_size"], 0)
        self.assertIn("domain:apple.com", self.dedup._company_cache)
        self.assertEqual(self.dedup._company_cache["domain:apple.com"], "co_1")
        self.assertIn("ein:77-0493581", self.dedup._company_cache)
        self.assertEqual(self.dedup._company_cache["ein:77-0493581"], "co_2")


if __name__ == "__main__":
    unittest.main()
