"""
DataExtraction — Unit Test Suite: Executive Title & Industry Classification (Agents 4 & 5)
=========================================================================================
Validates:
  1. Heuristic seniority classification (C_SUITE, FOUNDER, OWNER, VP, DIRECTOR, MANAGER, STAFF).
  2. Heuristic department classification (ENGINEERING, PRODUCT, SALES, MARKETING, FINANCE, HR, LEGAL, OPERATIONS, CUSTOMER_SUCCESS, EXECUTIVE).
  3. LLM executive title normalization with Ollama structured JSON and fallback.
  4. Heuristic industry taxonomy and NAICS code mapping.
  5. LLM industry classification with Ollama structured JSON and fallback.
  6. Asynchronous batch concurrency for both title and industry workflows.
  7. Person entity normalization enrichment (standardized_title, seniority_level, department).
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from packages.domain.normalizer import (
    classify_industries_batch,
    classify_industry,
    classify_industry_heuristic,
    classify_industry_llm,
    normalize_executive_title,
    normalize_executive_title_heuristic,
    normalize_executive_title_llm,
    normalize_executive_titles_batch,
    normalize_person,
)
from packages.infrastructure.ollama_client import ollama_client


class TestExecutiveTitleAndIndustryNormalizer(unittest.IsolatedAsyncioTestCase):
    """Test suite for title normalization and industry taxonomy classification."""

    def test_executive_title_seniority_heuristics(self):
        """Verifies deterministic seniority level resolution across standard hierarchies."""
        test_cases = [
            ("Chief Executive Officer", "C_SUITE"),
            ("CEO", "C_SUITE"),
            ("President", "C_SUITE"),
            ("Chief Technology Officer", "C_SUITE"),
            ("CTO", "C_SUITE"),
            ("Chief Financial Officer", "C_SUITE"),
            ("CFO", "C_SUITE"),
            ("Chief Information Security Officer", "C_SUITE"),
            ("CISO", "C_SUITE"),
            ("Founder & CEO", "C_SUITE"),
            ("Co-Founder", "FOUNDER"),
            ("Founding Partner", "FOUNDER"),
            ("Owner", "OWNER"),
            ("Proprietor", "OWNER"),
            ("Executive Vice President", "VP"),
            ("EVP Engineering", "VP"),
            ("Senior Vice President", "VP"),
            ("Vice President of Sales", "VP"),
            ("VP of Product", "VP"),
            ("Managing Director", "DIRECTOR"),
            ("Senior Director of Marketing", "DIRECTOR"),
            ("Head of People", "DIRECTOR"),
            ("Engineering Manager", "MANAGER"),
            ("Senior Product Manager", "MANAGER"),
            ("General Manager", "MANAGER"),
            ("Team Lead", "MANAGER"),
            ("Senior Software Engineer", "STAFF"),
            ("Data Analyst", "STAFF"),
            ("Strategy Consultant", "STAFF"),
            ("Marketing Associate", "STAFF"),
            ("Engineering Intern", "STAFF"),
            ("", "STAFF"),
            (None, "STAFF"),
        ]

        for raw_title, expected_seniority in test_cases:
            res = normalize_executive_title_heuristic(raw_title)
            self.assertEqual(
                res["seniority_level"],
                expected_seniority,
                f"Failed seniority mapping for: {raw_title}",
            )

    def test_executive_title_department_heuristics(self):
        """Verifies deterministic department resolution across organizational units."""
        test_cases = [
            ("VP of Software Engineering", "ENGINEERING"),
            ("Cloud Infrastructure Architect", "ENGINEERING"),
            ("Director of Product Management", "PRODUCT"),
            ("Lead UI/UX Designer", "PRODUCT"),
            ("Account Executive - Enterprise Sales", "SALES"),
            ("VP of Global Revenue", "SALES"),
            ("VP of Marketing & Brand Growth", "MARKETING"),
            ("Chief Financial Officer", "FINANCE"),
            ("Senior Accounting Manager", "FINANCE"),
            ("Chief People Officer", "HR"),
            ("Head of Talent Acquisition", "HR"),
            ("General Counsel & VP Legal", "LEGAL"),
            ("Chief Operating Officer", "OPERATIONS"),
            ("Supply Chain & Logistics Director", "OPERATIONS"),
            ("Director of Customer Success", "CUSTOMER_SUCCESS"),
            ("Chief Executive Officer", "EXECUTIVE"),
            ("President", "EXECUTIVE"),
            ("General Office Worker", "OTHER"),
        ]

        for raw_title, expected_dept in test_cases:
            res = normalize_executive_title_heuristic(raw_title)
            self.assertEqual(
                res["department"],
                expected_dept,
                f"Failed department mapping for: {raw_title}",
            )

    async def test_executive_title_llm_success(self):
        """Verifies LLM title classification when Ollama returns structured JSON."""
        mock_output = {
            "standardized_title": "Vice President of Artificial Intelligence",
            "seniority_level": "VP",
            "department": "ENGINEERING",
            "confidence": 0.98,
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_output

            res = await normalize_executive_title_llm("VP of AI Solutions", company_name="Acme AI")
            self.assertEqual(res["standardized_title"], "Vice President of Artificial Intelligence")
            self.assertEqual(res["seniority_level"], "VP")
            self.assertEqual(res["department"], "ENGINEERING")
            self.assertEqual(res["method"], "ollama_llama3.1:8b")
            self.assertEqual(res["confidence"], 0.98)

    async def test_executive_title_llm_fallback_on_error(self):
        """Verifies seamless fallback to heuristic title parser when Ollama fails."""
        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = None  # Simulate LLM timeout/failure

            res = await normalize_executive_title_llm("Senior Vice President of Product")
            self.assertEqual(res["seniority_level"], "VP")
            self.assertEqual(res["department"], "PRODUCT")
            self.assertEqual(res["method"], "deterministic_fallback")

    def test_industry_classification_heuristics(self):
        """Verifies deterministic mapping of business descriptions to standardized industries & NAICS."""
        test_cases = [
            ("Cloud enterprise SaaS and machine learning platform", "Computer Software", "5415", "Information Technology"),
            ("General hospital and specialized pediatric surgery clinic", "Healthcare", "6211", "Health Care"),
            ("Commercial investment banking and asset management fund", "Banking and Finance", "5221", "Financials"),
            ("Automotive components metal fabrication plant and machining", "Industrial Manufacturing & Transformation", "3320", "Industrials"),
            ("Aerospace defense systems federal military contractor", "Federal Contractor", "9281", "Industrials"),
            ("Online direct-to-consumer fashion apparel shop", "Retail", "4481", "Consumer Discretionary"),
            ("Utility scale solar energy and wind farm development", "Energy", "2211", "Energy"),
            ("Accredited state university and collegiate education", "Education", "6113", "Consumer Discretionary"),
            ("Commercial real estate leasing and property management", "Real Estate", "5312", "Real Estate"),
            ("Cellular mobile wireless telecommunications carrier", "Telecommunications", "5173", "Communication Services"),
            ("Commercial civil engineering and skyscraper builder", "Construction", "2362", "Industrials"),
            ("Global non-profit charitable foundation and NGO", "Nonprofits and Associations", "8132", "Other"),
            ("Corporate strategy consulting and management advisory", "Professional Services", "5411", "Professional, Scientific, and Technical Services"),
            (None, "Other", "9999", "Other"),
            ("", "Other", "9999", "Other"),
        ]

        for raw_text, expected_ind, expected_naics, expected_sec in test_cases:
            res = classify_industry_heuristic(raw_text)
            self.assertEqual(res["standardized_industry"], expected_ind, f"Failed industry for: {raw_text}")
            self.assertEqual(res["naics_code"], expected_naics, f"Failed NAICS for: {raw_text}")
            self.assertEqual(res["sector"], expected_sec, f"Failed sector for: {raw_text}")

    async def test_industry_classification_llm_success(self):
        """Verifies LLM industry classification when Ollama returns structured JSON."""
        mock_output = {
            "standardized_industry": "Banking and Finance",
            "naics_code": "5221",
            "sector": "Financials",
            "confidence": 0.96,
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_output

            res = await classify_industry_llm("Peer-to-peer decentralized micro-lending protocol", company_name="LoanFlow")
            self.assertEqual(res["standardized_industry"], "Banking and Finance")
            self.assertEqual(res["naics_code"], "5221")
            self.assertEqual(res["sector"], "Financials")
            self.assertEqual(res["method"], "ollama_llama3.1:8b")
            self.assertEqual(res["confidence"], 0.96)

    async def test_industry_classification_llm_fallback_on_error(self):
        """Verifies fallback to heuristic industry classifier when Ollama fails."""
        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = None  # Simulate LLM failure

            res = await classify_industry_llm("Medical devices and cardiovascular clinical implants")
            self.assertEqual(res["standardized_industry"], "Healthcare")
            self.assertEqual(res["naics_code"], "6211")
            self.assertEqual(res["method"], "deterministic_fallback")

    async def test_batch_title_normalization_concurrency(self):
        """Verifies batch title normalization processes concurrently with bounded semaphore."""
        titles = [
            "Chief Technology Officer",
            "VP of Engineering",
            "Director of Product",
            "Engineering Manager",
            "Lead Software Engineer",
        ]

        with patch("packages.domain.normalizer.normalize_executive_title_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {
                "standardized_title": "Standardized",
                "seniority_level": "STAFF",
                "department": "ENGINEERING",
                "confidence": 0.90,
                "method": "mock",
            }

            results = await normalize_executive_titles_batch(titles, concurrency=3)
            self.assertEqual(len(results), 5)
            self.assertEqual(mock_llm.call_count, 5)

    async def test_batch_industry_classification_concurrency(self):
        """Verifies batch industry classification processes concurrently with bounded semaphore."""
        industries = [
            "Enterprise cloud software",
            "Acute care clinical health",
            "Investment banking asset advisory",
            "Aerospace defense fabrication",
        ]

        with patch("packages.domain.normalizer.classify_industry_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = {
                "standardized_industry": "Computer Software",
                "naics_code": "5415",
                "sector": "Information Technology",
                "confidence": 0.90,
                "method": "mock",
            }

            results = await classify_industries_batch(industries, concurrency=2)
            self.assertEqual(len(results), 4)
            self.assertEqual(mock_llm.call_count, 4)

    def test_normalize_person_enrichment(self):
        """Verifies normalize_person automatically enriches standardized_title, seniority, and department."""
        raw_person = {
            "first_name": "Satya",
            "last_name": "Nadella",
            "title": "Chief Executive Officer",
            "company_name": "Microsoft Corporation",
            "email": "satya@microsoft.com",
        }

        norm = normalize_person(raw_person, source="INTERNAL_JSON")
        self.assertEqual(norm["first_name"], "Satya")
        self.assertEqual(norm["last_name"], "Nadella")
        self.assertEqual(norm["title"], "Chief Executive Officer")
        self.assertEqual(norm["standardized_title"], "Chief Executive Officer")
        self.assertEqual(norm["seniority_level"], "C_SUITE")
        self.assertEqual(norm["department"], "EXECUTIVE")
        self.assertEqual(norm["normalized_company_name"], "MICROSOFT")


if __name__ == "__main__":
    unittest.main()
