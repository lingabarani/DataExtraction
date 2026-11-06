"""
Unit & Integration tests for EnterpriseGMapsStorage.
Verifies distributed worker lease engine (`FOR UPDATE SKIP LOCKED`),
bulk ingestion adapter (`execute_values`), heartbeats, and audit event logging.
"""

import os
import sys
import uuid
import pytest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from packages.scrapers.google_maps.postgres_storage import EnterpriseGMapsStorage


@pytest.fixture
def storage():
    return EnterpriseGMapsStorage()


def test_enterprise_gmaps_storage_full_lifecycle(storage):
    # 1. Create Job
    job_id = storage.create_job(
        job_type="GMAPS_COLLECTION",
        target_country="US",
        target_region="CA",
        parameters={"category": "restaurants", "zoom": 14},
    )
    assert job_id is not None
    assert len(job_id) == 36  # UUID string

    # 2. Register Tiles
    test_uid = uuid.uuid4().hex[:8]
    tile_1 = f"US_CA_test_{test_uid}_1"
    tile_2 = f"US_CA_test_{test_uid}_2"
    tiles = [
        {
            "tile_id": tile_1,
            "country_code": "US",
            "region": "CA",
            "min_lat": 37.70,
            "max_lat": 37.80,
            "min_lng": -122.50,
            "max_lng": -122.40,
            "priority": 150,
        },
        {
            "tile_id": tile_2,
            "country_code": "US",
            "region": "CA",
            "min_lat": 37.80,
            "max_lat": 37.90,
            "min_lng": -122.50,
            "max_lng": -122.40,
            "priority": 100,
        },
    ]
    registered = storage.register_tiles(job_id, tiles)
    assert registered == 2

    # 3. Worker 1 Claims Next Tile (should get tile_1 because priority 150 > 100)
    worker_1 = f"worker_{test_uid}_A"
    claimed_1 = storage.claim_next_tile(worker_id=worker_1, lease_seconds=120, country_code="US", region="CA", job_id=job_id)
    assert claimed_1 is not None
    assert claimed_1["tile_id"] == tile_1
    assert claimed_1["worker_id"] == worker_1
    assert claimed_1["status"] == "LEASED"

    # 4. Worker 2 Claims Next Tile (should get tile_2 via SKIP LOCKED, avoiding tile_1)
    worker_2 = f"worker_{test_uid}_B"
    claimed_2 = storage.claim_next_tile(worker_id=worker_2, lease_seconds=120, country_code="US", region="CA", job_id=job_id)
    assert claimed_2 is not None
    assert claimed_2["tile_id"] == tile_2
    assert claimed_2["worker_id"] == worker_2
    assert claimed_2["status"] == "LEASED"

    # 5. Heartbeat
    hb_ok = storage.heartbeat_tile(tile_1, worker_1, extension_seconds=300)
    assert hb_ok is True

    # 6. Bulk Upsert Scraped Places
    places = [
        {
            "cid": f"cid_{test_uid}_101",
            "tile_id": tile_1,
            "name": "Mission Burrito Bay",
            "category": "Mexican Restaurant",
            "vertical": "food_beverage",
            "phone": "+1-415-555-0101",
            "website": "https://missionburritobay.com",
            "normalized_domain": "missionburritobay.com",
            "street_address": "24th St & Mission",
            "city": "San Francisco",
            "region": "CA",
            "country_code": "US",
            "postal_code": "94110",
            "latitude": 37.752,
            "longitude": -122.418,
            "rating": 4.7,
            "review_count": 820,
        },
        {
            "cid": f"cid_{test_uid}_102",
            "tile_id": tile_1,
            "name": "Telegraph Cafe",
            "category": "Coffee Shop",
            "vertical": "food_beverage",
            "phone": "+1-415-555-0102",
            "website": "https://telegraphcafe.com",
            "normalized_domain": "telegraphcafe.com",
            "street_address": "Telegraph Hill Blvd",
            "city": "San Francisco",
            "region": "CA",
            "country_code": "US",
            "postal_code": "94133",
            "latitude": 37.802,
            "longitude": -122.405,
            "rating": 4.5,
            "review_count": 310,
        },
    ]
    upserted = storage.bulk_upsert_results(places)
    assert upserted == 2

    # 7. Complete Tile 1
    completed = storage.complete_tile(tile_1, worker_1, records_count=2)
    assert completed is True

    # 8. Fail Tile 2
    failed = storage.fail_tile(tile_2, worker_2, error_msg="Simulated tile timeout error")
    assert failed is True

    # 9. Audit Event Logging
    event_id = storage.log_event(
        job_id=job_id,
        event_type="TILE_COMPLETED",
        worker_id=worker_1,
        message="Tile 1 extracted 2 places successfully",
        payload={"tile_id": tile_1, "records": 2},
    )
    assert event_id > 0

    # 10. Update Job Status
    job_updated = storage.update_job_status(
        job_id=job_id,
        status="COMPLETED",
        completed_tiles=1,
        failed_tiles=1,
        records_collected=2,
    )
    assert job_updated is True
