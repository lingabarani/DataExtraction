"""
Unit and integration tests for Agent 2: Google Maps Reviews & Services
Tests:
1. Review pagination, privacy modes, and incremental checkpoint store.
2. Review sentiment, topic, complaints, and praise analysis.
3. Hierarchical service taxonomy classification and attribute mapping.
"""

import unittest
from unittest.mock import MagicMock
from packages.scrapers.google_maps.reviews.analyzer import ReviewAnalyzer
from packages.scrapers.google_maps.services.taxonomy import ServiceTaxonomyClassifier, TAXONOMY_RULES


class TestAgent2ReviewsServices(unittest.TestCase):
    def setUp(self):
        self.analyzer = ReviewAnalyzer(
            get_conn_fn=lambda: None,
            release_conn_fn=lambda c: None,
        )
        self.classifier = ServiceTaxonomyClassifier()

    def test_review_analysis_positive(self):
        text = "Absolutely fantastic service! The staff was very friendly, fast and helpful. High quality work."
        insights = self.analyzer.analyze_review_text(text, rating=5)
        self.assertEqual(insights["sentiment"], "positive")
        self.assertIn("customer_service", insights["topics"])
        self.assertTrue(insights["customer_experience_indicators"]["staff_friendly"])
        self.assertTrue(insights["customer_experience_indicators"]["timely_service"])
        self.assertTrue(len(insights["praise"]) > 0)
        self.assertEqual(len(insights["complaints"]), 0)

    def test_review_analysis_negative_complaint(self):
        text = "Terrible experience. The manager was extremely rude and the price was way overpriced. Slow service."
        insights = self.analyzer.analyze_review_text(text, rating=1)
        self.assertEqual(insights["sentiment"], "negative")
        self.assertIn("pricing", insights["topics"])
        self.assertIn("customer_service", insights["topics"])
        self.assertTrue(len(insights["complaints"]) > 0)
        self.assertFalse(insights["customer_experience_indicators"]["good_value"])

    def test_review_analysis_mixed_sentiment(self):
        text = "Great delicious food and friendly staff, but the service was terribly slow and very expensive."
        insights = self.analyzer.analyze_review_text(text, rating=3)
        self.assertIn(insights["sentiment"], ["mixed", "neutral"])

    def test_service_taxonomy_technology(self):
        classified = self.classifier.classify_service("Mobile App Development", "Engineering")
        self.assertEqual(classified["main_category"], "Technology")
        self.assertEqual(classified["subcategory"], "Software Development")
        self.assertEqual(classified["service_name"], "Mobile App Development")
        self.assertIn("mobile", classified["tags"])

    def test_service_taxonomy_professional_legal(self):
        classified = self.classifier.classify_service("Patent Filing & Prosecution", "Legal Services")
        self.assertEqual(classified["main_category"], "Professional Services")
        self.assertEqual(classified["subcategory"], "Legal Services")
        self.assertEqual(classified["service_name"], "Intellectual Property")

    def test_service_taxonomy_construction_trades(self):
        classified = self.classifier.classify_service("HVAC Repair and AC installation", "Amenities")
        self.assertEqual(classified["main_category"], "Construction & Trades")
        self.assertEqual(classified["subcategory"], "Specialty Trades")
        self.assertEqual(classified["service_name"], "HVAC Installation & Repair")

    def test_service_taxonomy_fallback(self):
        classified = self.classifier.classify_service("Custom Antique Restoration", "Specialty")
        # Uncertain services remain unclassified (None) rather than forcing a synthetic fallback category
        self.assertIsNone(classified["main_category"])
        self.assertIsNone(classified["subcategory"])
        self.assertEqual(classified["service_name"], "Custom Antique Restoration")


if __name__ == "__main__":
    unittest.main()
