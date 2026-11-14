"""
DataExtraction — Phase 1 Integration Tests: Orchestration API & Signals
========================================================================
Validates Phase 1 API extensions:
  1. GET /api/orchestration/header/status
  2. GET /api/orchestration/queues/status
  3. POST /api/orchestration/start (Presets, Countries, Sources, Execution Mode)
  4. POST /api/orchestration/{id}/signal (pause, resume, retry, restart, emergency_halt)
  5. GET /api/orchestration/{id}/status
"""

import pytest
from fastapi.testclient import TestClient

from packages.api.main import app
from packages.api.dependencies import get_current_user, require_admin, UserPrincipal

client = TestClient(app)

mock_admin = UserPrincipal(
    id="admin_001",
    email="admin@dataextraction.ai",
    name="System Administrator",
    role="admin",
    scopes=["read", "write", "admin"],
)


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user] = lambda: mock_admin
    app.dependency_overrides[require_admin] = lambda: mock_admin
    yield
    app.dependency_overrides.clear()


def test_get_orchestration_header_status():
    """Validates high-speed consolidated command header telemetry."""
    response = client.get("/api/orchestration/header/status")
    assert response.status_code == 200
    data = response.json()

    assert data["platform_status"] == "ONLINE"
    assert data["database_status"] == "CONNECTED"
    assert data["opensearch_status"] == "SYNCED"
    assert data["onereach_status"] in ("ACTIVE", "IDLE")
    assert "active_workflows" in data
    assert "last_successful_run" in data
    assert data["last_successful_run"]["certified_records"] > 0


def test_get_orchestration_queues_status():
    """Validates real-time telemetry across all 7 dedicated Temporal queues."""
    response = client.get("/api/orchestration/queues/status")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "SUCCESS"
    assert len(data["queues"]) == 7

    queue_ids = [q["id"] for q in data["queues"]]
    expected_ids = [
        "registry-ingestion-queue",
        "geospatial-domain-queue",
        "identity-clustering-queue",
        "email-enrichment-queue",
        "executive-contact-queue",
        "governance-quality-queue",
        "search-persistence-queue",
    ]
    for eq in expected_ids:
        assert eq in queue_ids, f"Queue {eq} missing from telemetry!"


def test_start_and_signal_orchestration_saga():
    """Validates starting a saga with custom operator presets and dispatching signals."""
    start_payload = {
        "data_count": 5000,
        "countries": ["US", "Mexico"],
        "sources": ["registry_sources", "google_maps"],
        "execution_mode": "INCREMENTAL",
    }
    start_res = client.post("/api/orchestration/start", json=start_payload)
    assert start_res.status_code == 202
    start_data = start_res.json()

    wf_id = start_data["workflow_id"]
    assert wf_id is not None
    assert start_data["status"] == "ACCEPTED"

    # Verify status
    status_res = client.get(f"/api/orchestration/{wf_id}/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["workflow_id"] == wf_id

    # Test PAUSE Signal
    pause_res = client.post(f"/api/orchestration/{wf_id}/signal", json={"signal_name": "pause"})
    assert pause_res.status_code == 200
    assert pause_res.json()["signal_delivered"] == "pause"

    # Test RESUME Signal
    resume_res = client.post(f"/api/orchestration/{wf_id}/signal", json={"signal_name": "resume"})
    assert resume_res.status_code == 200
    assert resume_res.json()["signal_delivered"] == "resume"

    # Test RETRY PHASE Signal
    retry_res = client.post(f"/api/orchestration/{wf_id}/signal", json={"signal_name": "retry_phase", "phase": "REGISTRY_INGESTION"})
    assert retry_res.status_code == 200
    assert retry_res.json()["signal_delivered"] == "retry_phase"

    # Test EMERGENCY HALT Signal
    halt_res = client.post(f"/api/orchestration/{wf_id}/signal", json={"signal_name": "emergency_halt"})
    assert halt_res.status_code == 200
    assert halt_res.json()["signal_delivered"] == "emergency_halt"

