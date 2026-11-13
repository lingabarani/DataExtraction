"""
Agent 2 Geospatial & Domain Discovery Execution Contract & Reliability Tests
============================================================================
Verifies:
1. Source alias & group expansion ('geospatial_sources', 'gmaps', 'osm').
2. Country/region/state derivation and cancelled_region filtering.
3. ConfigManager.get_geospatial_config() defaults and GEOSPATIAL_* env overrides.
4. OSM activity: non-US state SKIPPED, dry_run planning, canonical staging_companies
   (with company_email so 0 synthetic people) + master_dataextraction.locations persistence,
   and Overpass all-chunk failure reporting.
5. GMaps website verification SSRF 2-tuple unpacking ((False, reason) must block!).
6. validate_geo_activity reading/updating staging_dataextraction.staging_companies and failing honestly when DB offline.
7. Agent2GeospatialWorkflow honest status propagation (SKIPPED, FAILED, COMPLETED_WITH_ERRORS, COMPLETED).
"""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestAgent2GeospatialExecution(unittest.TestCase):
    def test_resolve_geospatial_sources_expands_aliases_and_ignores_unrelated(self):
        from packages.temporal.workflows.w2_geospatial_workflow import resolve_geospatial_sources

        resolved = resolve_geospatial_sources(["registry_sources", "geospatial_sources", "sec_edgar"])
        self.assertEqual(resolved, ["google_maps", "openstreetmap"])

        resolved_subset = resolve_geospatial_sources(["gmaps", "sec_edgar"])
        self.assertEqual(resolved_subset, ["google_maps"])

        resolved_osm = resolve_geospatial_sources(["osm"])
        self.assertEqual(resolved_osm, ["openstreetmap"])

        resolved_none = resolve_geospatial_sources(["sec_edgar", "cms_npi"])
        self.assertEqual(resolved_none, [])

        resolved_default = resolve_geospatial_sources(None)
        self.assertEqual(resolved_default, ["google_maps", "openstreetmap"])

    def test_regions_and_states_derivation_from_countries_and_cancellations(self):
        from packages.temporal.workflows.w2_geospatial_workflow import _resolve_regions_and_states

        defaults = {
            "us_regions": ["US-CA", "US-TX", "US-NY"],
            "mx_regions": ["MX-CMX", "MX-JAL"],
        }
        regions, states = _resolve_regions_and_states(
            {"countries": ["US", "MX"]},
            defaults,
            {"US-NY"},
        )
        self.assertEqual(regions, ["US-CA", "US-TX", "MX-CMX", "MX-JAL"])
        self.assertEqual(states, ["CA", "TX"])

    def test_geospatial_config_defaults_and_env_overrides(self):
        from packages.infrastructure.config_manager import config_manager

        with patch.dict(
            os.environ,
            {
                "GEOSPATIAL_SOURCES": "openstreetmap",
                "GEOSPATIAL_BATCH_LIMIT": "75",
                "GEOSPATIAL_OSM_MAX_CHUNKS_PER_FIELD": "3",
                "GEOSPATIAL_KG_ENABLED": "false",
            },
            clear=False,
        ):
            cfg = config_manager.get_geospatial_config()
            self.assertEqual(cfg["enabled_sources"], ["openstreetmap"])
            self.assertEqual(cfg["default_batch_limit"], 75)
            self.assertEqual(cfg["osm_max_chunks_per_field"], 3)
            self.assertFalse(cfg["kg_observation_enabled"])

    def test_osm_activity_skips_invalid_region_and_supports_us_and_mx_canonical_records(self):
        from packages.temporal.activities.osm_activities import run_osm_state_extraction_activity

        skip_res = asyncio.run(run_osm_state_extraction_activity("ZZ-INVALID", {}))
        self.assertEqual(skip_res["status"], "SKIPPED")
        self.assertEqual(skip_res["extracted"], 0)

        mx_dry_res = asyncio.run(run_osm_state_extraction_activity("MX-CMX", {"dry_run": True}))
        self.assertEqual(mx_dry_res["status"], "SUCCESS")
        self.assertEqual(mx_dry_res["mode"], "dry_run")
        self.assertEqual(mx_dry_res.get("country"), "MX")
        self.assertGreater(mx_dry_res["extracted"], 0)

        dry_res = asyncio.run(run_osm_state_extraction_activity("CA", {"dry_run": True}))
        self.assertEqual(dry_res["status"], "SUCCESS")
        self.assertEqual(dry_res["mode"], "dry_run")
        self.assertGreater(dry_res["extracted"], 0)

        sample_poi = {
            "osm_type": "node",
            "osm_id": 987654321,
            "name": "Golden Gate Coffee Roasters",
            "osm_key": "shop",
            "osm_value": "coffee",
            "category": "coffee",
            "addr:housenumber": "123",
            "addr:street": "Market St",
            "addr:city": "San Francisco",
            "addr:state": "CA",
            "addr:postcode": "94105",
            "latitude": 37.7749,
            "longitude": -122.4194,
            "phone": "+1-415-555-0100",
            "email": "hello@ggcoffee.example.com",
            "website": "https://ggcoffee.example.com",
            "source_url": "https://www.openstreetmap.org/node/987654321",
            "collected_at": "2026-11-12T00:00:00+00:00",
            "raw_tags": {"shop": "coffee", "name": "Golden Gate Coffee Roasters"},
        }

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with patch("src.osm_state_collector.OSMStateCollector") as mock_cls, \
             patch("packages.infrastructure.db_connector.get_connection", return_value=mock_conn), \
             patch("packages.infrastructure.db_connector.release_connection"), \
             patch("packages.infrastructure.staging_writer.bulk_upsert_staging_records", return_value=(1, 0)) as mock_bulk, \
             patch("packages.infrastructure.staging_writer.upsert_master_locations", return_value=1) as mock_loc:
            collector_inst = MagicMock()
            collector_inst.progress_data = {}
            collector_inst.process_state.return_value = {
                "state": "California",
                "state_code": "CA",
                "status": "in_progress",
                "fields": {"shop": 1},
                "total_records": 1,
                "collected_records": [sample_poi],
            }
            mock_cls.return_value = collector_inst

            res = asyncio.run(run_osm_state_extraction_activity("CA", {"limit": 5, "max_chunks_per_field": 1}))

        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["extracted"], 1)
        self.assertEqual(res["postgres_inserted"], 1)
        self.assertEqual(res["locations_upserted"], 1)
        mock_conn.commit.assert_called_once()
        mock_loc.assert_called_once()

        # Verify company_email used instead of email so bulk upsert creates 0 fake people
        passed_records = mock_bulk.call_args[0][1]
        self.assertEqual(passed_records[0]["id"], "osm_node_987654321")
        self.assertEqual(passed_records[0]["company_email"], "hello@ggcoffee.example.com")
        self.assertNotIn("email", passed_records[0])

    def test_osm_activity_reports_failed_when_all_chunks_fail(self):
        from packages.temporal.activities.osm_activities import run_osm_state_extraction_activity

        with patch("src.osm_state_collector.OSMStateCollector") as mock_cls:
            collector_inst = MagicMock()
            collector_inst.progress_data = {
                "California": {
                    "shop": {"stats": {"successful_chunks": 0, "failed_chunks": 2}}
                }
            }
            collector_inst.process_state.return_value = {
                "state": "California",
                "state_code": "CA",
                "status": "in_progress",
                "fields": {"shop": 0},
                "total_records": 0,
                "collected_records": [],
            }
            mock_cls.return_value = collector_inst

            res = asyncio.run(run_osm_state_extraction_activity("CA", {"limit": 5}))

        self.assertEqual(res["status"], "FAILED")
        self.assertIn("Overpass", res["error"])

    def test_website_verification_blocks_ssrf_tuple_false(self):
        from packages.temporal.activities.gmaps_activities import run_gmaps_website_verification_activity

        query_conn = MagicMock()
        query_cur = MagicMock()
        query_cur.fetchall.return_value = [
            ("gmaps_ssrf_1", "Internal Metadata", "http://169.254.169.254/latest/meta-data", None, "Austin", "TX", "tech"),
        ]
        query_conn.cursor.return_value = query_cur

        update_conn = MagicMock()
        update_cur = MagicMock()
        update_conn.cursor.return_value = update_cur

        with patch("packages.temporal.activities.gmaps_activities._get_postgres_connection", side_effect=[query_conn, update_conn]), \
             patch("packages.temporal.activities.gmaps_activities._release_postgres_connection"), \
             patch("gmaps_scraper.website.ssrf.is_safe_url", return_value=(False, "Private/metadata IP blocked")) as mock_ssrf, \
             patch("gmaps_scraper.website.verifier.WebsiteVerifier") as mock_verifier_cls:
            res = asyncio.run(run_gmaps_website_verification_activity("batch_ssrf", limit=5))

        mock_ssrf.assert_called_once()
        mock_verifier_cls.return_value.verify.assert_not_called()
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["verified"], 0)
        self.assertEqual(res["failed"], 1)
        update_conn.commit.assert_called_once()

    def test_validate_geo_updates_staging_companies_and_fails_when_db_offline(self):
        from packages.temporal.activities.pipeline_activities import validate_geo_activity

        with patch("packages.infrastructure.db_connector.get_connection", return_value=None):
            offline_res = asyncio.run(validate_geo_activity("staging_dataextraction.staging_companies", limit=10))
        self.assertEqual(offline_res["status"], "FAILED")

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # Swapped coordinates (-122.4194, 37.7749) and leading-zero stripped US ZIP "2138"
        mock_cur.fetchall.return_value = [
            ("osm_node_1", "2138", "United States", {"latitude": -122.4194, "longitude": 37.7749}),
        ]
        mock_conn.cursor.return_value = mock_cur

        with patch("packages.infrastructure.db_connector.get_connection", return_value=mock_conn), \
             patch("packages.infrastructure.db_connector.release_connection"):
            ok_res = asyncio.run(validate_geo_activity("companies", limit=10, sources=["GOOGLE_MAPS", "OPENSTREETMAP"]))

        self.assertEqual(ok_res["status"], "SUCCESS")
        self.assertEqual(ok_res["table"], "staging_dataextraction.staging_companies")
        self.assertEqual(ok_res["validated"], 1)
        self.assertEqual(ok_res["updated"], 1)
        mock_conn.commit.assert_called_once()
        select_sql, select_params = mock_cur.execute.call_args_list[0][0]
        self.assertIn("source = ANY(%s)", select_sql)
        self.assertEqual(select_params[0], ["GOOGLE_MAPS", "OPENSTREETMAP"])
        update_sql, update_params = mock_cur.execute.call_args_list[1][0]
        self.assertIn("UPDATE staging_dataextraction.staging_companies", update_sql)
        self.assertEqual(update_params[0], "02138")
        patch_json = json.loads(update_params[1])
        self.assertTrue(patch_json["geo_valid"])
        self.assertTrue(patch_json["geo_swapped_corrected"])
        self.assertEqual(patch_json["latitude"], 37.7749)
        self.assertEqual(patch_json["longitude"], -122.4194)

    def test_agent2_workflow_status_calculations_and_kg_degradation(self):
        from packages.temporal.workflows.w2_geospatial_workflow import Agent2GeospatialWorkflow

        # 1. SKIPPED when non-geospatial sources only
        wf_skip = Agent2GeospatialWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"):
            mock_info.return_value.workflow_id = "test-a2-skip"
            res_skip = asyncio.run(wf_skip.run({"sources": ["sec_edgar"]}))
        self.assertEqual(res_skip["status"], "SKIPPED")

        # 2. FAILED when all collection activities fail
        wf_fail = Agent2GeospatialWorkflow()
        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_activity", new=AsyncMock(return_value={"status": "FAILED", "postgres_inserted": 0})):
            mock_info.return_value.workflow_id = "test-a2-fail"
            res_fail = asyncio.run(wf_fail.run({"sources": ["google_maps"], "regions": ["US-CA"]}))
        self.assertEqual(res_fail["status"], "FAILED")
        self.assertEqual(res_fail["spatial_standardized"], 0)

        # 3. COMPLETED with KG storage offline gracefully handled
        wf_ok = Agent2GeospatialWorkflow()

        async def _mock_exec(act_fn, args=None, **kwargs):
            name = getattr(act_fn, "__name__", str(act_fn))
            if "gmaps_collection" in name:
                return {"status": "SUCCESS", "postgres_inserted": 6, "locations_upserted": 6}
            if "osm_state_extraction" in name:
                return {"status": "SUCCESS", "extracted": 4, "postgres_inserted": 4, "locations_upserted": 4}
            if "website_verification" in name:
                return {"status": "SUCCESS", "verified": 5, "failed": 1}
            if "website_crawl" in name:
                return {"status": "SUCCESS", "crawled": 3, "contacts_found": 7}
            if "validate_geo" in name:
                return {"status": "SUCCESS", "validated": 10, "failed": 0, "updated": 10}
            if "ingest_kg_observation" in name:
                raise RuntimeError("MinIO localhost:9000 offline")
            return {"status": "SUCCESS"}

        with patch("temporalio.workflow.info") as mock_info, \
             patch("temporalio.workflow.logger"), \
             patch("temporalio.workflow.wait_condition", new=AsyncMock()), \
             patch("temporalio.workflow.execute_activity", side_effect=_mock_exec):
            mock_info.return_value.workflow_id = "test-a2-ok"
            res_ok = asyncio.run(wf_ok.run({"regions": ["US-CA"], "states": ["CA"]}))

        self.assertEqual(res_ok["status"], "COMPLETED")
        self.assertEqual(res_ok["spatial_standardized"], 10)
        self.assertEqual(res_ok["websites_verified"], 5)
        self.assertEqual(res_ok["contacts_found"], 7)
        self.assertEqual(res_ok["geo_validated"], 10)
        self.assertEqual(res_ok["results"]["kg_observation"]["status"], "SKIPPED_STORAGE_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
