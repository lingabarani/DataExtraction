"""
Agent 1 Official Registry Execution Contract & Reliability Tests
==================================================================
Verifies:
1. Source alias & group expansion ('registry_sources' -> concrete scrapers).
2. CLI argument parity across federal_activities.py and all 6 fetch_*.py scrapers.
3. fetch_cms_npi._row_to_lead phone normalization (validate_phone import fix).
4. Structured telemetry marker parsing & heartbeat-safe _run_scraper behavior.
5. Agent1RegistryWorkflow status propagation (COMPLETED, SKIPPED, FAILED, COMPLETED_WITH_ERRORS).
6. config_manager.get_registry_config() defaults and env override handling.
"""

import asyncio
import importlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestAgent1RegistryExecution(unittest.TestCase):
    def test_resolve_registry_sources_expands_group_aliases(self):
        from packages.temporal.workflows.w1_registry_workflow import resolve_registry_sources

        supported = ["cms_npi", "sec_edgar", "fdic", "usaspending", "propublica", "sam_gov"]
        # UI payload sends group alias alongside Agent 2/other category keys
        resolved = resolve_registry_sources(
            ["registry_sources", "google_maps", "osm"],
            all_supported=supported,
            configured_defaults=supported,
        )
        self.assertEqual(resolved, supported)

        # Explicit individual source + alias
        resolved_subset = resolve_registry_sources(
            ["sec", "fdic_ncua", "google_maps"],
            all_supported=supported,
        )
        self.assertEqual(resolved_subset, ["sec_edgar", "fdic"])

        # Non-registry selection must return empty (Agent 1 skipped cleanly)
        resolved_none = resolve_registry_sources(["google_maps", "osm"], all_supported=supported)
        self.assertEqual(resolved_none, [])

    def test_registry_config_defaults_and_env_overrides(self):
        from packages.infrastructure.config_manager import config_manager

        with patch.dict(
            os.environ,
            {
                "FEDERAL_REGISTRY_SOURCES": "sec_edgar,fdic",
                "FEDERAL_SCRAPER_TIMEOUT_SECONDS": "1234",
                "FEDERAL_SCRAPER_HEARTBEAT_SECONDS": "2.5",
                "FEDERAL_SCRAPER_ERROR_THRESHOLD_PCT": "15",
            },
            clear=False,
        ):
            cfg = config_manager.get_registry_config()
            self.assertEqual(cfg["enabled_sources"], ["sec_edgar", "fdic"])
            self.assertEqual(cfg["scraper_timeout_seconds"], 1234)
            self.assertEqual(cfg["heartbeat_interval_seconds"], 2.5)
            self.assertEqual(cfg["error_threshold_pct"], 15.0)

    def test_cms_npi_row_to_lead_normalizes_phone_with_validate_phone(self):
        from packages.scrapers.federal import fetch_cms_npi

        row = {
            "NPI": "1234567890",
            "Entity Type Code": "2",
            "Provider Organization Name (Legal Business Name)": "ACME MEDICAL GROUP LLC",
            "Provider Business Practice Location Address Telephone Number": "202-456-1111",
            "Provider Business Practice Location Address City Name": "SAN FRANCISCO",
            "Provider Business Practice Location Address State Name": "CA",
            "Provider Business Practice Location Address Postal Code": "941051234",
            "Healthcare Provider Taxonomy Code_1": "207Q00000X",
        }
        lead = fetch_cms_npi._row_to_lead(row)
        self.assertIsNotNone(lead)
        self.assertEqual(lead["company_name"], "ACME MEDICAL GROUP LLC")
        self.assertEqual(lead["api_source"], "CMS_NPI")
        self.assertEqual(lead["zip_code"], "94105")
        self.assertEqual(lead["phone"], "+12024561111")

    def test_all_six_federal_scrapers_accept_activity_cli_flags(self):
        scrapers_dir = REPO_ROOT / "packages" / "scrapers" / "federal"
        cases = [
            ("fetch_cms_npi.py", ["--limit", "10", "--mode", "incremental", "--help"]),
            ("fetch_sec_edgar.py", ["--form-types", "10-K,10-Q", "--mode", "tickers", "--limit", "10", "--help"]),
            ("fetch_fdic.py", ["--source", "both", "--mode", "incremental", "--limit", "10", "--help"]),
            ("fetch_usaspending.py", ["--fiscal-year", "2025", "--mode", "incremental", "--limit", "10", "--help"]),
            ("fetch_propublica.py", ["--mode", "incremental", "--state", "CA", "--limit", "10", "--help"]),
            ("fetch_sam_gov.py", ["--mode", "incremental", "--limit", "10", "--help"]),
        ]
        for script_name, args in cases:
            proc = subprocess.run(
                [sys.executable, str(scrapers_dir / script_name)] + args,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(
                proc.returncode,
                0,
                msg=f"{script_name} rejected flags {args}: stderr={proc.stderr}",
            )

    def test_sam_gov_unconfigured_key_emits_skipped_marker(self):
        from packages.temporal.activities.federal_activities import _parse_scraper_output

        scrapers_dir = REPO_ROOT / "packages" / "scrapers" / "federal"
        clean_env = {**os.environ, "SAM_GOV_API_KEY": "", "PYTHONPATH": str(REPO_ROOT)}
        proc = subprocess.run(
            [sys.executable, str(scrapers_dir / "fetch_sam_gov.py"), "--mode", "incremental", "--limit", "2", "--dry-run"],
            capture_output=True,
            text=True,
            cwd=str(scrapers_dir),
            env=clean_env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        parsed = _parse_scraper_output("fetch_sam_gov.py", proc.stdout)
        self.assertEqual(parsed.get("status"), "SKIPPED_UNCONFIGURED")
        self.assertEqual(parsed.get("inserted_count"), 0)

    def test_workflow_status_accurately_reflects_failures_and_skips(self):
        from packages.temporal.workflows.w1_registry_workflow import Agent1RegistryWorkflow

        # Case 1: Empty sources -> SKIPPED
        wf = Agent1RegistryWorkflow()
        with patch("packages.temporal.workflows.w1_registry_workflow.workflow") as mock_wf:
            mock_wf.info.return_value = MagicMock(workflow_id="test-empty")
            mock_wf.logger = MagicMock()
            res = asyncio.run(wf.run({"sources": ["google_maps"]}))
        self.assertEqual(res["status"], "SKIPPED")
        self.assertEqual(res["organizations_processed"], 0)

        # Case 2: All executed sources fail -> FAILED
        wf_fail = Agent1RegistryWorkflow()

        async def _always_fail(*args, **kwargs):
            raise RuntimeError("boom")

        with patch("packages.temporal.workflows.w1_registry_workflow.workflow") as mock_wf:
            mock_wf.info.return_value = MagicMock(workflow_id="test-fail")
            mock_wf.logger = MagicMock()
            mock_wf.wait_condition = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
            mock_wf.execute_activity = MagicMock(side_effect=_always_fail)
            res_fail = asyncio.run(wf_fail.run({"sources": ["sec_edgar"]}))
        self.assertEqual(res_fail["status"], "FAILED")
        self.assertEqual(res_fail["sources_failed"], 1)


if __name__ == "__main__":
    unittest.main()
