"""
Shared fixtures for the Discovery Engine tests.

* No test may write to the real database: persistence is stubbed unless a test uses the `db` fixture, which only
  connects to a database whose name contains "test" (otherwise those tests skip).
* Caches that would leak state between tests are cleared before every test.
* No network: tests inject mock sources / transports.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MIGRATIONS = ["015_secrets_llm_planner.sql", "016_place_deep_data.sql", "017_discovery_schema.sql",
              "018_discovery_answer_store.sql"]


@pytest.fixture(autouse=True)
def _isolate(request, monkeypatch):
    from packages.discovery.cache import default_cache
    from packages.discovery import http as dhttp, robots, suppression

    default_cache.clear()
    robots.clear_cache()
    dhttp._CLIENTS.clear()
    dhttp._BUCKETS.clear()
    suppression._ACTIVE_HASHES.clear()
    suppression._LAST_LOADED = 0.0
    for name in ("LINKEDIN_AUTH_ENABLED", "LLM_PROVIDER", "GROQ_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    # Worldwide geocoder (OpenStreetMap): private cache file, and "not found" unless a test mocks a response
    import httpx
    from packages.discovery import world_geo
    monkeypatch.setenv("DISCOVERY_GEO_CACHE", str(request.getfixturevalue("tmp_path") / "world_cache.json"))
    world_geo._cache = None
    dhttp.set_transport_override(world_geo.RATE_BUCKET, httpx.MockTransport(lambda req: httpx.Response(200, json=[])))

    if "persist" not in request.fixturenames and "db" not in request.fixturenames:
        from packages.discovery import orchestrator as orch
        from packages.discovery.persistence import PersistResult

        monkeypatch.setattr(orch, "persist_discovery_search", lambda *a, **k: PersistResult(ok=False, error="stubbed"))
        monkeypatch.setattr(orch, "save_search_answer", lambda *a, **k: False)
        monkeypatch.setattr(suppression, "load_suppression_hashes", lambda force=False: set())
    yield
    dhttp.set_transport_override(world_geo.RATE_BUCKET, None)
    world_geo._cache = None


@pytest.fixture(scope="session")
def pg():
    try:
        import psycopg2
        from packages.infrastructure.config_manager import config_manager
        cfg = config_manager.get_database_config()
        if "test" not in str(cfg["dbname"]).lower():
            pytest.skip(f"refusing to run DB tests against non-test database '{cfg['dbname']}'")
        conn = psycopg2.connect(host=cfg["host"], port=cfg["port"], dbname=cfg["dbname"], user=cfg["user"],
                                password=cfg["password"], connect_timeout=3)
    except pytest.skip.Exception:
        raise
    except Exception as exc:
        pytest.skip(f"PostgreSQL test database unavailable: {type(exc).__name__}")

    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS kg_audit")
        cur.execute("""CREATE TABLE IF NOT EXISTS kg_audit.suppression_lists (
            suppression_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            hashed_identifier CHAR(64) NOT NULL UNIQUE, identifier_type VARCHAR(50) NOT NULL DEFAULT 'x',
            reason VARCHAR(100) NOT NULL DEFAULT 'test', requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_active BOOLEAN NOT NULL DEFAULT true)""")
        cur.execute("CREATE SCHEMA IF NOT EXISTS staging_dataextraction")
        for f in MIGRATIONS:
            cur.execute((ROOT / "packages" / "infrastructure" / "migrations" / f).read_text(encoding="utf-8"))
    conn.autocommit = False
    yield conn
    conn.close()


@pytest.fixture
def persist():
    """Marker fixture: the test exercises real persistence (needs `db`)."""
    return True


@pytest.fixture
def db(pg, monkeypatch):
    """Clean discovery tables, and point the project's connection helpers at the test database."""
    pg.rollback()
    with pg.cursor() as cur:
        cur.execute("TRUNCATE discovery_dataextraction.search_results, discovery_dataextraction.search_runs, "
                    "discovery_dataextraction.facts, discovery_dataextraction.people, "
                    "discovery_dataextraction.organizations, kg_audit.suppression_lists CASCADE")
    pg.commit()
    return pg
