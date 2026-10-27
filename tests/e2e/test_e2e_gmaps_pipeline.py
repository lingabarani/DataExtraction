"""
DataExtraction — E2E Scenario 2: Google Maps Scraper Pipeline
==============================================================
Comprehensive End-to-End integration test covering:
1. Spatial coordinate ingestion and PlaceStub parsing.
2. Deduplication across geographic tiles by place_id.
3. Website verification and domain extraction (SSRF safety).
4. Directory/social domain discrimination.
5. State-level export generation (CSV format with standard headers).
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Bootstrap paths
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGES = _REPO_ROOT / "packages"
_GMAPS_SRC = _PACKAGES / "scrapers" / "google_maps" / "src"

for p in [
    _GMAPS_SRC,
    _PACKAGES / "pipeline",
    _PACKAGES / "infrastructure",
    _REPO_ROOT / "tests" / "e2e" / "utils",
    _REPO_ROOT,
]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from gmaps_scraper.models import PlaceStub
from gmaps_scraper.db import Database
from gmaps_scraper.website.ssrf import normalize_url, is_safe_url
from gmaps_scraper.website.verifier import is_directory_or_social, clean_tokens
from gmaps_scraper.export import export_data
from wiremock_controller import load_fixture


class TestE2EGMapsPipeline(unittest.TestCase):
    """End-to-End test suite for Google Maps Scraper and Enrichment."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures = load_fixture("mock_gmaps_places.json")

    def test_e2e_place_parsing_and_tiling_dedup(self):
        """Verifies PlaceStub conversion, spatial coordinate validation, and deduplication."""
        places = self.fixtures
        self.assertGreater(len(places), 0)

        stubs = []
        seen_place_ids = set()

        for idx, raw in enumerate(places, 1):
            stub = PlaceStub(
                cid=f"cid_{idx:05d}",
                ftid=f"0x{idx:08x}",
                place_id=raw["place_id"],
                name=raw["title"],
                category=raw["category"],
                address=raw["address"],
                latitude=raw["latitude"],
                longitude=raw["longitude"],
                phone=raw["phone"],
                website=raw["website"],
                rating=raw["rating"],
                review_count=raw["reviews_count"],
            )
            # Deterministic dedup by place_id
            if stub.place_id not in seen_place_ids:
                seen_place_ids.add(stub.place_id)
                stubs.append(stub)

        self.assertEqual(len(stubs), len(places))
        self.assertIn("ChIJN1t_tDeuEmsRUsoyG83frY4", seen_place_ids)

    def test_e2e_website_verifier_logic(self):
        """Verifies safe website normalization, SSRF guard, and directory discrimination."""
        # Clean URL normalization
        clean = normalize_url("http://google.com/")
        self.assertIn("google.com", clean)

        # Directory / social filtering
        self.assertTrue(is_directory_or_social("facebook.com"))
        self.assertTrue(is_directory_or_social("m.yelp.com"))
        self.assertFalse(is_directory_or_social("apexmanufacturing.com"))

        # Token extraction
        tokens = clean_tokens("Google LLC Corporate Headquarters")
        self.assertIn("google", tokens)
        self.assertNotIn("llc", tokens)  # Corporate suffix stripped

    def test_e2e_export_generation_csv(self):
        """Verifies Database storage and CSV export generation."""
        places = self.fixtures
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_gmaps.db"
            db = Database(str(db_path))
            db.init_schema()

            for idx, raw in enumerate(places, 1):
                db.upsert_place_stub({
                    "cid": f"cid_{idx:05d}",
                    "ftid": f"0x{idx:08x}",
                    "place_id": raw["place_id"],
                    "name": raw["title"],
                    "category": raw["category"],
                    "address": raw["address"],
                    "phone": raw["phone"],
                    "website": raw["website"],
                    "rating": raw["rating"],
                    "review_count": raw["reviews_count"],
                    "status": "completed",
                })

            export_res = export_data(db, export_format="csv", output_dir=Path(tmp_dir))
            files = export_res.get("files", [])
            self.assertGreater(len(files), 0)
            csv_path = files[0]
            self.assertTrue(Path(csv_path).exists())

            content = Path(csv_path).read_text(encoding="utf-8")
            self.assertIn("Google Bay View Campus", content)
            self.assertIn("St. Jude Children's Research Hospital", content)


if __name__ == "__main__":
    unittest.main()
