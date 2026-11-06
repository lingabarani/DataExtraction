"""
DataExtraction — Sprint 5 Governance & Promotion Gate API Test Suite
===================================================================
Verifies:
  1. GET /api/governance/stats: Live telemetry for Pre-Master Working Layer & Master Vault
  2. POST /api/governance/promotion/trigger: Atomic promotion gate API execution
  3. POST /api/governance/revalidation/sweep: Autonomous freshness decay & revalidation sweep API
  4. GET /api/governance/revalidation/overdue: Active SLA overdue entities inspection
  5. GET /api/governance/quarantine/records: Quarantined isolation records inspection
"""

import sys
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "api")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.api.main import create_app
from packages.api.dependencies import get_current_user, UserPrincipal


@pytest.fixture(scope="module")
def api_client():
    app = create_app()

    # Override authentication for automated integration tests
    def mock_current_user():
        return UserPrincipal(
            id="test-architect-01",
            email="architect@dataextraction.ai",
            name="Principal Architect",
            workspace_id="ws-001",
            is_admin=True,
        )

    app.dependency_overrides[get_current_user] = mock_current_user
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_get_governance_stats(api_client):
    """Verify live telemetry for Working Layer, Master Vault, and Governance Gate."""
    res = api_client.get("/api/governance/stats")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "HEALTHY"
    assert "working_layer" in data
    assert "master_vault" in data
    assert "governance_gate" in data

    # Verify Master Vault totals
    mv = data["master_vault"]
    assert mv["total_organizations"] >= 200000
    assert mv["average_quality_score"] > 0
    assert mv["average_trust_score"] >= 0.85
    assert mv["average_freshness_score"] > 0

    # Verify Gate thresholds
    gate = data["governance_gate"]
    assert gate["certification_threshold_quality"] == 80
    assert gate["certification_threshold_trust"] == 0.8500


def test_trigger_promotion_gate_api(api_client):
    """Verify triggering atomic single-transaction promotion gate via API."""
    payload = {
        "min_quality": 80,
        "min_trust": 0.85,
        "batch_size": 50,
        "auto_evaluate_pre_master": True,
    }
    res = api_client.post("/api/governance/promotion/trigger", json=payload)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "COMPLETED"
    assert "promotion_gate_outcome" in data


def test_trigger_revalidation_sweep_api(api_client):
    """Verify triggering freshness decay and SLA revalidation sweep via API."""
    payload = {
        "batch_size": 50,
        "auto_reharvest": True,
    }
    res = api_client.post("/api/governance/revalidation/sweep", json=payload)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data = res.json()
    assert data["status"] == "COMPLETED"
    assert "freshness_decay" in data
    assert data["freshness_decay"]["status"] == "COMPLETED"


def test_get_overdue_revalidations_api(api_client):
    """Verify inspecting entities overdue for SLA revalidation."""
    res = api_client.get("/api/governance/revalidation/overdue?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert "records" in data
    assert isinstance(data["records"], list)


def test_get_quarantine_records_api(api_client):
    """Verify inspecting quarantined isolation records."""
    res = api_client.get("/api/governance/quarantine/records?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "records" in data
    assert isinstance(data["records"], list)
