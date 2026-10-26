#!/usr/bin/env python3
"""
Unit and Integration Test Suite for Phase 2: Data Validation & Quality Hardening.

Validates:
1. Tax ID Validator: US EIN campus prefix allocation, dummy rejection, Mexican RFC syntax & personality types.
2. Geographic & Address Validator: Leading-zero restoration for US ZIP & Mexican CP, CONUS, Alaska, Hawaii,
   Puerto Rico, Guam, Mexico boundary validation, and swapped coordinate detection.
3. Contact Validator: Evidence-based email verification tiers, tldextract registered domain resolution,
   and Google phonenumbers canonical E.164 parsing and line-type classification.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure paths resolve properly in DataExtraction monorepo
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

from tax_validator import (
    validate_ein,
    validate_rfc,
    validate_tax_id,
    VALID_IRS_EIN_PREFIXES,
    DISALLOWED_IRS_EIN_PREFIXES,
)
from geo_validator import (
    normalize_postal_code,
    validate_coordinates,
)
from contact_validator import (
    validate_email,
    validate_phone,
    validate_contact,
    contact_is_usable,
    lead_score_from_contact,
    extract_registered_domain,
    normalise_linkedin,
)


class TestTaxValidator(unittest.TestCase):
    """Tests US EIN and Mexican RFC validation and normalization rules."""

    def test_valid_ein_formats(self):
        """Valid EINs with recognized IRS campus prefixes should pass."""
        # Andover: 10, 12; Cincinnati: 30, 32; National Internet: 20, 26, 45, 81
        valid_samples = [
            ("12-3456789", "12-3456789"),
            ("301234567", "30-1234567"),
            (" 45-9876543 ", "45-9876543"),
            ("81-0000001", "81-0000001"),
        ]
        for raw, expected_formatted in valid_samples:
            res = validate_ein(raw)
            self.assertTrue(res["is_valid"], f"Failed for {raw}: {res.get('reason')}")
            self.assertEqual(res["formatted"], expected_formatted)
            self.assertEqual(res["reason"], "VALID_IRS_EIN")

    def test_ein_leading_zero_prefix(self):
        """EINs starting with '01', '02', '03', '04', '05', '06' (Brookhaven/Austin) are valid."""
        res = validate_ein("01-2345678")
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["prefix"], "01")

        res = validate_ein("06-9876543")
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["prefix"], "06")

    def test_ein_invalid_length(self):
        """EINs with fewer or more than 9 digits must be rejected."""
        short_res = validate_ein("12-34567")
        self.assertFalse(short_res["is_valid"])
        self.assertIn("INVALID_LENGTH", short_res["reason"])

        long_res = validate_ein("12-34567890")
        self.assertFalse(long_res["is_valid"])
        self.assertIn("INVALID_LENGTH", long_res["reason"])

    def test_ein_repetitive_dummy_digits(self):
        """Repeated dummy digits like 000000000, 111111111, 999999999 must be rejected."""
        dummy_samples = ["00-0000000", "11-1111111", "99-9999999", "333333333"]
        for dummy in dummy_samples:
            res = validate_ein(dummy)
            self.assertFalse(res["is_valid"], f"Should reject dummy {dummy}")
            self.assertEqual(res["reason"], "REPETITIVE_DUMMY_DIGITS")

    def test_ein_disallowed_prefix(self):
        """Prefixes never assigned by IRS (e.g. 00, 07, 19, 79) must be rejected."""
        for pfx in ("00", "07", "19", "49", "79"):
            res = validate_ein(f"{pfx}-1234567")
            self.assertFalse(res["is_valid"], f"Should reject prefix {pfx}")
            self.assertIn("INVALID_IRS_PREFIX", res["reason"])

    def test_valid_rfc_moral(self):
        """Mexican RFC for Persona Moral (12 alphanumeric characters) must pass."""
        # 3 letters + 6 date digits + 3 homoclave
        samples = ["ABC010101XYZ", "IMS421231I45", "SAT970701NN3"]
        for rfc in samples:
            res = validate_rfc(rfc)
            self.assertTrue(res["is_valid"], f"Failed for {rfc}: {res.get('reason')}")
            self.assertEqual(res["rfc_type"], "MORAL")
            self.assertFalse(res["is_generic"])

    def test_valid_rfc_fisica(self):
        """Mexican RFC for Persona Física (13 alphanumeric characters) must pass."""
        # 4 letters + 6 date digits + 3 homoclave
        samples = ["GARM800101HR4", "PEAR9001011A2"]
        for rfc in samples:
            res = validate_rfc(rfc)
            self.assertTrue(res["is_valid"], f"Failed for {rfc}: {res.get('reason')}")
            self.assertEqual(res["rfc_type"], "FISICA")
            self.assertFalse(res["is_generic"])

    def test_generic_rfc(self):
        """Generic RFCs for general public (XAXX010101000) must be identified."""
        res = validate_rfc("XAXX010101000")
        self.assertTrue(res["is_valid"])
        self.assertTrue(res["is_generic"])
        self.assertEqual(res["rfc_type"], "GENERIC")

    def test_invalid_rfc(self):
        """Malformed or wrong length RFCs must be rejected."""
        res = validate_rfc("INVALID")
        self.assertFalse(res["is_valid"])

        res2 = validate_rfc("ABCD1234567890")  # 14 chars
        self.assertFalse(res2["is_valid"])

    def test_validate_tax_id_dispatcher(self):
        """Unified validate_tax_id dispatcher should correctly route US and MX."""
        us_res = validate_tax_id("12-3456789", country="US")
        self.assertEqual(us_res["country"], "US")
        self.assertEqual(us_res["identifier_type"], "EIN")
        self.assertTrue(us_res["is_valid"])

        mx_res = validate_tax_id("ABC010101XYZ", country="MX")
        self.assertEqual(mx_res["country"], "MX")
        self.assertEqual(mx_res["identifier_type"], "RFC")
        self.assertTrue(mx_res["is_valid"])


class TestGeoValidator(unittest.TestCase):
    """Tests postal code leading-zero restoration and geographic boundary validation."""

    def test_normalize_us_postal_code_leading_zero(self):
        """Leading zeros stripped from East Coast US postal codes must be restored."""
        test_cases = [
            ("1234", "01234"),      # Massachusetts / New England
            ("2138", "02138"),      # Cambridge, MA
            ("7030", "07030"),      # Hoboken, NJ
            ("90210", "90210"),    # Beverly Hills, CA
        ]
        for raw, expected in test_cases:
            normalized = normalize_postal_code(raw, country="US")
            self.assertEqual(normalized, expected, f"Failed for {raw}")

    def test_normalize_us_postal_code_zip9(self):
        """ZIP+4 formatted codes should be preserved or properly formatted."""
        self.assertEqual(normalize_postal_code("12345-6789", country="US"), "12345-6789")
        self.assertEqual(normalize_postal_code("123456789", country="US"), "12345-6789")

    def test_normalize_us_postal_code_invalid(self):
        """All zero or invalid postal codes must return None."""
        self.assertIsNone(normalize_postal_code("00000", country="US"))
        self.assertIsNone(normalize_postal_code("ABCDE", country="US"))
        self.assertIsNone(normalize_postal_code(None, country="US"))
        self.assertIsNone(normalize_postal_code("", country="US"))

    def test_normalize_mexico_postal_code_leading_zero(self):
        """Mexican postal codes (Código Postal) must have leading zeros restored."""
        test_cases = [
            ("1000", "01000"),      # Álvaro Obregón, CDMX
            ("64000", "64000"),    # Monterrey, NL
        ]
        for raw, expected in test_cases:
            normalized = normalize_postal_code(raw, country="MX")
            self.assertEqual(normalized, expected, f"Failed for {raw}")

    def test_validate_coordinates_conus(self):
        """Coordinates inside the contiguous United States should validate as CONUS."""
        # Austin, TX: (30.2672, -97.7431)
        res = validate_coordinates(30.2672, -97.7431, country="US")
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["region"], "CONUS")

        # New York, NY: (40.7128, -74.0060)
        res = validate_coordinates(40.7128, -74.0060, country="US")
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["region"], "CONUS")

    def test_validate_coordinates_non_contiguous_us(self):
        """Alaska, Hawaii, Puerto Rico, and Guam must validate without being rejected."""
        # Anchorage, Alaska: (61.2181, -149.9003)
        ak = validate_coordinates(61.2181, -149.9003, country="US")
        self.assertTrue(ak["is_valid"])
        self.assertEqual(ak["region"], "ALASKA")

        # Honolulu, Hawaii: (21.3069, -157.8583)
        hi = validate_coordinates(21.3069, -157.8583, country="US")
        self.assertTrue(hi["is_valid"])
        self.assertEqual(hi["region"], "HAWAII")

        # San Juan, Puerto Rico: (18.4655, -66.1057)
        pr = validate_coordinates(18.4655, -66.1057, country="US")
        self.assertTrue(pr["is_valid"])
        self.assertEqual(pr["region"], "PUERTO_RICO_USVI")

        # Hagåtña, Guam: (13.4757, 144.7489)
        gu = validate_coordinates(13.4757, 144.7489, country="US")
        self.assertTrue(gu["is_valid"])
        self.assertEqual(gu["region"], "GUAM_CNMI")

    def test_validate_coordinates_swapped(self):
        """Inverted latitude and longitude (lat negative, lon positive in US) must be flagged."""
        # Swapped Austin, TX: lat=-97.7431, lon=30.2672
        res = validate_coordinates(-97.7431, 30.2672, country="US")
        self.assertFalse(res["is_valid"])
        self.assertTrue(res["is_swapped"])
        self.assertAlmostEqual(res["suggested_latitude"], 30.2672)
        self.assertAlmostEqual(res["suggested_longitude"], -97.7431)

    def test_validate_coordinates_mexico(self):
        """Coordinates in Mexico should validate as MEXICO."""
        # Mexico City: (19.4326, -99.1332)
        res = validate_coordinates(19.4326, -99.1332, country="MX")
        self.assertTrue(res["is_valid"])
        self.assertEqual(res["region"], "MEXICO")

    def test_validate_coordinates_null_island_and_invalid(self):
        """Null Island (0,0) and out-of-bounds coordinates must be rejected."""
        null_res = validate_coordinates(0.0, 0.0)
        self.assertFalse(null_res["is_valid"])
        self.assertEqual(null_res["reason"], "NULL_ISLAND_PLACEHOLDER")

        oob_res = validate_coordinates(95.0, -100.0)
        self.assertFalse(oob_res["is_valid"])
        self.assertEqual(oob_res["reason"], "OUT_OF_GLOBAL_BOUNDS")


class TestContactValidator(unittest.TestCase):
    """Tests evidence-based email tiers, tldextract domain parsing, and Google phonenumbers."""

    def test_extract_registered_domain_cctld(self):
        """tldextract must cleanly extract the registered root domain across complex ccTLDs."""
        test_cases = [
            ("https://subdomain.example.co.uk/path", "example.co.uk"),
            ("https://portal.empresa.com.mx/login", "empresa.com.mx"),
            ("https://tramites.sat.gob.mx", "sat.gob.mx"),
            ("https://app.stripe.com/dashboard", "stripe.com"),
            ("contact@engineering.firm.com", "firm.com"),
        ]
        for url_or_domain, expected in test_cases:
            root = extract_registered_domain(url_or_domain)
            self.assertEqual(root, expected, f"Failed for {url_or_domain}")

    def test_validate_email_syntax_and_missing(self):
        """Invalid syntax and missing emails must be tagged cleanly."""
        missing = validate_email(None)
        self.assertEqual(missing["status"], "MISSING")

        invalid = validate_email("not-an-email")
        self.assertEqual(invalid["status"], "INVALID")
        self.assertEqual(invalid["confidence_score"], 0)

    def test_validate_email_disposable_domain(self):
        """Emails with disposable domains must be classified as UNDELIVERABLE with 0 score."""
        disposable_samples = [
            "test@mailinator.com",
            "fakeuser@tempmail.com",
            "john@guerrillamail.com",
            "anon@sharklasers.com",
        ]
        for email in disposable_samples:
            res = validate_email(email)
            self.assertEqual(res["status"], "UNDELIVERABLE", f"Failed for {email}")
            self.assertEqual(res["evidence_level"], "DISPOSABLE_DOMAIN")
            self.assertEqual(res["confidence_score"], 0)

    def test_validate_email_role_account(self):
        """Departmental role addresses (info@, support@) must be classified as RISKY."""
        role_samples = [
            "info@google.com",
            "support@microsoft.com",
            "sales@apple.com",
            "admin@amazon.com",
        ]
        for email in role_samples:
            res = validate_email(email, skip_mx=True)
            self.assertEqual(res["status"], "RISKY", f"Failed for {email}")
            self.assertEqual(res["evidence_level"], "ROLE_ACCOUNT")
            self.assertTrue(res["checks"]["role_addr"])

    def test_validate_email_evidence_tiers(self):
        """Emails must reflect correct evidence tiers depending on verification level."""
        # 1. Syntax only (skip_mx=True)
        res_syntax = validate_email("john.doe@samplecorp.org", skip_mx=True)
        self.assertEqual(res_syntax["status"], "SYNTAX_VALID")
        self.assertEqual(res_syntax["evidence_level"], "SYNTAX_ONLY")

        # 2. SMTP handshake verified (highest tier)
        res_smtp = validate_email("executive@enterprise.com", skip_mx=True, smtp_delivered=True)
        self.assertEqual(res_smtp["status"], "DELIVERABLE")
        self.assertEqual(res_smtp["evidence_level"], "SMTP_HANDSHAKE_VERIFIED")

        # 3. MX confirmed mock
        with patch("contact_validator._check_mx_record", return_value=True):
            res_mx = validate_email("ceo@realcompany.com", skip_mx=False)
            self.assertEqual(res_mx["status"], "MX_CONFIRMED")
            self.assertEqual(res_mx["evidence_level"], "DNS_MX_CONFIRMED")
            self.assertTrue(res_mx["checks"]["mx_record"])

    def test_validate_phone_us_e164(self):
        """Google phonenumbers must normalize US 10-digit phone to canonical E.164."""
        samples = [
            ("(512) 555-0199", "+15125550199", "(512) 555-0199"),
            ("512-555-0199", "+15125550199", "(512) 555-0199"),
            ("+1 512 555 0199", "+15125550199", "(512) 555-0199"),
        ]
        for raw, expected_e164, expected_national in samples:
            res = validate_phone(raw, country="US")
            self.assertEqual(res["status"], "VALID_E164", f"Failed for {raw}")
            self.assertEqual(res["phone"], expected_e164)
            self.assertEqual(res["phone_national"], expected_national)
            self.assertEqual(res["phone_country"], "US")

    def test_validate_phone_mexico_e164(self):
        """Google phonenumbers must normalize Mexican 10-digit phone to canonical E.164 (+52)."""
        raw = "55 5234 5678"
        res = validate_phone(raw, country="MX")
        self.assertEqual(res["status"], "VALID_E164")
        self.assertEqual(res["phone"], "+525552345678")
        self.assertEqual(res["phone_country"], "MX")

    def test_validate_phone_toll_free(self):
        """Toll-free numbers must be classified with line type TOLL_FREE."""
        res = validate_phone("800-555-0199", country="US")
        self.assertEqual(res["status"], "VALID_E164")
        self.assertEqual(res["phone_type"], "TOLL_FREE")

    def test_validate_phone_invalid(self):
        """Malformed or incomplete phone numbers must be flagged as INVALID."""
        res = validate_phone("12345", country="US")
        self.assertEqual(res["status"], "INVALID")

        missing = validate_phone(None)
        self.assertEqual(missing["status"], "MISSING")

    def test_validate_contact_jsonb_structure(self):
        """validate_contact must return a complete schema suitable for PostgreSQL JSONB storage."""
        contact = validate_contact(
            email="sarah.connor@cyberdyne.com",
            phone="(512) 555-0144",
            linkedin_url="https://www.linkedin.com/in/sarah-connor",
            country="US",
            skip_mx=True,
            smtp_delivered=True,
        )
        self.assertEqual(contact["email"], "sarah.connor@cyberdyne.com")
        self.assertEqual(contact["email_status"], "DELIVERABLE")
        self.assertEqual(contact["email_evidence_level"], "SMTP_HANDSHAKE_VERIFIED")
        self.assertEqual(contact["phone"], "+15125550144")
        self.assertEqual(contact["phone_status"], "VALID_E164")
        self.assertEqual(contact["linkedin_url"], "https://linkedin.com/in/sarah-connor")
        self.assertIn("validated_at", contact)
        self.assertTrue(contact_is_usable(contact))

    def test_lead_score_from_contact(self):
        """Lead score should combine evidence-based email, phone, and seniority."""
        # Top tier: Deliverable email (40) + E.164 phone (20) + C-Suite bonus (10) = 70+
        contact_top = {
            "email_status": "DELIVERABLE",
            "phone_status": "VALID_E164",
        }
        score_top = lead_score_from_contact(contact_top, seniority_level="C_SUITE")
        self.assertEqual(score_top, 70)

        # Risky email (15) + Missing phone (0) + Manager (5) = 20
        contact_risky = {
            "email_status": "RISKY",
            "phone_status": "MISSING",
        }
        score_risky = lead_score_from_contact(contact_risky, seniority_level="MANAGER")
        self.assertEqual(score_risky, 20)


if __name__ == "__main__":
    unittest.main()
