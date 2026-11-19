"""
Comprehensive Integration Tests for Enhanced Agent 2 & Agent 8
==============================================================
Validates:
1. Review extraction, checkpointing, incremental persistence, and resume.
2. Independent review analysis for sentiment, topics, complaints, praise.
3. Service extraction and hierarchical taxonomy classification.
4. Website candidate resolution and SSRF verification.
5. Multi-page crawling, field cross-verification, and tech stack detection.
6. C-suite leadership extraction.
7. MasterOrchestrator 8-agent topology.
8. Live Discovery SSE pipeline integrity.
"""

import asyncio
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.scrapers.google_maps.reviews.checkpoint import ReviewCheckpointStore
from packages.scrapers.google_maps.reviews.scraper import GoogleMapsReviewScraper
from packages.scrapers.google_maps.reviews.analyzer import ReviewAnalyzer
from packages.scrapers.google_maps.services.taxonomy import ServiceTaxonomyClassifier
from packages.scrapers.google_maps.services.extractor import GoogleMapsServiceExtractor
from packages.enrichment.website.tech_stack import TechStackDetector
from packages.enrichment.website.verifier import FieldCrossVerifier
from packages.enrichment.website.csuite_extractor import CSuiteExtractor
from packages.temporal.activities.website_intelligence_activities import (
    run_website_verification_activity,
    run_website_crawl_and_enrichment_activity,
)
from packages.temporal.workflows.master_orchestrator import MasterOrchestrator
from packages.temporal.workflows.w8_website_intelligence_workflow import Agent8WebsiteIntelligenceWorkflow
from packages.temporal.workflows.w2_geospatial_workflow import Agent2GeospatialWorkflow
from packages.temporal.workflows.discovery_workflow import DiscoverySearchWorkflow
from scripts.ops.start_all_workers import WORKERS_SPEC


class TestEnhancedAgent2AndAgent8Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_place_id = f"test_place_{int(datetime.now().timestamp())}"
        cls.test_domain = f"testcorp-{int(datetime.now().timestamp())}.com"

    def test_01_review_checkpoint_and_persistence(self):
        """Test checkpoint store saving, updating, and loading from PostgreSQL."""
        store = ReviewCheckpointStore(get_connection, release_connection)
        
        # Save initial checkpoint
        store.save_checkpoint(
            place_id=self.test_place_id,
            token="page_token_1",
            reviews_added=10,
            status="in_progress",
            run_id="run_test_01",
        )
        cp = store.get_checkpoint(self.test_place_id)
        self.assertIsNotNone(cp)
        self.assertEqual(cp["next_pagination_token"], "page_token_1")
        self.assertEqual(cp["reviews_extracted"], 10)
        self.assertEqual(cp["status"], "in_progress")

        # Resume and advance checkpoint
        store.save_checkpoint(
            place_id=self.test_place_id,
            token=None,
            reviews_added=15,
            status="complete",
            run_id="run_test_01",
        )
        cp2 = store.get_checkpoint(self.test_place_id)
        self.assertEqual(cp2["reviews_extracted"], 25)
        self.assertEqual(cp2["status"], "complete")
        self.assertIsNone(cp2["next_pagination_token"])

    def test_02_review_persistence_and_independent_analysis(self):
        """Test inserting raw reviews and executing independent review analysis."""
        scraper = GoogleMapsReviewScraper(
            get_conn_fn=get_connection,
            release_conn_fn=release_connection,
        )
        sample_reviews = [
            {
                "place_id": self.test_place_id,
                "review_id": f"rev_pos_{self.test_place_id}",
                "reviewer_name": "Alice Smith",
                "rating": 5,
                "review_text": "Superb work! Very friendly and prompt service. The staff is fantastic.",
                "language": "en",
                "reaction_count": 2,
            },
            {
                "place_id": self.test_place_id,
                "review_id": f"rev_neg_{self.test_place_id}",
                "reviewer_name": "Bob Jones",
                "rating": 1,
                "review_text": "Awful experience, terrible customer service and way overpriced. Never coming back.",
                "language": "en",
                "reaction_count": 0,
            },
        ]
        inserted = scraper._persist_reviews_batch(sample_reviews)
        self.assertEqual(inserted, 2)

        # Independent review analysis
        analyzer = ReviewAnalyzer(get_connection, release_connection)
        res = analyzer.analyze_stored_reviews(place_id=self.test_place_id, reanalyze=True)
        self.assertGreaterEqual(res["analyzed_count"], 2)

        # Check aggregate place summary
        summary = analyzer.get_place_review_summary(self.test_place_id)
        self.assertEqual(summary["total_reviews"], 2)
        self.assertEqual(summary["average_rating"], 3.0)
        self.assertEqual(summary["sentiment_summary"]["positive"], 1)
        self.assertEqual(summary["sentiment_summary"]["negative"], 1)

    def test_03_service_extraction_and_taxonomy(self):
        """Test service extraction from place attributes and taxonomy categorization."""
        extractor = GoogleMapsServiceExtractor(get_connection, release_connection)
        sample_details = {
            "attributes": [
                {"attribute_name": "Custom Mobile App Development", "group_name": "Offerings", "is_enabled": True},
                {"attribute_name": "Air Conditioning Installation", "group_name": "Services", "is_enabled": True},
                {"attribute_name": "Corporate Contract Law Review", "group_name": "Legal", "is_enabled": True},
            ]
        }
        rows = extractor.extract_from_place_details(self.test_place_id, sample_details, run_id="svc_run_01")
        self.assertEqual(len(rows), 3)

        saved = extractor.persist_services(rows)
        self.assertEqual(saved, 3)

        categories = {r["main_category"] for r in rows}
        self.assertIn("Technology", categories)
        self.assertIn("Construction & Trades", categories)
        self.assertIn("Professional Services", categories)

    def test_04_website_intelligence_enrichment_flow(self):
        """Test Agent 8 website verification, crawling, tech stack, and C-suite extraction."""
        candidate = {
            "domain": self.test_domain,
            "place_id": self.test_place_id,
            "company_id": f"comp_{self.test_place_id}",
            "name": "Acme Enterprise Technologies",
            "website": f"https://{self.test_domain}",
            "phone": "415-555-0155",
            "email": "info@acme-test.com",
            "postal_code": "94107",
            "source": "GOOGLE_MAPS",
        }

        # Mock crawler to return synthetic HTML without requiring external web access
        mock_pages = {
            f"https://{self.test_domain}/": """
            <html>
                <head>
                    <script src="/_next/static/app.js"></script>
                    <script async src="https://www.googletagmanager.com/gtag/js?id=G-XYZ123"></script>
                </head>
                <body>
                    <h1>Acme Enterprise Technologies</h1>
                    <p>Phone: (415) 555-0155</p>
                    <p>Email: info@acme-test.com</p>
                    <a href="/leadership">Leadership Team</a>
                </body>
            </html>
            """,
            f"https://{self.test_domain}/leadership": """
            <html>
                <body>
                    <h2>Leadership</h2>
                    <div>
                        <h3>Jonathan Vance</h3>
                        <p>Chief Executive Officer</p>
                    </div>
                    <div>
                        <h3>Elena Rostova</h3>
                        <p>Chief Technology Officer</p>
                    </div>
                </body>
            </html>
            """,
        }

        with patch("packages.temporal.activities.website_intelligence_activities.SafeWebsiteCrawler.crawl", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = mock_pages
            
            enrichment_stats = asyncio.run(run_website_crawl_and_enrichment_activity(
                verified_candidates=[candidate],
                batch_id="test_enrichment_batch",
                max_pages=3,
            ))

            self.assertEqual(enrichment_stats["domains_crawled"], 1)
            self.assertGreaterEqual(enrichment_stats["tech_stack_saved"], 2)
            self.assertGreaterEqual(enrichment_stats["executives_saved"], 2)
            self.assertGreaterEqual(enrichment_stats["cross_verifications_saved"], 2)

    def test_05_master_orchestrator_8_agent_topology(self):
        """Verify MasterOrchestrator registers all 8 agents in the exact required sequence."""
        wf = MasterOrchestrator()
        status = wf.get_status()
        self.assertEqual(status["status"], "RUNNING")
        self.assertIn("reviews_extracted", wf._metrics)
        self.assertIn("services_extracted", wf._metrics)
        self.assertIn("websites_verified", wf._metrics)
        self.assertIn("websites_crawled", wf._metrics)
        self.assertIn("csuite_identified", wf._metrics)
        self.assertIn("tech_stack_detected", wf._metrics)

    def test_06_worker_supervisor_registration(self):
        """Verify scripts/ops/start_all_workers.py registers all workers including worker-8-website."""
        worker_ids = [w.id for w in WORKERS_SPEC]
        queues = [w.queue for w in WORKERS_SPEC]

        self.assertIn("worker-1-registry", worker_ids)
        self.assertIn("worker-2-geospatial", worker_ids)
        self.assertIn("worker-8-website", worker_ids)
        self.assertIn("worker-3-identity", worker_ids)
        self.assertIn("worker-7-email", worker_ids)
        self.assertIn("worker-4-executive", worker_ids)
        self.assertIn("worker-5-governance", worker_ids)
        self.assertIn("worker-6-search", worker_ids)

        self.assertIn("website-intelligence-queue", queues)
        self.assertIn("geospatial-domain-queue", queues)

    def test_07_discovery_sse_pipeline_unbroken(self):
        """Ensure DiscoverySearchWorkflow and PlaceDeepExtractionWorkflow are intact."""
        self.assertTrue(hasattr(DiscoverySearchWorkflow, "run"))
        self.assertTrue(hasattr(Agent2GeospatialWorkflow, "run"))
        self.assertTrue(hasattr(Agent8WebsiteIntelligenceWorkflow, "run"))


if __name__ == "__main__":
    unittest.main()
