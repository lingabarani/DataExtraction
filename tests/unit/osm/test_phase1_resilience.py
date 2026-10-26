#!/usr/bin/env python3
"""
Unit and Integration Test Suite for Phase 1: Open Map Extraction Resiliency Architecture.

Validates:
1. Enterprise Configuration Management (src.config)
2. Endpoint Circuit Breaker & Health Isolation (src.circuit_breaker)
3. Adaptive Quadtree Spatial Subdivision (src.quadtree)
4. SQLite ACID State Checkpoint Manager (src.checkpoint)
5. Integrated Failover and Sub-Bisection Pipeline Flow
"""

import json
import os
import shutil
import tempfile
import time
import sys
import unittest
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
from src.config import OverpassConfig, DEFAULT_OVERPASS_MIRRORS
from src.circuit_breaker import EndpointCircuitBreaker, EndpointHealth
from src.quadtree import AdaptiveQuadtree, split_bounding_box
from src.checkpoint import EnterpriseCheckpointManager
from src.sources.osm_overpass import OpenStreetMapSource, OverpassTimeoutError, validate_overpass_response


class TestOverpassConfig(unittest.TestCase):
    """Verifies configuration loading, mirror pool assembly, and zero-hardcoding rules."""

    def test_default_config_mirrors(self):
        cfg = OverpassConfig()
        self.assertIn("https://overpass-api.de/api/interpreter", cfg.fallback_endpoints)
        self.assertIn("https://overpass.kumi.systems/api/interpreter", cfg.fallback_endpoints)
        self.assertIn("https://overpass.private.coffee/api/interpreter", cfg.fallback_endpoints)
        self.assertGreaterEqual(len(cfg.fallback_endpoints), 4)

    def test_config_timeouts(self):
        cfg = OverpassConfig(connect_timeout_sec=15, read_timeout_sec=50)
        self.assertEqual(cfg.connect_timeout_sec, 15)
        self.assertEqual(cfg.read_timeout_sec, 50)
        self.assertTrue(cfg.enable_adaptive_subdivision)
        self.assertEqual(cfg.max_quadtree_depth, 3)


class TestEndpointCircuitBreaker(unittest.TestCase):
    """Verifies circuit breaker health tracking, cooldown isolation, and jittered backoff."""

    def setUp(self):
        self.endpoints = [
            "https://mirror1.org/api",
            "https://mirror2.org/api",
            "https://mirror3.org/api"
        ]
        self.cb = EndpointCircuitBreaker(self.endpoints, failure_threshold=2, cooldown_sec=1.0)

    def test_initial_active_endpoint(self):
        ep = self.cb.get_active_endpoint()
        self.assertEqual(ep, self.endpoints[0])

    def test_rotate_endpoint(self):
        next_ep = self.cb.rotate_endpoint()
        self.assertEqual(next_ep, self.endpoints[1])

    def test_circuit_trips_on_504(self):
        ep = self.cb.get_active_endpoint()
        tripped, cooldown = self.cb.record_failure(ep, status_code=504, error_message="Gateway Timeout")
        self.assertTrue(tripped)
        self.assertGreater(cooldown, 0)
        self.assertFalse(self.cb.registry[ep].is_healthy)
        
        # Next active endpoint should NOT be the failing one
        new_ep = self.cb.get_active_endpoint()
        self.assertNotEqual(new_ep, ep)

    def test_jittered_backoff_bounds(self):
        for attempt in range(1, 5):
            delay = self.cb.calculate_jittered_backoff(attempt=attempt, base_backoff=1.5, max_delay=30.0)
            self.assertGreaterEqual(delay, 2.0)
            self.assertLessEqual(delay, 30.0)


class TestAdaptiveQuadtree(unittest.TestCase):
    """Verifies spatial bisection geometry and cross-border deduplication."""

    def setUp(self):
        self.qt = AdaptiveQuadtree(max_depth=3, min_chunk_deg=0.0625)
        # Bbox in Alabama: (s, w, n, e) = (30.5, -88.0, 31.0, -87.5) (0.5 deg tile)
        self.bbox = (30.5, -88.0, 31.0, -87.5)

    def test_split_bounding_box(self):
        quadrants = split_bounding_box(self.bbox)
        self.assertEqual(len(quadrants), 4)
        suffixes = [q[0] for q in quadrants]
        self.assertEqual(suffixes, ["q1_sw", "q2_se", "q3_nw", "q4_ne"])

        # Check midpoint calculations
        # mid_lat = 30.75, mid_lon = -87.75
        sw_bbox = quadrants[0][1]
        self.assertEqual(sw_bbox, (30.5, -88.0, 30.75, -87.75))
        ne_bbox = quadrants[3][1]
        self.assertEqual(ne_bbox, (30.75, -87.75, 31.0, -87.5))

    def test_depth_limit(self):
        self.assertTrue(self.qt.can_subdivide(self.bbox, current_depth=0))
        self.assertTrue(self.qt.can_subdivide(self.bbox, current_depth=1))
        self.assertTrue(self.qt.can_subdivide(self.bbox, current_depth=2))
        self.assertFalse(self.qt.can_subdivide(self.bbox, current_depth=3))

    def test_deduplicate_records(self):
        records = [
            {"osm_type": "node", "osm_id": 1001, "name": "Pharmacy A"},
            {"osm_type": "node", "osm_id": 1001, "name": "Pharmacy A Duplicate"},
            {"osm_type": "way", "osm_id": 2001, "name": "General Hospital"},
        ]
        deduped = self.qt.deduplicate_records(records)
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["osm_id"], 1001)
        self.assertEqual(deduped[1]["osm_id"], 2001)


class TestEnterpriseCheckpointManager(unittest.TestCase):
    """Verifies SQLite ACID safety, atomic updates, and disk reconciliation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="osm_test_checkpoint_")
        self.cp = EnterpriseCheckpointManager(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sqlite_db_creation(self):
        self.assertTrue(os.path.exists(self.cp.db_path))

    def test_init_and_mark_completed(self):
        chunks = [
            {"chunk_id": "chunk_0001", "bbox": (30.0, -88.0, 30.5, -87.5)},
            {"chunk_id": "chunk_0002", "bbox": (30.5, -88.0, 31.0, -87.5)},
        ]
        self.cp.init_field(
            state_name="Alabama",
            state_code="AL",
            field_name="healthcare",
            field_group="HEALTHCARE",
            total_chunks=2,
            chunks_info=chunks
        )

        completed_set = self.cp.get_completed_chunk_ids("Alabama", "healthcare")
        self.assertEqual(len(completed_set), 0)

        # Mark chunk_0001 completed
        self.cp.mark_chunk_completed(
            state_name="Alabama",
            field_name="healthcare",
            chunk_id="chunk_0001",
            records_count=42,
            raw_path=os.path.join(self.test_dir, "raw.json"),
            proc_path=os.path.join(self.test_dir, "proc.json")
        )

        completed_set = self.cp.get_completed_chunk_ids("Alabama", "healthcare")
        self.assertEqual(completed_set, {"chunk_0001"})

        # Verify export to legacy JSON matches
        self.assertTrue(os.path.exists(self.cp.legacy_json_path))
        with open(self.cp.legacy_json_path, "r", encoding="utf-8") as f:
            legacy = json.load(f)
        self.assertIn("Alabama", legacy)
        self.assertIn("healthcare", legacy["Alabama"])
        self.assertEqual(legacy["Alabama"]["healthcare"]["completed_chunks"], 1)

    def test_reconcile_corrupted_or_missing_chunk(self):
        proc_dir = os.path.join(self.test_dir, "processed")
        os.makedirs(proc_dir, exist_ok=True)
        valid_proc_file = os.path.join(proc_dir, "chunk_0001.json")
        with open(valid_proc_file, "w", encoding="utf-8") as f:
            json.dump([{"osm_id": 123}], f)

        chunks = [{"chunk_id": "chunk_0001", "bbox": (30.0, -88.0, 30.5, -87.5)}]
        self.cp.init_field("Alabama", "AL", "shop", "COMMERCIAL", 1, chunks)
        self.cp.mark_chunk_completed("Alabama", "shop", "chunk_0001", 1, "", valid_proc_file)

        # Reconcile valid file: count should remain 1
        valid, repaired = self.cp.reconcile_disk_state("Alabama", "shop", proc_dir)
        self.assertEqual(valid, 1)
        self.assertEqual(repaired, 0)

        # Remove the file to simulate crash/disk corruption
        os.remove(valid_proc_file)
        valid, repaired = self.cp.reconcile_disk_state("Alabama", "shop", proc_dir)
        self.assertEqual(valid, 0)
        self.assertEqual(repaired, 1)
        self.assertEqual(len(self.cp.get_completed_chunk_ids("Alabama", "shop")), 0)


class TestResponseValidation(unittest.TestCase):
    """Verifies response validation and detection of error remarks or invalid endpoints."""

    def test_valid_response(self):
        payload = {"elements": [{"id": 1, "type": "node", "tags": {"shop": "bakery"}}]}
        is_valid, err, count = validate_overpass_response(payload)
        self.assertTrue(is_valid)
        self.assertIsNone(err)
        self.assertEqual(count, 1)

    def test_timed_out_remark(self):
        payload = {"elements": [], "remark": "runtime error: Query timed out after 35 seconds"}
        is_valid, err, count = validate_overpass_response(payload)
        self.assertFalse(is_valid)
        self.assertIn("runtime error", err.lower())

    def test_rejected_117166_endpoint(self):
        payload = {"elements": [], "osm3s": {"timestamp_osm_base": "117166"}}
        is_valid, err, count = validate_overpass_response(payload)
        self.assertFalse(is_valid)
        self.assertIn("117166", err)


if __name__ == "__main__":
    unittest.main()
