"""Discovery API: authentication, validation, SSE event order, replay, export. Sources are mocked."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from packages.api import dependencies as deps
from packages.api.dependencies import UserPrincipal, get_current_user
from packages.api.main import app
from packages.api.routers import discovery_router as dr
from packages.discovery.models import OrgRecord, PhoneEntry, SourceResult, SourceStatus
from packages.discovery.orchestrator import DiscoveryOrchestrator

USER = UserPrincipal(id="u1", email="u@test", name="U", is_admin=False)
ADMIN = UserPrincipal(id="a1", email="a@test", name="A", is_admin=True)


class _Src:
    def __init__(self, name, orgs):
        self.name, self._orgs = name, orgs

    async def search(self, intent, budget):
        yield SourceResult(organizations=[o.model_copy(deep=True) for o in self._orgs],
                           status=SourceStatus(name=self.name, status="ok", count=len(self._orgs)))


@pytest.fixture
def client(monkeypatch):
    orgs = [OrgRecord(name="Test Care One", category="home care", phones=[PhoneEntry(number="7045550101")],
                      address={"street": "1 Test Way", "city": "Charlotte", "state": "NC", "postal_code": "28202"})]
    orch = DiscoveryOrchestrator(sources=[_Src("mock_source", orgs)])
    orch.website_crawler = orch.linkedin_source = None
    monkeypatch.setattr(dr, "_orchestrator", orch)
    monkeypatch.setattr(dr, "get_search_run", lambda run_id: None)
    dr._active_searches.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def as_user(principal):
    app.dependency_overrides[get_current_user] = lambda: principal


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines.get("data", "{}"))))
    return events


def test_routes_require_authentication(client, monkeypatch):
    monkeypatch.setattr(deps.config_manager, "is_auth_required", lambda: True)
    assert client.post("/api/v1/discovery/search", json={"query": "home care in Charlotte NC"}).status_code == 401
    assert client.get(f"/api/v1/discovery/search/{uuid.uuid4()}").status_code == 401
    assert client.get(f"/api/v1/discovery/organizations/{uuid.uuid4()}").status_code == 401
    assert client.get("/api/v1/discovery/sources/status").status_code == 401


def test_sources_status_is_admin_only(client):
    as_user(USER)
    assert client.get("/api/v1/discovery/sources/status").status_code == 403
    as_user(ADMIN)
    resp = client.get("/api/v1/discovery/sources/status")
    assert resp.status_code == 200 and [s["source"] for s in resp.json()] == ["mock_source"]


@pytest.mark.parametrize("body", [{"query": ""}, {"query": "x" * 301}, {"query": "a", "budget_seconds": 1},
                                  {"query": "a", "filters": {"drop_tables": True}},
                                  {"query": "a", "filters": {"max_results": 0}},
                                  {"query": "a", "filters": {"max_results": 5000}},
                                  {"query": "a", "filters": {"max_results": "lots"}},
                                  {"query": "a", "filters": {"sources": "database_dump"}},
                                  {"query": "a", "filters": {"crawl_websites": "yes"}}])
def test_validation(client, body):
    as_user(USER)
    assert client.post("/api/v1/discovery/search", json=body).status_code == 422


def test_new_search_options_are_accepted(client):
    as_user(USER)
    body = {"query": "plumbers in Austin TX",
            "filters": {"max_results": 1000, "sources": "internet", "crawl_websites": False}}
    assert client.post("/api/v1/discovery/search", json=body).status_code == 202


def test_stream_emits_events_in_order_then_replays(client):
    as_user(USER)
    init = client.post("/api/v1/discovery/search", json={"query": "home care in Charlotte NC", "budget_seconds": 10})
    assert init.status_code == 202
    sid = init.json()["search_id"]
    events = parse_sse(client.get(f"/api/v1/discovery/search/{sid}/stream").text)
    names = [e for e, _ in events]
    assert names[0] == "plan"
    for required in ("source_started", "result", "source_done", "entities_resolved", "answer", "done"):
        assert required in names
    assert names.index("source_started") < names.index("result") < names.index("source_done") < names.index("answer")
    answer = dict(events)["answer"]
    assert answer["total_organizations"] == 1 and answer["cards"][0]["phone"] == "(704) 555-0101"
    # A finished search is replayed, not re-run
    replay = parse_sse(client.get(f"/api/v1/discovery/search/{sid}/stream").text)
    assert [e for e, _ in replay] == ["answer", "done"] and replay[1][1]["replayed"] is True
    final = client.get(f"/api/v1/discovery/search/{sid}").json()
    assert final["status"] == "completed" and final["answer"]["total_organizations"] == 1


def test_sync_fetch_runs_a_pending_search(client):
    as_user(USER)
    sid = client.post("/api/v1/discovery/search", json={"query": "home care in Charlotte NC"}).json()["search_id"]
    data = client.get(f"/api/v1/discovery/search/{sid}").json()
    assert data["status"] == "completed" and data["answer"]["cards"]


def test_query_without_location_asks_for_one(client):
    as_user(USER)
    sid = client.post("/api/v1/discovery/search", json={"query": "plumbers"}).json()["search_id"]
    events = dict(parse_sse(client.get(f"/api/v1/discovery/search/{sid}/stream").text))
    assert "needs_location" in events and events["answer"]["needs_location"] is True
    assert events["answer"]["cards"] == []


def test_export_csv_and_jsonl(client):
    as_user(USER)
    sid = client.post("/api/v1/discovery/search", json={"query": "home care in Charlotte NC"}).json()["search_id"]
    client.get(f"/api/v1/discovery/search/{sid}/stream")
    csv_resp = client.post(f"/api/v1/discovery/search/{sid}/export?format=csv")
    assert csv_resp.status_code == 200 and "Test Care One" in csv_resp.text and csv_resp.text.startswith("org_id,")
    jl = client.post(f"/api/v1/discovery/search/{sid}/export?format=jsonl")
    assert json.loads(jl.text.splitlines()[0])["name"] == "Test Care One"
    assert client.post(f"/api/v1/discovery/search/{sid}/export?format=xml").status_code == 422


def test_unknown_or_malformed_ids_are_404(client):
    as_user(USER)
    assert client.get("/api/v1/discovery/search/not-a-uuid").status_code == 404
    assert client.get(f"/api/v1/discovery/search/{uuid.uuid4()}").status_code == 404
    assert client.get("/api/v1/discovery/organizations/not-a-uuid").status_code == 404
