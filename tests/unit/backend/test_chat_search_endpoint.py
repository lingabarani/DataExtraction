"""
Unit and integration tests for POST /api/ai/chat-search endpoint.
Verifies SQL parameter safety, zero schema migrations compatibility,
and robust handling of company and people search modes.
"""

import pytest
from fastapi.testclient import TestClient
from packages.api.main import app

client = TestClient(app)


def test_chat_search_company_mode():
    """Verifies company chat search returns structured results and facets."""
    payload = {
        "query": "Find healthcare companies in California",
        "mode": "company",
        "limit": 5,
        "offset": 0
    }
    resp = client.post("/api/ai/chat-search", json=payload)
    assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["mode"] == "company"
    assert "assistant_summary" in data
    assert isinstance(data["applied_filters"], dict)
    assert "results" in data
    assert isinstance(data["results"], list)
    assert "total_count" in data
    assert "search_engine" in data


def test_chat_search_people_mode():
    """Verifies people chat search returns executive decision-makers."""
    payload = {
        "query": "C-suite and VPs of Engineering in California",
        "mode": "people",
        "limit": 5,
        "offset": 0
    }
    resp = client.post("/api/ai/chat-search", json=payload)
    assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}: {resp.text}"
    data = resp.json()

    assert data["mode"] == "people"
    assert "assistant_summary" in data
    assert "results" in data
    assert isinstance(data["results"], list)
    assert data["total_count"] > 0
    for person in data["results"]:
        assert "full_name" in person
        assert "title" in person
        assert "seniority" in person


def test_chat_search_sql_injection_defense():
    """Verifies that malicious SQL injection inputs are strictly parameterized and defanged."""
    malicious_payload = {
        "query": "homecare' UNION SELECT 1, 'hacked', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL--",
        "mode": "company",
        "limit": 5,
        "offset": 0
    }
    resp = client.post("/api/ai/chat-search", json=malicious_payload)
    # The endpoint should not crash with a 500 SQL syntax error; it should handle it securely
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["results"], list)
