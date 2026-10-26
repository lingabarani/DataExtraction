#!/usr/bin/env python3
"""
Unit and Integration Test Suite for Phases 2 & 3:
- Phase 2: Pipeline Normalization, Quality Scoring & Deduplication Connector
- Phase 3: FastAPI Backend REST Endpoints & Telemetry
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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
from fastapi.testclient import TestClient

from normalizer import normalize_company, supported_sources
from openmap_engine import (
    OverpassConfig,
    default_config,
    EndpointCircuitBreaker,
    AdaptiveQuadtree,
    EnterpriseCheckpointManager,
    OpenMapConnector,
    US_STATES,
    STATE_BOUNDING_BOXES,
    FIELDS_TAXONOMY,
)
from api_server import app


class TestPhase2NormalizationAndConnector(unittest.TestCase):
    """Verifies OSM normalization, schema conformity, and OpenMapConnector."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="osm_test_p2_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sources_registration(self):
        """Verifies OPEN_MAP and OSM sources are registered."""
        sources = supported_sources()
        self.assertIn("OPEN_MAP", sources)
        self.assertIn("OSM", sources)

    def test_normalize_company_osm_poi_dict(self):
        """Tests normalization of extracted POI record with contact and geo tags."""
        poi_record = {
            "osm_id": 987654321,
            "osm_type": "node",
            "name": "Acme Health Clinic",
            "brand": "Acme Health",
            "operator": "Acme Healthcare LLC",
            "addr:housenumber": "123",
            "addr:street": "Main St",
            "addr:city": "Birmingham",
            "addr:state": "AL",
            "addr:postcode": "35203",
            "addr:country": "US",
            "latitude": 33.5186,
            "longitude": -86.8104,
            "phone": "+1-205-555-0199",
            "email": "contact@acmehealth.com",
            "website": "https://www.acmehealth.com/locations/birmingham",
            "category_group": "HEALTHCARE",
            "category": "clinic",
        }

        norm = normalize_company(poi_record, source="OPEN_MAP")
        self.assertEqual(norm["name"], "Acme Health Clinic")
        self.assertEqual(norm["trade_name"], "Acme Health")
        self.assertEqual(norm["legal_name"], "Acme Healthcare LLC")
        self.assertEqual(norm["domain"], "acmehealth.com")
        self.assertEqual(norm["street"], "123 Main St")
        self.assertEqual(norm["city"], "Birmingham")
        self.assertEqual(norm["state_code"], "AL")
        self.assertEqual(norm["zip_code"], "35203")
        self.assertEqual(norm["phone"], "+1-205-555-0199")
        self.assertEqual(norm["email"], "contact@acmehealth.com")
        self.assertEqual(norm["latitude"], 33.5186)
        self.assertEqual(norm["longitude"], -86.8104)
        self.assertEqual(norm["industry"], "HEALTHCARE")
        self.assertEqual(norm["category"], "clinic")
        self.assertEqual(norm["source"], "OPEN_MAP")
        # Quality score: 55 base + 15 phone + 15 website + 10 street/city + 5 coords = 100
        self.assertEqual(norm["data_quality_score"], 100)

    def test_normalize_company_osm_raw_element(self):
        """Tests normalization from raw Overpass JSON element with tags dict."""
        raw_element = {
            "type": "way",
            "id": 11223344,
            "lat": 34.0522,
            "lon": -118.2437,
            "tags": {
                "name": "Sunset Financial Advisory",
                "brand": "Sunset Capital",
                "addr:housenumber": "450",
                "addr:street": "Grand Ave",
                "addr:city": "Los Angeles",
                "addr:state": "California",
                "addr:postcode": "90071",
                "contact:phone": "213-555-0100",
                "contact:website": "sunsetcapital.org",
                "office": "financial",
            }
        }

        norm = normalize_company(raw_element, source="OSM")
        self.assertEqual(norm["name"], "Sunset Financial Advisory")
        self.assertEqual(norm["trade_name"], "Sunset Capital")
        self.assertEqual(norm["domain"], "sunsetcapital.org")
        self.assertEqual(norm["street"], "450 Grand Ave")
        self.assertEqual(norm["city"], "Los Angeles")
        self.assertEqual(norm["state_code"], "CA")
        self.assertEqual(norm["phone"], "213-555-0100")
        self.assertGreaterEqual(norm["data_quality_score"], 90)

    def test_openmap_connector_load_and_dry_run_ingest(self):
        """Tests connector loading files from disk, normalization, and dry-run ingestion."""
        test_file = os.path.join(self.temp_dir, "test_export.json")
        sample_records = [
            {
                "osm_id": 101,
                "osm_type": "node",
                "name": "Alpha Diagnostics",
                "phone": "205-555-1111",
                "website": "https://alphadiag.com",
                "addr:city": "Mobile",
                "addr:state": "AL",
            },
            {
                "osm_id": 102,
                "osm_type": "node",
                "name": "Beta Medical Supplies",
                "phone": "205-555-2222",
                "website": "https://betamed.com",
                "addr:city": "Huntsville",
                "addr:state": "AL",
            }
        ]
        with open(test_file, "w", encoding="utf-8") as f:
            json.dump(sample_records, f)

        connector = OpenMapConnector(workspace_dir=self.temp_dir)
        loaded = connector.load_exported_file(test_file)
        self.assertEqual(len(loaded), 2)

        norm_list = connector.normalize_records(loaded)
        self.assertEqual(len(norm_list), 2)
        self.assertEqual(norm_list[0]["name"], "Alpha Diagnostics")
        self.assertEqual(norm_list[1]["name"], "Beta Medical Supplies")

        # Ingestion dry run
        stats = connector.ingest_records(loaded, dry_run=True)
        self.assertTrue(stats["dry_run"])
        self.assertEqual(stats["total_raw"], 2)
        self.assertEqual(stats["total_normalized"], 2)
        self.assertEqual(stats["inserted"], 2)
        self.assertEqual(stats["errors"], 0)

    def test_openmap_connector_reconcile_checkpoints(self):
        """Tests reconciliation between disk export files and SQLite checkpoint DB."""
        # Setup fake export files
        export_dir = os.path.join(self.temp_dir, "data", "export", "alabama")
        os.makedirs(export_dir, exist_ok=True)
        with open(os.path.join(export_dir, "healthcare.json"), "w", encoding="utf-8") as f:
            json.dump([{"name": "Clinic 1"}, {"name": "Clinic 2"}], f)

        connector = OpenMapConnector(workspace_dir=self.temp_dir)
        report = connector.reconcile_checkpoints(dry_run=False)

        self.assertEqual(report["states_inspected"], 1)
        self.assertEqual(report["exports_found"], 1)
        self.assertEqual(report["updated_records"], 1)

        # Field status should now be completed in checkpoint DB
        status = connector.checkpoint_manager.get_field_status("Alabama", "healthcare")
        self.assertIsNotNone(status)
        self.assertEqual(status["status"], "COMPLETED")
        self.assertEqual(status["records_collected"], 2)


class TestPhase3FastAPIEndpoints(unittest.TestCase):
    """Verifies all Phase 3 FastAPI endpoints in map_extraction_router."""

    def setUp(self):
        self.client = TestClient(app)
        self.temp_dir = tempfile.mkdtemp(prefix="osm_test_api_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_config(self):
        """GET /api/map-extraction/config returns valid configuration."""
        resp = self.client.get("/api/map-extraction/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("primary_endpoint", data)
        self.assertIn("fallback_endpoints", data)
        self.assertIn("connect_timeout_sec", data)
        self.assertIn("read_timeout_sec", data)
        self.assertIn("max_quadtree_depth", data)
        self.assertIn("circuit_breaker_cooldown_sec", data)

    def test_put_config_updates_runtime_settings(self):
        """PUT /api/map-extraction/config validates and updates runtime settings."""
        payload = {
            "connect_timeout_sec": 12,
            "read_timeout_sec": 48,
            "max_retries": 4,
            "circuit_breaker_cooldown_sec": 90.0,
        }
        resp = self.client.put("/api/map-extraction/config", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "updated")
        self.assertEqual(data["updated"]["connect_timeout_sec"], 12)
        self.assertEqual(data["updated"]["read_timeout_sec"], 48)
        self.assertEqual(data["config"]["connect_timeout_sec"], 12)

    def test_get_mirrors_status(self):
        """GET /api/map-extraction/mirrors returns mirror telemetry."""
        resp = self.client.get("/api/map-extraction/mirrors")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertGreaterEqual(data["total_mirrors"], 4)
        self.assertIn("active_mirror", data)
        self.assertIn("mirrors", data)
        self.assertIsInstance(data["mirrors"], list)

        first = data["mirrors"][0]
        self.assertIn("url", first)
        self.assertIn("is_healthy", first)
        self.assertIn("consecutive_failures", first)

    @patch("requests.post")
    def test_post_mirrors_test(self, mock_post):
        """POST /api/map-extraction/mirrors/test actively probes mirrors."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"elements": []}'
        mock_post.return_value = mock_resp

        payload = {"url": "https://overpass-api.de/api/interpreter", "timeout_sec": 5}
        resp = self.client.post("/api/map-extraction/mirrors/test", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["probed_count"], 1)
        self.assertEqual(data["results"][0]["status_code"], 200)
        self.assertTrue(data["results"][0]["is_healthy"])

    def test_get_states(self):
        """GET /api/map-extraction/states returns 50 US states with bounding boxes."""
        resp = self.client.get("/api/map-extraction/states")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_states"], 50)
        self.assertEqual(len(data["states"]), 50)

        alabama = next(s for s in data["states"] if s["name"] == "Alabama")
        self.assertEqual(alabama["code"], "AL")
        self.assertAlmostEqual(alabama["bbox"]["min_lat"], 30.14)
        self.assertAlmostEqual(alabama["bbox"]["max_lat"], 35.01)
        self.assertGreater(alabama["estimated_chunks"], 0)

    def test_get_fields(self):
        """GET /api/map-extraction/fields returns the 13 POI category fields."""
        resp = self.client.get("/api/map-extraction/fields")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_fields"], 13)
        field_names = [f["field"] for f in data["fields"]]
        self.assertIn("healthcare", field_names)
        self.assertIn("shop", field_names)
        self.assertIn("office", field_names)
        self.assertIn("food", field_names)
        self.assertIn("transport", field_names)

    def test_get_status(self):
        """GET /api/map-extraction/status returns overall progress and active jobs."""
        resp = self.client.get("/api/map-extraction/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["total_states"], 50)
        self.assertIn("completed_states_count", data)
        self.assertIn("total_records_collected", data)
        self.assertIn("active_jobs", data)

    def test_start_and_stop_extraction(self):
        """POST /api/map-extraction/start and /stop handle job lifecycle."""
        start_payload = {
            "state": "Alabama",
            "field": "healthcare",
            "dry_run": True
        }
        # Start
        resp = self.client.post("/api/map-extraction/start", json=start_payload)
        self.assertEqual(resp.status_code, 200)
        start_data = resp.json()
        self.assertEqual(start_data["status"], "started")
        task_id = start_data["task_id"]

        # Stop
        stop_payload = {"task_id": task_id}
        stop_resp = self.client.post("/api/map-extraction/stop", json=stop_payload)
        self.assertEqual(stop_resp.status_code, 200)
        stop_data = stop_resp.json()
        self.assertIn(stop_data["status"], ("stopped", "idle"))

    def test_ingest_endpoint_dry_run(self):
        """POST /api/map-extraction/ingest validates dry run ingestion via API."""
        # Create a temp export file to test
        temp_export = os.path.join(self.temp_dir, "export.json")
        with open(temp_export, "w", encoding="utf-8") as f:
            json.dump([
                {"osm_id": 501, "name": "Dental Care Associates", "phone": "205-555-3333", "addr:state": "AL"}
            ], f)

        ingest_payload = {
            "file_path": temp_export,
            "dry_run": True
        }
        resp = self.client.post("/api/map-extraction/ingest", json=ingest_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "completed")
        self.assertTrue(data["stats"]["dry_run"])
        self.assertEqual(data["stats"]["total_raw"], 1)
        self.assertEqual(data["stats"]["inserted"], 1)

    def test_reconcile_endpoint(self):
        """POST /api/map-extraction/reconcile runs disk reconciliation report."""
        resp = self.client.post("/api/map-extraction/reconcile", json={"dry_run": True})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "reconciled")
        self.assertIn("report", data)
        self.assertTrue(data["report"]["dry_run"])


if __name__ == "__main__":
    unittest.main()
