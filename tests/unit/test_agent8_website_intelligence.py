"""
Unit and integration tests for Agent 8: Website Intelligence & Enrichment
Tests:
1. Tech stack detection across HTML and HTTP headers.
2. Field-level cross-verification & conflict detection.
3. C-suite executive and leadership extraction.
4. SSRF protection verification.
5. Agent 8 Workflow and Activity structure.
"""

import unittest
from packages.enrichment.website.tech_stack import TechStackDetector
from packages.enrichment.website.verifier import FieldCrossVerifier
from packages.enrichment.website.csuite_extractor import CSuiteExtractor
from packages.scrapers.google_maps.src.gmaps_scraper.website.ssrf import is_safe_url


class TestAgent8WebsiteIntelligence(unittest.TestCase):
    def test_tech_stack_detection_cms_and_framework(self):
        html_pages = {
            "https://acme.com/": """
            <html>
                <head>
                    <script src="/_next/static/chunks/main.js"></script>
                    <script src="https://cdn.shopify.com/s/files/1/theme.js"></script>
                    <script async src="https://www.googletagmanager.com/gtag/js?id=G-12345ABC"></script>
                </head>
                <body class="font-sans max-w-7xl mx-auto">
                    <h1>Welcome to Acme</h1>
                </body>
            </html>
            """
        }
        headers = {
            "server": "cloudflare",
            "cf-ray": "82a93b4c12-DFW",
            "x-powered-by": "Next.js",
        }
        detected = TechStackDetector.detect(html_pages, headers)
        names = {d["technology_name"] for d in detected}
        categories = {d["category"] for d in detected}

        self.assertIn("Next.js", names)
        self.assertIn("Shopify", names)
        self.assertIn("Google Analytics", names)
        self.assertIn("Cloudflare", names)
        self.assertIn("Tailwind CSS", names)
        self.assertIn("CMS", categories)
        self.assertIn("Framework", categories)
        self.assertIn("Analytics", categories)
        self.assertIn("Hosting & CDN", categories)

    def test_field_cross_verification_exact_match(self):
        domain = "techcorp.com"
        upstream = {
            "name": "TechCorp Inc.",
            "phone": "+1 415-555-0199",
            "email": "contact@techcorp.com",
            "postal_code": "94105",
        }
        evidence = {
            "names": [{"value": "TechCorp Inc", "source_url": "https://techcorp.com/about"}],
            "phones": [{"value": "(415) 555-0199", "source_url": "https://techcorp.com/contact"}],
            "emails": [{"value": "contact@techcorp.com", "source_url": "https://techcorp.com/contact"}],
            "addresses": [{"postal_code": "94105", "source_url": "https://techcorp.com/contact"}],
        }
        results = FieldCrossVerifier.verify_company_fields(domain, upstream, evidence)
        statuses = {r["field_name"]: r["status"] for r in results}

        self.assertEqual(statuses.get("company_name"), "VERIFIED")
        self.assertEqual(statuses.get("phone"), "VERIFIED")
        self.assertEqual(statuses.get("email"), "VERIFIED")
        self.assertEqual(statuses.get("postal_code"), "VERIFIED")

    def test_field_cross_verification_conflict_detection(self):
        domain = "healthplus.com"
        upstream = {
            "name": "Health Plus LLC",
            "phone": "212-555-0100",
            "email": "old_info@healthplus.com",
            "postal_code": "10001",
        }
        evidence = {
            "names": [{"value": "Health Plus LLC", "source_url": "https://healthplus.com/"}],
            "phones": [{"value": "212-555-9999", "source_url": "https://healthplus.com/contact"}],
            "emails": [{"value": "support@healthplus.com", "source_url": "https://healthplus.com/contact"}],
            "addresses": [{"postal_code": "90210", "source_url": "https://healthplus.com/contact"}],
        }
        results = FieldCrossVerifier.verify_company_fields(domain, upstream, evidence)
        statuses = {r["field_name"]: r["status"] for r in results}

        self.assertEqual(statuses.get("company_name"), "VERIFIED")
        self.assertEqual(statuses.get("phone"), "CONFLICT")
        self.assertEqual(statuses.get("email"), "CONFLICT")
        self.assertEqual(statuses.get("postal_code"), "CONFLICT")

        phone_conflict = next(r for r in results if r["field_name"] == "phone")
        self.assertEqual(phone_conflict["original_value"], "212-555-0100")
        self.assertEqual(phone_conflict["website_value"], "212-555-9999")

    def test_csuite_leadership_extraction(self):
        extractor = CSuiteExtractor()
        html_pages = {
            "https://acme.com/leadership": """
            <div>
                <h2>Executive Leadership</h2>
                <div class="team-member">
                    <h3>Alice Montgomery</h3>
                    <p>Chief Executive Officer & Founder</p>
                </div>
                <div class="team-member">
                    <h3>David K. Chen</h3>
                    <p>Chief Technology Officer</p>
                </div>
                <div class="team-member">
                    <h3>Sarah Jenkins</h3>
                    <p>Chief Financial Officer</p>
                </div>
            </div>
            """
        }
        leaders = extractor.extract_leadership(html_pages, place_id="test_cid")
        names_roles = {(l["full_name"], l["role_title"]) for l in leaders}

        self.assertIn(("Alice Montgomery", "Chief Executive Officer"), names_roles)
        self.assertIn(("David K. Chen", "Chief Technology Officer"), names_roles)
        self.assertIn(("Sarah Jenkins", "Chief Financial Officer"), names_roles)

    def test_ssrf_safety_checks(self):
        # Disallowed private and metadata endpoints
        self.assertFalse(is_safe_url("http://localhost:8000")[0])
        self.assertFalse(is_safe_url("http://127.0.0.1/admin")[0])
        self.assertFalse(is_safe_url("http://169.254.169.254/latest/meta-data")[0])
        self.assertFalse(is_safe_url("http://metadata.google.internal")[0])
        self.assertFalse(is_safe_url("http://192.168.1.100")[0])
        self.assertFalse(is_safe_url("http://10.0.0.5:5432")[0])

        # Allowed public domains (tested with check_dns=False for offline unit testing)
        self.assertTrue(is_safe_url("https://www.google.com", check_dns=False)[0])
        self.assertTrue(is_safe_url("https://github.com/features", check_dns=False)[0])
        self.assertTrue(is_safe_url("https://93.184.216.34", check_dns=False)[0])


if __name__ == "__main__":
    unittest.main()
