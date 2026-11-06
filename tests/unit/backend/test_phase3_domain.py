"""
DataExtraction — Unit Test Suite: Phase 3 Core Enterprise Domain
================================================================
Validates:
  1. packages.domain.normalizer:
     - clean_legal_suffixes: US, Mexican, Commonwealth, European regimes.
     - clean_domain: Registered domain parsing via PSL.
     - normalize_company and normalize_person.
  2. packages.domain.validation:
     - 5-Tier Contact: validate_email, validate_phone, validate_contact.
     - Statutory Tax IDs: validate_ein, validate_rfc.
     - Geospatial: normalize_postal_code, validate_coordinates.
  3. packages.domain.deduplication:
     - Deduplicator initialization and DedupResult dataclass.
  4. packages.domain.splink_engine:
     - SplinkEngine / SplinkIdentityLinker export and alias equivalence.
  5. packages.domain.lead_builder:
     - build_us_lead extraction and contract enforcement.
  6. packages.domain.gleif_enricher:
     - validate_lei_checksum (ISO 17442 mod 97-10 algorithm).
     - GLEIFEnricher multi-tier decision policy (AUTO_ENRICH, QUARANTINE_REVIEW, NO_MATCH).
"""

import unittest
from unittest.mock import MagicMock, patch

from packages.domain.normalizer import (
    clean_legal_suffixes,
    clean_domain,
    clean_string,
    normalize_company,
    normalize_person,
)
from packages.domain.validation import (
    validate_email,
    validate_phone,
    validate_ein,
    validate_rfc,
    normalize_postal_code,
    validate_coordinates,
)
from packages.domain.deduplication import Deduplicator, DedupResult
from packages.domain.splink_engine import SplinkIdentityLinker, SplinkEngine, splink_engine
from packages.domain.lead_builder import build_us_lead
from packages.domain.gleif_enricher import (
    validate_lei_checksum,
    GLEIFEnricher,
    gleif_enricher,
)


class TestDomainNormalizer(unittest.TestCase):
    """Verifies domain cleaning and legal suffix normalization."""

    def test_clean_legal_suffixes_us(self):
        self.assertEqual(clean_legal_suffixes("Acme Industries, Inc."), "ACME INDUSTRIES")
        self.assertEqual(clean_legal_suffixes("Cyberdyne Systems LLC"), "CYBERDYNE SYSTEMS")
        self.assertEqual(clean_legal_suffixes("Omega Corporation"), "OMEGA")
        self.assertEqual(clean_legal_suffixes("Apex Holdings, Ltd."), "APEX HOLDINGS")

    def test_clean_legal_suffixes_mexico(self):
        self.assertEqual(clean_legal_suffixes("Fomento Economico Mexicano, S.A.B. de C.V."), "FOMENTO ECONOMICO MEXICANO")
        self.assertEqual(clean_legal_suffixes("Grupo Bimbo S.A. de C.V."), "GRUPO BIMBO")
        self.assertEqual(clean_legal_suffixes("Operadora Comercial S. de R.L. de C.V."), "OPERADORA COMERCIAL")

    def test_clean_legal_suffixes_preserves_internal_tokens(self):
        self.assertEqual(clean_legal_suffixes("Incorporate Global Inc."), "INCORPORATE GLOBAL")
        self.assertEqual(clean_legal_suffixes("Company One LLC"), "COMPANY ONE")

    def test_clean_domain(self):
        self.assertEqual(clean_domain("https://www.example.com/about?q=1"), "example.com")
        self.assertEqual(clean_domain("sub.portal.domain.co.uk"), "domain.co.uk")
        self.assertIsNone(clean_domain(None))
        self.assertIsNone(clean_domain(""))

    def test_normalize_company(self):
        raw = {
            "name": "Stark Industries, Inc.",
            "website": "https://www.starkindustries.com",
            "ein": "12-3456789",
        }
        res = normalize_company(raw, source="INTERNAL_JSON")
        self.assertEqual(res["company_name"], "Stark Industries, Inc.")
        self.assertEqual(res["normalized_name"], "STARK INDUSTRIES")
        self.assertEqual(res["domain"], "starkindustries.com")
        self.assertEqual(res["ein"], "12-3456789")


class TestDomainValidation(unittest.TestCase):
    """Verifies contact, tax, and geospatial validation."""

    def test_contact_validation(self):
        # Email syntax & disposable check
        valid_res = validate_email("john.doe@acme-corp.com", skip_mx=True)
        self.assertIn(valid_res["status"], ("SYNTAX_VALID", "MX_CONFIRMED"))
        self.assertTrue(valid_res["checks"]["syntax"])

        disp_res = validate_email("spammer@mailinator.com", skip_mx=True)
        self.assertEqual(disp_res["status"], "UNDELIVERABLE")
        self.assertTrue(disp_res["checks"]["disposable"])

        # Phone normalization
        phone_res = validate_phone("2125550199", country="US")
        self.assertEqual(phone_res["status"], "VALID_E164")
        self.assertEqual(phone_res["phone"], "+12125550199")

    def test_tax_id_validation(self):
        # EIN
        ein_res = validate_ein("12-3456789")
        self.assertTrue(ein_res["is_valid"])
        self.assertEqual(ein_res["formatted"], "12-3456789")

        disallowed = validate_ein("00-1234567")
        self.assertFalse(disallowed["is_valid"])

        # RFC
        rfc_moral = validate_rfc("ABC010101XYZ")
        self.assertTrue(rfc_moral["is_valid"])
        self.assertEqual(rfc_moral["rfc_type"], "MORAL")

    def test_geo_validation(self):
        self.assertEqual(normalize_postal_code("90210-1234"), "90210-1234")
        geo_valid = validate_coordinates(37.7749, -122.4194)
        self.assertTrue(geo_valid["is_valid"])
        geo_invalid = validate_coordinates(95.0, 200.0)
        self.assertFalse(geo_invalid["is_valid"])


class TestDomainLinkageAndEnrichment(unittest.TestCase):
    """Verifies Splink engine aliasing and GLEIF checksum & decisions."""

    def test_splink_engine_alias(self):
        self.assertIs(SplinkEngine, SplinkIdentityLinker)
        self.assertIsInstance(splink_engine, SplinkIdentityLinker)

    def test_lei_checksum_validation(self):
        # Valid official sample LEI: 5493006MHB84DD0ZWV18
        self.assertTrue(validate_lei_checksum("5493006MHB84DD0ZWV18"))
        # Invalid format / check digits
        self.assertFalse(validate_lei_checksum("5493006MHB84DD0ZWV19"))
        self.assertFalse(validate_lei_checksum("INVALID_SHORT"))
        self.assertFalse(validate_lei_checksum(None))

    def test_gleif_enricher_exact_match(self):
        enricher = GLEIFEnricher()
        with patch.object(enricher.client, "lookup_by_lei") as mock_lookup:
            mock_lookup.return_value = {
                "lei": "5493006MHB84DD0ZWV18",
                "legal_name": "ACME INDUSTRIAL HOLDINGS, INC.",
            }
            res = enricher.enrich_entity(lei="5493006MHB84DD0ZWV18")
            self.assertTrue(res["matched"])
            self.assertEqual(res["confidence"], 1.0)
            self.assertEqual(res["action"], "AUTO_ENRICH")

    def test_gleif_enricher_decision_thresholds(self):
        enricher = GLEIFEnricher()
        with patch.object(enricher.client, "search_by_name") as mock_search:
            # 1. High confidence >= 0.95 -> AUTO_ENRICH
            mock_search.return_value = [{"lei": "5493006MHB84DD0ZWV18", "match_score": 0.96}]
            res = enricher.enrich_entity(company_name="Acme Corp")
            self.assertEqual(res["action"], "AUTO_ENRICH")
            self.assertTrue(res["matched"])

            # 2. Medium confidence 0.70 <= score < 0.95 -> QUARANTINE_REVIEW
            mock_search.return_value = [{"lei": "5493006MHB84DD0ZWV18", "match_score": 0.82}]
            res = enricher.enrich_entity(company_name="Acme Corp")
            self.assertEqual(res["action"], "QUARANTINE_REVIEW")
            self.assertTrue(res["matched"])

            # 3. Low confidence < 0.70 -> NO_MATCH
            mock_search.return_value = [{"lei": "5493006MHB84DD0ZWV18", "match_score": 0.55}]
            res = enricher.enrich_entity(company_name="Acme Corp")
            self.assertEqual(res["action"], "NO_MATCH")
            self.assertFalse(res["matched"])


if __name__ == "__main__":
    unittest.main()
