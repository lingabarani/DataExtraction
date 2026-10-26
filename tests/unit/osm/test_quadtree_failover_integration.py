#!/usr/bin/env python3
"""
Integration Test: Verifies Adaptive Quadtree Auto-Bisection and Failover Flow.

Simulates a 0.5° bounding box that times out with HTTP 504 on initial attempt,
triggering automatic subdivision into 4 quadrants of 0.25°, each succeeding,
and assembling into a fully completed parent chunk in the ACID Checkpoint DB.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path
_osm_dir = Path(__file__).resolve().parent
_project_root = _osm_dir.parents[2]
_packages = _project_root / "packages"

for _p in [
    _packages / "scrapers" / "open_map",
    _packages / "scrapers" / "open_map" / "src",
    _packages / "pipeline",
    _packages / "infrastructure",
    _packages / "scrapers",
    _packages / "scrapers" / "federal",
    _packages / "scrapers" / "openmap_engine",
    _packages / "api",
    _packages / "api" / "routers",
    _project_root / "scripts" / "db",
    _project_root / "scripts" / "ops",
    _project_root,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from src.config import OverpassConfig
from src.osm_state_collector import OSMStateCollector
from src.sources.osm_overpass import OverpassTimeoutError


class TestQuadtreeFailoverIntegration(unittest.TestCase):
    """Verifies that 504 timeouts trigger adaptive quadtree bisection and recovery."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="osm_test_integration_")
        self.config = OverpassConfig(
            enable_adaptive_subdivision=True,
            max_quadtree_depth=2,
            rate_limit_delay_sec=0.0
        )
        self.collector = OSMStateCollector(
            workspace_dir=self.test_dir,
            config=self.config
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_chunk_timeout_triggers_quadtree_bisection(self):
        """Simulate root chunk timing out with 504, but children succeeding."""
        # Setup mock responses: parent fails with OverpassTimeoutError, child quadrants succeed
        def mock_query(ql_query, timeout=None, counters=None):
            # If broad bounding box query: simulate 504 timeout
            if "30.0, -88.0, 30.5, -87.5" in ql_query or "30.0,-88.0,30.5,-87.5" in ql_query:
                raise OverpassTimeoutError("Overpass server timed out: HTTP 504 Gateway Timeout")
            # Sub-quadrant queries succeed
            return {
                "elements": [
                    {
                        "type": "node",
                        "id": 12345,
                        "lat": 30.1,
                        "lon": -87.9,
                        "tags": {"name": "Subdivided Clinic", "amenity": "clinic"}
                    }
                ]
            }

        with patch.object(self.collector.osm_source, "query_overpass", side_effect=mock_query):
            field_meta = {
                "field": "healthcare",
                "category_group": "HEALTHCARE",
                "query_template": 'nwr["amenity"="clinic"]({s},{w},{n},{e});'
            }
            chunk_info = {
                "chunk_id": "chunk_0001",
                "index": 1,
                "bbox": (30.0, -88.0, 30.5, -87.5)
            }
            completed_chunk_ids = set()
            field_records_map = {}
            field_progress = {
                "completed_chunk_ids": [],
                "failed_chunk_ids": [],
                "stats": {}
            }
            mock_logger = MagicMock()
            raw_dir = os.path.join(self.test_dir, "data", "raw", "alabama", "healthcare")
            proc_dir = os.path.join(self.test_dir, "data", "processed", "alabama", "healthcare")
            os.makedirs(raw_dir, exist_ok=True)
            os.makedirs(proc_dir, exist_ok=True)

            status, count = self.collector._process_single_chunk(
                query_template=field_meta["query_template"],
                chunk_info=chunk_info,
                field_meta=field_meta,
                state_name="Alabama",
                state_slug="alabama",
                field_name="healthcare",
                field_progress=field_progress,
                completed_chunk_ids=completed_chunk_ids,
                field_records_map=field_records_map,
                state_logger=mock_logger,
                chunk_dir_raw=raw_dir,
                chunk_dir_proc=proc_dir,
                counters={},
                chunk_size_deg=0.5,
                depth=0,
                parent_id=None,
                total_chunks=1,
            )

            # Assert parent chunk completed via quadtree bisection
            self.assertEqual(status, "completed")
            self.assertIn("chunk_0001", completed_chunk_ids)
            self.assertGreater(count, 0)
            self.assertEqual(len(field_records_map), 1)

            # Check that child quadrant files exist on disk
            self.assertTrue(os.path.exists(os.path.join(proc_dir, "chunk_0001_q1_sw.json")))
            self.assertTrue(os.path.exists(os.path.join(proc_dir, "chunk_0001_q2_se.json")))
            self.assertTrue(os.path.exists(os.path.join(proc_dir, "chunk_0001_q3_nw.json")))
            self.assertTrue(os.path.exists(os.path.join(proc_dir, "chunk_0001_q4_ne.json")))

            # Check SQLite database state
            completed_in_db = self.collector.checkpoint_manager.get_completed_chunk_ids("Alabama", "healthcare")
            self.assertIn("chunk_0001_q1_sw", completed_in_db)
            self.assertIn("chunk_0001_q2_se", completed_in_db)
            self.assertIn("chunk_0001_q3_nw", completed_in_db)
            self.assertIn("chunk_0001_q4_ne", completed_in_db)


if __name__ == "__main__":
    unittest.main()
