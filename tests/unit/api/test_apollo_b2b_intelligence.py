"""
Unit & Integration Tests for Enterprise Apollo.io B2B Intelligence Features
==========================================================================
Tests:
  1. Standardized 28 Macro Industry Taxonomy API (/api/prospecting/taxonomy)
  2. Faceted Revenue & Headcount Bracket Filtering (/api/search/companies)
  3. Technographic Sniffer Stack Detection Catalog
  4. ATS Job Scraper Normalization Logic
"""

import pytest
from fastapi.testclient import TestClient

from packages.api.main import app
from packages.scrapers.jobs.ats_job_scraper import normalize_seniority, normalize_department
from packages.scrapers.technographics.technographic_sniffer import CLOUD_PATTERNS, EMAIL_PATTERNS, CRM_MARKETING_PATTERNS


@pytest.fixture
def client():
    return TestClient(app)


class TestApolloB2BIntelligence:
    def test_taxonomy_endpoint_contract(self, client):
        """Verifies GET /api/prospecting/taxonomy returns macro and sub-industries."""
        response = client.get("/api/prospecting/taxonomy")
        assert response.status_code == 200
        data = response.json()
        assert "total_macro_industries" in data
        assert "total_sub_industries" in data
        assert data["total_macro_industries"] > 0
        assert data["total_sub_industries"] > 0

        # Verify Healthcare & Life Sciences presence
        macro_names = [m["macro_industry"] for m in data["taxonomy"]]
        assert any("Healthcare" in m for m in macro_names)

        # Verify sub-industry schema
        first_group = data["taxonomy"][0]
        assert "sub_industries" in first_group
        first_sub = first_group["sub_industries"][0]
        assert "sub_industry" in first_sub
        assert "naics_code" in first_sub
        assert "sic_code" in first_sub

    def test_faceted_companies_search_with_brackets(self, client):
        """Verifies POST /api/search/companies handles revenue and headcount brackets."""
        payload = {
            "revenue_brackets": ["$10M-$50M"],
            "headcount_brackets": ["201-500"],
            "limit": 5,
        }
        response = client.post("/api/search/companies", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "total" in data

        if data["results"]:
            first = data["results"][0]
            assert "revenue_bracket" in first
            assert "headcount_bracket" in first
            assert first["revenue_bracket"] == "$10M-$50M"
            assert first["headcount_bracket"] == "201-500"

    def test_ats_job_seniority_normalization(self):
        """Tests deterministic normalization of job titles into Apollo seniority levels."""
        assert normalize_seniority("Chief Technology Officer") == "C_SUITE"
        assert normalize_seniority("VP of Sales") == "VP"
        assert normalize_seniority("Director of Engineering") == "DIRECTOR"
        assert normalize_seniority("Engineering Manager") == "MANAGER"
        assert normalize_seniority("Senior Software Engineer") == "SENIOR"
        assert normalize_seniority("Junior Analyst") == "ENTRY"
        assert normalize_seniority("Nurse Practitioner") == "INDIVIDUAL_CONTRIBUTOR"

    def test_ats_job_department_normalization(self):
        """Tests deterministic normalization of job titles into standard departments."""
        assert normalize_department("Tech", "Full Stack Developer") == "ENGINEERING_TECH"
        assert normalize_department("Commercial", "Account Executive") == "SALES"
        assert normalize_department("Demand Gen", "Growth Marketing Lead") == "MARKETING"
        assert normalize_department("Accounting", "Senior Accountant") == "FINANCE"
        assert normalize_department("Talent", "Technical Recruiter") == "HUMAN_RESOURCES"
        assert normalize_department("Care", "Registered Homecare Nurse") == "HEALTHCARE_CLINICAL"

    def test_technographic_catalog_integrity(self):
        """Verifies signature patterns for major clouds, email providers, and CRMs."""
        assert "Amazon Web Services (AWS)" in CLOUD_PATTERNS
        assert "Google Workspace" in EMAIL_PATTERNS
        assert "Microsoft 365" in EMAIL_PATTERNS
        assert "Salesforce" in CRM_MARKETING_PATTERNS
        assert "HubSpot" in CRM_MARKETING_PATTERNS
