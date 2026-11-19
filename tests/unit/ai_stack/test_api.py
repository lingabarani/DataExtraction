"""HTTP API for keys, LLM status, planner and place data."""

import json

import pytest
from fastapi.testclient import TestClient

from packages.api.dependencies import UserPrincipal, get_current_user
from packages.api.main import app
from packages.infrastructure.key_vault import set_secrets_manager

from .conftest import FAKE_KEY_A, FAKE_KEY_B
from .test_deep_place import FakeHttp, STUB, extractor, make_review, reviews_response, run
from packages.scrapers.google_maps.deep_place_writer import save_bundle

ADMIN = UserPrincipal(id="1", email="admin@test", name="Admin", is_admin=True)
USER = UserPrincipal(id="2", email="user@test", name="User", is_admin=False)


@pytest.fixture
def client():
    set_secrets_manager(None)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    set_secrets_manager(None)


def as_user(principal):
    app.dependency_overrides[get_current_user] = lambda: principal


ADMIN_ROUTES = [
    ("post", "/api/v1/secrets/keys", {"provider": "groq", "value": FAKE_KEY_A}),
    ("get", "/api/v1/secrets/keys", None),
    ("patch", "/api/v1/secrets/keys/00000000-0000-0000-0000-000000000000", {"status": "disabled"}),
    ("delete", "/api/v1/secrets/keys/00000000-0000-0000-0000-000000000000", None),
    ("post", "/api/v1/secrets/keys/00000000-0000-0000-0000-000000000000/test", None),
    ("get", "/api/v1/llm/status", None),
    ("post", "/api/v1/planner/run", {"dry_run": True}),
    ("post", "/api/v1/places/extract", {"place_ids": ["1"]}),
]


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_admin_routes_reject_non_admins(client, method, path, body):
    as_user(USER)
    resp = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert resp.status_code == 403


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_admin_routes_require_authentication(client, monkeypatch, method, path, body):
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    resp = getattr(client, method)(path, **({"json": body} if body is not None else {}))
    assert resp.status_code == 401


# ── keys ─────────────────────────────────────────────────────────────────────

def test_key_lifecycle_never_exposes_the_value(db, client):
    as_user(ADMIN)
    created = client.post("/api/v1/secrets/keys", json={"provider": "groq", "value": FAKE_KEY_A,
                                                        "label": "monday", "priority": 5})
    assert created.status_code == 201
    key_id = created.json()["id"]
    assert created.json()["masked"] == "****aaaa" and FAKE_KEY_A not in created.text

    listing = client.get("/api/v1/secrets/keys")
    assert listing.status_code == 200 and FAKE_KEY_A not in listing.text
    row = listing.json()["keys"][0]
    assert row["masked"] == "****aaaa" and row["status"] == "active" and "ciphertext" not in row
    with db.cursor() as cur:
        cur.execute("SELECT ciphertext FROM ops_dataextraction.api_keys WHERE id = %s::uuid", (key_id,))
        assert FAKE_KEY_A not in cur.fetchone()[0]

    patched = client.patch(f"/api/v1/secrets/keys/{key_id}", json={"status": "disabled"})
    assert patched.status_code == 200
    assert client.get("/api/v1/secrets/keys").json()["keys"][0]["status"] == "disabled"
    assert client.delete(f"/api/v1/secrets/keys/{key_id}").status_code == 200
    assert client.get("/api/v1/secrets/keys").json()["keys"] == []


def test_new_key_added_through_api_is_used_by_llm_layer_immediately(db, client):
    as_user(ADMIN)
    from packages.infrastructure.key_vault import get_secrets_manager
    assert get_secrets_manager().get_active_key("groq") is None
    client.post("/api/v1/secrets/keys", json={"provider": "groq", "value": FAKE_KEY_A})
    assert get_secrets_manager().get_active_key("groq").value == FAKE_KEY_A
    client.post("/api/v1/secrets/keys", json={"provider": "groq", "value": FAKE_KEY_B, "priority": 1})
    assert get_secrets_manager().get_active_key("groq").value == FAKE_KEY_B  # daily rotation: newest wins


@pytest.mark.parametrize("body", [
    {"provider": "openai", "value": FAKE_KEY_A},
    {"provider": "groq", "value": "short"},
    {"provider": "groq"},
    {"provider": "groq", "value": FAKE_KEY_A, "priority": 0},
])
def test_invalid_key_payloads_are_rejected(db, client, body):
    as_user(ADMIN)
    resp = client.post("/api/v1/secrets/keys", json=body)
    assert resp.status_code == 422


def test_validation_errors_do_not_echo_the_key(db, client):
    as_user(ADMIN)
    resp = client.post("/api/v1/secrets/keys", json={"provider": "nope", "value": FAKE_KEY_A})
    assert resp.status_code == 422 and FAKE_KEY_A not in resp.text


def test_missing_master_key_gives_clear_503(db, client, monkeypatch):
    as_user(ADMIN)
    monkeypatch.delenv("SECRETS_MASTER_KEY")
    resp = client.post("/api/v1/secrets/keys", json={"provider": "groq", "value": FAKE_KEY_A})
    assert resp.status_code == 503 and "SECRETS_MASTER_KEY" in resp.json()["detail"]


def test_unknown_key_returns_404(db, client):
    as_user(ADMIN)
    zero = "00000000-0000-0000-0000-000000000000"
    assert client.patch(f"/api/v1/secrets/keys/{zero}", json={"status": "disabled"}).status_code == 404
    assert client.delete(f"/api/v1/secrets/keys/{zero}").status_code == 404
    assert client.post(f"/api/v1/secrets/keys/{zero}/test").status_code == 404


def test_key_test_endpoint_marks_rejected_keys_invalid(db, client, monkeypatch):
    as_user(ADMIN)
    key_id = client.post("/api/v1/secrets/keys", json={"provider": "groq", "value": FAKE_KEY_A}).json()["id"]
    monkeypatch.setattr("packages.infrastructure.llm.groq_provider.probe_groq_key",
                        lambda value, **kw: {"ok": False, "status_code": 401, "model": "m"})
    resp = client.post(f"/api/v1/secrets/keys/{key_id}/test")
    assert resp.json()["ok"] is False and FAKE_KEY_A not in resp.text
    assert client.get("/api/v1/secrets/keys").json()["keys"][0]["status"] == "invalid"
    monkeypatch.setattr("packages.infrastructure.llm.groq_provider.probe_groq_key",
                        lambda value, **kw: {"ok": True, "status_code": 200, "model": "m"})
    client.patch(f"/api/v1/secrets/keys/{key_id}", json={"status": "active"})
    assert client.post(f"/api/v1/secrets/keys/{key_id}/test").json()["ok"] is True


# ── llm + planner ────────────────────────────────────────────────────────────

def test_llm_status_reports_masked_key_and_budget(db, client, monkeypatch):
    as_user(ADMIN)
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY_B)
    data = client.get("/api/v1/llm/status").json()
    assert data["provider"] == "groq" and data["groq_key_available"] is True
    assert data["groq_key_masked"] == "****bbbb" and FAKE_KEY_B not in json.dumps(data)
    assert data["models"]["groq"] == "openai/gpt-oss-120b" and "budget" in data


def test_planner_run_dry_run_records_a_decision_and_lists_it(db, client):
    as_user(ADMIN)
    run_res = client.post("/api/v1/planner/run", json={"dry_run": True})
    assert run_res.status_code == 200
    body = run_res.json()
    assert body["dry_run"] is True and body["mode"] == "fallback"  # no key configured -> rules
    assert all(e["started"] is False for e in body["executed"])
    decisions = client.get("/api/v1/planner/decisions").json()["decisions"]
    assert decisions[0]["id"] == body["decision_id"] and decisions[0]["dry_run"] is True


def test_planner_config_lists_allowed_workflows(db, client):
    as_user(USER)
    cfg = client.get("/api/v1/planner/config").json()
    assert "PlaceDeepExtractionWorkflow" in cfg["allowed_workflows"]
    assert cfg["config"]["max_actions_per_cycle"] >= 1


# ── places ───────────────────────────────────────────────────────────────────

def _store_place(db, n_reviews=5, mode="hash"):
    http = FakeHttp(pages=[reviews_response([make_review(i, name=f"Person {i}") for i in range(n_reviews)])])
    bundle = run(extractor(http, mode=mode).extract_place(STUB))
    save_bundle(db, bundle, STUB, "run-api")
    db.commit()


def test_place_detail_and_reviews_endpoints(db, client):
    _store_place(db)
    as_user(USER)
    detail = client.get("/api/v1/places/123456789").json()
    assert detail["place"]["name"] == "Acme Dental" and detail["place"]["source"] == "GOOGLE_MAPS"
    assert {s["service_name"] for s in detail["services"]} == {"Dine-in", "Takeout"}
    assert any(c["contact_type"] == "email" for c in detail["contacts"])
    assert detail["reviews_summary"]["stored"] == 5 and detail["reviews_summary"]["average_rating"] == 5.0

    page1 = client.get("/api/v1/places/123456789/reviews?limit=2&offset=0").json()
    page2 = client.get("/api/v1/places/123456789/reviews?limit=2&offset=2").json()
    assert page1["total"] == 5 and len(page1["reviews"]) == 2 and len(page2["reviews"]) == 2
    assert {r["review_id"] for r in page1["reviews"]}.isdisjoint({r["review_id"] for r in page2["reviews"]})
    assert all(r["reviewer_name"] is None and len(r["reviewer_hash_prefix"]) == 8 for r in page1["reviews"])
    assert "Person" not in json.dumps(page1)


def test_plain_mode_names_are_visible_through_api(db, client):
    _store_place(db, n_reviews=1, mode="plain")
    as_user(USER)
    assert client.get("/api/v1/places/123456789/reviews").json()["reviews"][0]["reviewer_name"] == "Person 0"


def test_unknown_place_is_404_and_list_search_works(db, client):
    _store_place(db, n_reviews=1)
    as_user(USER)
    assert client.get("/api/v1/places/nope").status_code == 404
    assert client.get("/api/v1/places?q=acme").json()["places"][0]["place_id"] == "123456789"
    assert client.get("/api/v1/places?q=zzz").json()["places"] == []


def test_review_pagination_limits_are_validated(db, client):
    as_user(USER)
    assert client.get("/api/v1/places/x/reviews?limit=1000").status_code == 422
    assert client.get("/api/v1/places/x/reviews?offset=-1").status_code == 422


def test_extract_endpoint_validates_and_starts_the_workflow(db, client, monkeypatch):
    as_user(ADMIN)
    assert client.post("/api/v1/places/extract", json={}).status_code == 422
    assert client.post("/api/v1/places/extract", json={"region": "US-CA; DROP"}).status_code == 422
    assert client.post("/api/v1/places/extract", json={"place_ids": ["1"], "max_places": 9999}).status_code == 422

    started = {}

    class FakeClient:
        async def start_workflow(self, name, config, id, task_queue):
            started.update(name=name, config=config, id=id, queue=task_queue)

    async def fake_get_client():
        return FakeClient()
    monkeypatch.setattr("packages.temporal.client.get_temporal_client", fake_get_client)
    resp = client.post("/api/v1/places/extract", json={"region": "US-CA", "category": "dentist", "max_places": 10})
    assert resp.status_code == 202
    assert started["name"] == "PlaceDeepExtractionWorkflow" and started["config"]["region"] == "US-CA"
    assert started["id"].startswith("place-deep-") and started["queue"] == "geospatial-domain-queue"


def test_extract_endpoint_reports_temporal_outage_cleanly(db, client, monkeypatch):
    as_user(ADMIN)

    async def down():
        raise ConnectionError("Temporal server at localhost:7233 is not reachable")
    monkeypatch.setattr("packages.temporal.client.get_temporal_client", down)
    resp = client.post("/api/v1/places/extract", json={"place_ids": ["1"]})
    assert resp.status_code == 503 and "ConnectionError" in resp.json()["detail"]
