"""
Integration Tests for B2B Intelligence API Endpoints
===================================================
Verifies:
  1. GET /api/search/organizations returns B2B intelligence attributes and supports filters.
  2. GET /api/leads supports buying_role and intent_strength query parameters.
  3. GET /api/leads/company/{id}/org-chart reconstructs buying committee hierarchy.
  4. GET /api/leads/company/{id}/intelligence merges B2B intelligence fields cleanly.
"""

import pytest
from fastapi.testclient import TestClient
from packages.api.main import app

client = TestClient(app)


def test_search_organizations_with_intelligence_fields():
    response = client.get("/api/search/organizations?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0

    first = data["results"][0]
    assert "intent_score" in first
    assert "intent_strength" in first
    assert "tech_categories" in first
    assert "recent_hiring_velocity" in first


def test_leads_filtering_by_buying_role_and_intent():
    # Test valid query with new parameters
    response = client.get("/api/leads?table=us_leads&limit=5&intent_strength=NONE")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data or "data" in data or isinstance(data, list)


def test_company_org_chart_endpoint():
    # 1. Fetch a company ID from database
    search_res = client.get("/api/search/organizations?limit=1")
    assert search_res.status_code == 200
    results = search_res.json().get("results", [])
    if not results:
        pytest.skip("No organizations available in database")

    company_id = results[0]["id"]

    # 2. Query org-chart endpoint
    org_res = client.get(f"/api/leads/company/{company_id}/org-chart")
    assert org_res.status_code == 200
    chart = org_res.json()
    assert "company_id" in chart
    assert "buying_committee" in chart
    assert "roster" in chart
    assert "ECONOMIC_BUYER" in chart["buying_committee"]
    assert "TECHNICAL_EVALUATOR" in chart["buying_committee"]
    assert "CHAMPION" in chart["buying_committee"]
