"""
Shared fixtures for the autonomous-AI test suite.

DB-backed tests only run against a database whose name contains "test" and they
skip cleanly when PostgreSQL is unreachable. Set POSTGRES_HOST/USER/PASSWORD/DB
(e.g. POSTGRES_DB=dex_ai_test) to enable them.
"""

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("REVIEWER_HASH_SALT", "unit-test-salt")

FAKE_KEY_A = "gsk_test_fake_key_0000_aaaaaaaa"
FAKE_KEY_B = "gsk_test_fake_key_1111_bbbbbbbb"
FAKE_KEY_C = "gsk_test_fake_key_2222_cccccccc"

MIGRATIONS = ["015_secrets_llm_planner.sql", "016_place_deep_data.sql"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No real credentials or provider settings leak into tests."""
    for name in ("GROQ_API_KEY", "GROQ_API_KEYS", "USE_AWS_SECRETS", "LLM_PROVIDER",
                 "LLM_FALLBACK_CHAIN", "LLM_DAILY_TOKEN_BUDGET", "PLANNER_DRY_RUN"):
        monkeypatch.delenv(name, raising=False)
    # Fernet key: 32 url-safe base64 bytes
    from cryptography.fernet import Fernet
    monkeypatch.setenv("SECRETS_MASTER_KEY", Fernet.generate_key().decode())
    yield


@pytest.fixture(scope="session")
def pg():
    """Session-scoped connection factory to a *test* database with the new tables."""
    try:
        import psycopg2
        from packages.infrastructure.config_manager import config_manager
        cfg = config_manager.get_database_config()
        if "test" not in str(cfg["dbname"]).lower():
            pytest.skip(f"refusing to run DB tests against non-test database '{cfg['dbname']}'")
        conn = psycopg2.connect(host=cfg["host"], port=cfg["port"], dbname=cfg["dbname"],
                                user=cfg["user"], password=cfg["password"], connect_timeout=3)
    except pytest.skip.Exception:
        raise
    except Exception as exc:  # unreachable DB, bad credentials...
        pytest.skip(f"PostgreSQL test database unavailable: {type(exc).__name__}")

    conn.autocommit = True
    with conn.cursor() as cur:
        # Minimal copies of tables owned by other migrations (only created in a *test* database).
        cur.execute("CREATE SCHEMA IF NOT EXISTS staging_dataextraction")
        cur.execute("CREATE SCHEMA IF NOT EXISTS kg_audit")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staging_dataextraction.staging_companies (
                id TEXT PRIMARY KEY, name TEXT, website TEXT, phone TEXT, city TEXT, state TEXT,
                state_code TEXT, zip_code TEXT, industry TEXT, source TEXT,
                raw_payload JSONB DEFAULT '{}'::jsonb, updated_at TIMESTAMPTZ DEFAULT NOW())""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS kg_audit.suppression_lists (
                suppression_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                hashed_identifier CHAR(64) NOT NULL UNIQUE,
                identifier_type TEXT, reason TEXT, is_active BOOLEAN DEFAULT TRUE,
                requested_at TIMESTAMPTZ DEFAULT NOW())""")
        for f in MIGRATIONS:
            cur.execute((ROOT / "packages" / "infrastructure" / "migrations" / f).read_text(encoding="utf-8"))
    conn.autocommit = False
    yield conn
    conn.close()


@pytest.fixture
def db(pg):
    """Per-test clean tables. Yields the shared connection (autocommit off)."""
    pg.rollback()
    with pg.cursor() as cur:
        cur.execute("""TRUNCATE ops_dataextraction.api_keys, ops_dataextraction.llm_usage,
                       ops_dataextraction.planner_decisions,
                       staging_dataextraction.place_details, staging_dataextraction.place_services,
                       staging_dataextraction.place_reviews, staging_dataextraction.place_contacts,
                       staging_dataextraction.place_people, staging_dataextraction.place_extraction_runs,
                       staging_dataextraction.staging_companies, kg_audit.suppression_lists
                       RESTART IDENTITY""")
    pg.commit()
    return pg


@pytest.fixture
def cursor_ctx(pg):
    """A get_db_cursor-compatible context manager bound to the test connection."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        cur = pg.cursor()
        try:
            yield pg, cur
            pg.commit()
        except Exception:
            pg.rollback()
            raise
        finally:
            cur.close()
    return _ctx
