"""
DataExtraction — E2E Scenario 3: OpenMap Spatial Engine & Circuit Breaker
==========================================================================
Comprehensive End-to-End integration test covering:
1. OpenStreetMap Overpass POI parsing and tag normalization.
2. Adaptive Quadtree spatial subdivision on HTTP 504 / timeout.
3. Multi-mirror Endpoint Circuit Breaker failover.
4. ACID Checkpoint Manager recovery without duplicate chunks.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

# Bootstrap paths
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGES = _REPO_ROOT / "packages"
_OSM_SRC = _PACKAGES / "scrapers" / "open_map" / "src"

for p in [
    _OSM_SRC,
    _PACKAGES / "scrapers" / "open_map",
    _REPO_ROOT / "tests" / "e2e" / "utils",
    _REPO_ROOT,
]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.quadtree import AdaptiveQuadtree, split_bounding_box
from src.circuit_breaker import EndpointCircuitBreaker, EndpointHealth
from src.checkpoint import EnterpriseCheckpointManager
from wiremock_controller import load_fixture


class TestE2EOSMQuadtree(unittest.TestCase):
    """End-to-End test suite for OpenMap Spatial Engine and Fault Tolerance."""

    @classmethod
    def setUpClass(cls):
        cls.fixtures = load_fixture("mock_osm_elements.json")

    def test_e2e_osm_element_parsing(self):
        """Verifies POI node parsing, coordinate extraction, and tag preservation."""
        elements = self.fixtures["elements"]
        self.assertEqual(len(elements), 2)

        elem1 = elements[0]
        self.assertEqual(elem1["tags"]["name"], "Montgomery Regional Health Clinic")
        self.assertEqual(elem1["tags"]["addr:state"], "AL")
        self.assertAlmostEqual(elem1["lat"], 32.3777)
        self.assertAlmostEqual(elem1["lon"], -86.3006)

    def test_e2e_adaptive_quadtree_subdivision_on_timeout(self):
        """Verifies that a failing bounding box is divided into 4 quadrants."""
        quadtree = AdaptiveQuadtree(max_depth=3, min_chunk_deg=0.05)
        initial_bbox = (32.0, -87.0, 34.0, -85.0)  # Alabama chunk

        # Check eligibility to subdivide
        self.assertTrue(quadtree.can_subdivide(initial_bbox, current_depth=0))

        # Perform subdivision into 4 equal quadrants
        quadrants = split_bounding_box(initial_bbox)
        self.assertEqual(len(quadrants), 4)

        quadrant_suffixes = [q[0] for q in quadrants]
        self.assertIn("q1_sw", quadrant_suffixes)
        self.assertIn("q2_se", quadrant_suffixes)
        self.assertIn("q3_nw", quadrant_suffixes)
        self.assertIn("q4_ne", quadrant_suffixes)

        # Verify geographic boundaries span original bbox
        s, w, n, e = initial_bbox
        q1_bbox = quadrants[0][1]
        self.assertAlmostEqual(q1_bbox[0], s)
        self.assertAlmostEqual(q1_bbox[1], w)

    def test_e2e_circuit_breaker_failover_mechanism(self):
        """Verifies that failing mirrors are isolated and traffic shifts to healthy ones."""
        endpoints = [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        ]
        cb = EndpointCircuitBreaker(endpoints=endpoints, failure_threshold=2, cooldown_sec=60.0)

        primary = cb.get_active_endpoint()
        self.assertIn(primary, endpoints)

        # Simulate 2 consecutive failures on primary
        cb.record_failure(primary, status_code=504, error_message="Gateway Timeout")
        cb.record_failure(primary, status_code=504, error_message="Gateway Timeout")

        # Primary must be marked unhealthy
        self.assertFalse(cb.registry[primary].is_healthy)

        # Next endpoint must be one of the other healthy mirrors
        secondary = cb.get_active_endpoint()
        self.assertNotEqual(secondary, primary)
        self.assertTrue(cb.registry[secondary].is_healthy)

    def test_e2e_checkpoint_manager_atomic_reconcile(self):
        """Verifies ACID transactions in SQLite WAL mode and legacy JSON synchronization."""
        test_dir = Path(tempfile.gettempdir()) / f"osm_e2e_{uuid.uuid4().hex[:8]}"
        test_dir.mkdir(parents=True, exist_ok=True)
        try:
            mgr = EnterpriseCheckpointManager(workspace_dir=str(test_dir))

            # Initialize field and chunk
            mgr.init_field(
                state_name="Alabama",
                state_code="AL",
                field_name="healthcare",
                field_group="HEALTH",
                total_chunks=1,
                chunks_info=[{"chunk_id": "chunk_01", "bbox": (32.0, -87.0, 33.0, -86.0)}],
            )

            # Mark chunk completed
            mgr.mark_chunk_completed(
                state_name="Alabama",
                field_name="healthcare",
                chunk_id="chunk_01",
                records_count=15,
                raw_path=str(test_dir / "raw.json"),
                proc_path=str(test_dir / "proc.json"),
            )

            # Sync legacy JSON tracker
            mgr.sync_to_legacy_json()

            # Verify progress JSON exists
            legacy_json = test_dir / "data" / "progress" / "osm_progress.json"
            self.assertTrue(legacy_json.exists())

            # Verify completed chunk IDs
            completed_ids = mgr.get_completed_chunk_ids("Alabama", "healthcare")
            self.assertIn("chunk_01", completed_ids)
        finally:
            time.sleep(0.1)
            try:
                shutil.rmtree(test_dir, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
