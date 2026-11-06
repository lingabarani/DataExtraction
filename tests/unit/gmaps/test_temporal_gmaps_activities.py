"""
Unit tests for Google Maps Temporal Activities
Tests collection dry-run, website verification, crawl, and export activities.
"""

import pytest
from unittest.mock import patch, MagicMock
from packages.temporal.activities.gmaps_activities import (
    run_gmaps_collection_activity,
    run_gmaps_website_verification_activity,
    run_gmaps_website_crawl_activity,
    run_gmaps_export_activity,
)


@pytest.mark.asyncio
async def test_run_gmaps_collection_activity_dry_run():
    tile_cfg = {"dry_run": True, "limit": 10}
    with patch("temporalio.activity.heartbeat") as mock_hb:
        res = await run_gmaps_collection_activity(
            region="US-CA",
            category="healthcare",
            tile_config=tile_cfg,
        )
        assert res["status"] == "SUCCESS"
        assert res["mode"] == "dry_run"
        assert res["region"] == "US-CA"
        assert res["category"] == "healthcare"
        assert res["collected"] >= 1
        assert mock_hb.called


@pytest.mark.asyncio
async def test_run_gmaps_website_verification_activity_offline():
    with patch("temporalio.activity.heartbeat"):
        res = await run_gmaps_website_verification_activity("batch_123", limit=10)
        assert res["status"] == "SUCCESS"
        assert "verified" in res
        assert "failed" in res


@pytest.mark.asyncio
async def test_run_gmaps_website_crawl_activity_offline():
    with patch("temporalio.activity.heartbeat"):
        res = await run_gmaps_website_crawl_activity("batch_123")
        assert res["status"] == "SUCCESS"
        assert "crawled" in res
        assert "contacts_found" in res


@pytest.mark.asyncio
async def test_run_gmaps_export_activity():
    res = await run_gmaps_export_activity("job_test", export_format="csv")
    assert res["status"] == "SUCCESS"
    assert res["format"] == "csv"
    assert "output_path" in res

