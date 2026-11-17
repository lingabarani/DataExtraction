"""Migrations 015 and 016: idempotency and schema shape."""

import pathlib

import pytest

from .conftest import MIGRATIONS

MIG_DIR = pathlib.Path(__file__).resolve().parents[3] / "packages" / "infrastructure" / "migrations"


@pytest.mark.parametrize("filename", MIGRATIONS)
def test_migration_files_exist_and_use_if_not_exists(filename):
    sql = (MIG_DIR / filename).read_text(encoding="utf-8")
    creates = sql.upper().count("CREATE TABLE")
    assert creates and creates == sql.upper().count("CREATE TABLE IF NOT EXISTS")
    assert sql.upper().count("CREATE INDEX") == sql.upper().count("CREATE INDEX IF NOT EXISTS")


def test_migrations_apply_twice_without_error(pg):
    pg.autocommit = True
    try:
        with pg.cursor() as cur:
            for _ in range(2):
                for f in MIGRATIONS:
                    cur.execute((MIG_DIR / f).read_text(encoding="utf-8"))
    finally:
        pg.autocommit = False


def _cols(pg, schema, table):
    with pg.cursor() as cur:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
                    (schema, table))
        return {r[0] for r in cur.fetchall()}


@pytest.mark.parametrize("schema,table,expected", [
    ("ops_dataextraction", "api_keys", {"provider", "ciphertext", "last4", "status", "priority", "expires_at",
                                        "cooldown_until", "fail_count", "last_used_at", "daily_token_quota"}),
    ("ops_dataextraction", "llm_usage", {"provider", "model", "key_id", "prompt_tokens", "completion_tokens",
                                         "latency_ms", "status_code", "success"}),
    ("ops_dataextraction", "planner_decisions", {"mode", "dry_run", "llm_provider", "llm_model", "inputs_json",
                                                 "plan_json", "executed_json", "rejected_json"}),
    ("staging_dataextraction", "place_details", {"place_id", "ftid", "name", "categories", "address", "latitude",
                                                 "longitude", "phone", "website", "rating", "hours", "attributes",
                                                 "source", "source_url", "run_id", "scraped_at"}),
    ("staging_dataextraction", "place_services", {"place_id", "service_name", "group_name", "source", "run_id"}),
    ("staging_dataextraction", "place_reviews", {"place_id", "review_id", "reviewer_name", "reviewer_name_hash",
                                                 "rating", "review_text", "published_at", "owner_response_text",
                                                 "sentiment", "topics", "source", "source_url", "run_id",
                                                 "scraped_at"}),
    ("staging_dataextraction", "place_contacts", {"place_id", "contact_type", "value", "extraction_method"}),
    ("staging_dataextraction", "place_people", {"place_id", "full_name", "role_title", "extraction_method"}),
])
def test_tables_have_required_columns(pg, schema, table, expected):
    missing = expected - _cols(pg, schema, table)
    assert not missing, f"{schema}.{table} is missing {missing}"


def test_natural_key_constraints_and_indexes_exist(pg):
    with pg.cursor() as cur:
        cur.execute("""SELECT conname FROM pg_constraint WHERE conname IN
                       ('uq_place_services','uq_place_reviews','uq_place_contacts','uq_place_people')""")
        assert {r[0] for r in cur.fetchall()} == {"uq_place_services", "uq_place_reviews",
                                                  "uq_place_contacts", "uq_place_people"}
        cur.execute("""SELECT indexname FROM pg_indexes WHERE indexname IN
                       ('idx_place_reviews_place','idx_place_reviews_published','idx_api_keys_provider_status',
                        'idx_llm_usage_ts','idx_planner_decisions_ts')""")
        assert len(cur.fetchall()) == 5


def test_api_key_status_check_constraint(pg):
    import psycopg2
    with pg.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO ops_dataextraction.api_keys (provider, ciphertext, status) "
                        "VALUES ('groq', 'x', 'weird')")
    pg.rollback()


def test_duplicate_review_is_rejected_by_unique_constraint(pg):
    import psycopg2
    with pg.cursor() as cur:
        cur.execute("TRUNCATE staging_dataextraction.place_reviews")
        cur.execute("INSERT INTO staging_dataextraction.place_reviews (place_id, review_id) VALUES ('p','r')")
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO staging_dataextraction.place_reviews (place_id, review_id) VALUES ('p','r')")
    pg.rollback()
