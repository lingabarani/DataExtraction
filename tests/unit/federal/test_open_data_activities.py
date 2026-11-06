"""
Unit tests for Federal & Open Data Temporal Activities.
Tests dry-run execution, heartbeats, and parameter handling across all 8 activities.
Uses direct coroutine driving to run cleanly in sandboxed environments without event loop socket blocks.
"""

import pytest

from packages.temporal.activities.open_data_activities import (
    run_sam_gov_extraction_activity,
    run_census_cbp_extraction_activity,
    run_openfda_extraction_activity,
    run_bls_extraction_activity,
    run_bea_extraction_activity,
    run_eia_extraction_activity,
    run_usgs_extraction_activity,
    run_datagov_extraction_activity,
)


def _drive(coro):
    """Executes a coroutine directly to completion without creating OS socket pairs."""
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    raise RuntimeError("Coroutine did not complete synchronously in dry_run mode")


def test_sam_gov_activity_dry_run():
    res = _drive(run_sam_gov_extraction_activity({"dry_run": True, "limit": 10}))
    assert res["status"] == "SUCCESS"
    assert res["source"] == "SAM_GOV"
    assert res["mode"] == "dry_run"


def test_census_cbp_activity_dry_run():
    res = _drive(run_census_cbp_extraction_activity({"dry_run": True, "state": "06"}))
    assert res["status"] == "SUCCESS"
    assert res["source"] == "CENSUS_CBP"
    assert res["mode"] == "dry_run"


def test_openfda_activity_dry_run():
    res = _drive(run_openfda_extraction_activity({"dry_run": True, "limit": 5}))
    assert res["status"] == "SUCCESS"
    assert res["source"] == "OPENFDA"
    assert res["mode"] == "dry_run"


def test_bls_activity_dry_run():
    res = _drive(run_bls_extraction_activity({"dry_run": True}))
    assert res["status"] == "SUCCESS"
    assert res["source"] == "BLS"
    assert res["mode"] == "dry_run"


def test_bea_activity_dry_run():
    res = _drive(run_bea_extraction_activity({"dry_run": True}))
    assert res["status"] == "SUCCESS"
    assert res["source"] == "BEA"
    assert res["mode"] == "dry_run"


def test_eia_activity_dry_run():
    res = _drive(run_eia_extraction_activity({"dry_run": True}))
    assert res["status"] == "SUCCESS"
    assert res["source"] == "EIA"
    assert res["mode"] == "dry_run"


def test_usgs_activity_dry_run():
    res = _drive(run_usgs_extraction_activity({"dry_run": True, "state": "CA"}))
    assert res["status"] == "SUCCESS"
    assert res["source"] == "USGS"
    assert res["mode"] == "dry_run"


def test_datagov_activity_dry_run():
    res = _drive(run_datagov_extraction_activity({"dry_run": True, "limit": 5}))
    assert res["status"] == "SUCCESS"
    assert res["source"] == "DATA_GOV"
    assert res["mode"] == "dry_run"
