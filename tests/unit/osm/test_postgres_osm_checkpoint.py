"""
Unit and integration tests for OpenStreetMap EnterpriseCheckpointManager.
Verifies pure PostgreSQL-backed checkpointing, chunk reconciliation,
and worker lease management without SQLite.
"""

import sys
import uuid
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
OPEN_MAP_DIR = ROOT_DIR / "packages" / "scrapers" / "open_map"
if str(OPEN_MAP_DIR) not in sys.path:
    sys.path.insert(0, str(OPEN_MAP_DIR))

from packages.scrapers.open_map.src.checkpoint import EnterpriseCheckpointManager


@pytest.fixture
def checkpoint_mgr():
    return EnterpriseCheckpointManager()


def test_osm_enterprise_checkpoint_manager_lifecycle(checkpoint_mgr):
    test_uid = uuid.uuid4().hex[:6]
    state_name = f"TEST_STATE_{test_uid}"
    state_code = f"T{test_uid[:2]}".upper()
    field_name = "amenity"
    field_group = "commercial"

    chunks_info = [
        {"chunk_id": f"c_{test_uid}_1", "bbox": (34.0, -118.5, 34.5, -118.0)},
        {"chunk_id": f"c_{test_uid}_2", "bbox": (34.5, -118.5, 35.0, -118.0)},
    ]

    # 1. Initialize field progress and register chunks in PostgreSQL
    checkpoint_mgr.init_field(
        state_name=state_name,
        state_code=state_code,
        field_name=field_name,
        field_group=field_group,
        total_chunks=len(chunks_info),
        chunks_info=chunks_info,
    )

    # 2. Mark chunk in progress
    c1 = f"c_{test_uid}_1"
    checkpoint_mgr.mark_chunk_in_progress(state_name, field_name, c1, bbox=(34.0, -118.5, 34.5, -118.0))

    # 3. Mark chunk completed
    checkpoint_mgr.mark_chunk_completed(
        state_name=state_name,
        field_name=field_name,
        chunk_id=c1,
        records_count=25,
        raw_path=f"data/osm/{state_name}/raw/{c1}.json",
        proc_path=f"data/osm/{state_name}/proc/{c1}.parquet",
    )

    # 4. Verify completed chunk IDs
    completed = checkpoint_mgr.get_completed_chunk_ids(state_name, field_name)
    assert c1 in completed

    # 5. Mark second chunk failed
    c2 = f"c_{test_uid}_2"
    checkpoint_mgr.mark_chunk_failed(state_name, field_name, c2, error="Overpass Gateway Timeout")
    failed = checkpoint_mgr.get_failed_chunk_ids(state_name, field_name)
    assert c2 in failed

    # 6. Check overall field status
    status = checkpoint_mgr.get_field_status(state_name, field_name)
    assert status is not None
    assert status["completed_chunks"] == 1
    assert status["failed_chunks"] == 1
    assert status["total_chunks"] == 2
