"""
Phase 4 Test Suite: Database Integrity, Deduplication, PostGIS, Security & Migrations

Comprehensive verification of:
1. SQL Identifier Validation: _assert_safe_identifier blocks injection in dynamic column names.
2. Deduplication Query Whitelisting: _find_company and _find_person enforce field whitelists.
3. Trigram Fuzzy Matching: find_company_by_trigram and pg_trgm / SequenceMatcher fallback.
4. PostGIS & Spatial Geometry: sync_company_geometry coordinate validation and PostGIS/Haversine search.
5. Dynamic Upsert & Update Safety: Column names validated before SQL construction.
6. Non-Destructive Migrations & Setup: Idempotent schema, opt-in --drop-existing flag protection.
7. Connection Pool Lifecycle & Resilience: Safe release, error discarding, and clean shutdown.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Ensure imports work in DataExtraction monorepo
_backend_dir = Path(__file__).resolve().parent
_project_root = _backend_dir.parents[2]
_packages = _project_root / "packages"

for _p in [
    _packages / "pipeline",
    _packages / "infrastructure",
    _packages / "scrapers",
    _packages / "scrapers" / "federal",
    _packages / "scrapers" / "open_map",
    _packages / "api",
    _packages / "api" / "routers",
    _project_root / "scripts" / "db",
    _project_root / "scripts" / "ops",
    _project_root,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import db_connector
from db_connector import (
    _assert_safe_identifier,
    sync_company_geometry,
    find_nearby_companies,
    upsert_company,
    upsert_person,
    update_company_fields,
    update_person_fields,
    release_connection,
    close_pool,
)
from deduplicator import (
    Deduplicator,
    ALLOWED_COMPANY_QUERY_FIELDS,
    ALLOWED_PERSON_QUERY_FIELDS,
)
import migrate_schema
import setup_postgres


class TestIdentifierSafety(unittest.TestCase):
    """Verifies strict SQL identifier whitelisting to prevent column name injection."""

    def test_valid_identifiers_allowed(self):
        valid_identifiers = [
            "name",
            "company_id",
            "state_code",
            "data_quality_score",
            "source_records",
            "col_123",
            "_internal_id",
        ]
        for ident in valid_identifiers:
            self.assertEqual(_assert_safe_identifier(ident), ident)

    def test_insecure_identifiers_rejected(self):
        malicious_identifiers = [
            "name; DROP TABLE companies;--",
            "col name",
            "col-name",
            "123_starts_with_digit",
            "name' OR '1'='1",
            'name" --',
            "name/*comment*/",
            "",
            None,
            123,
        ]
        for ident in malicious_identifiers:
            with self.assertRaises(ValueError, msg=f"Should reject {ident!r}"):
                _assert_safe_identifier(ident)


class TestQueryWhitelisting(unittest.TestCase):
    """Verifies that Deduplicator queries enforce strict column whitelists."""

    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cur
        self.dedup = Deduplicator(self.mock_conn)

    def test_allowed_company_query_fields(self):
        # All required lookup fields must be in whitelist
        for field in ("ein", "rfc", "cik", "npi", "domain", "id"):
            self.assertIn(field, ALLOWED_COMPANY_QUERY_FIELDS)

        # Whitelisted field should construct parameterized query
        self.mock_cur.fetchone.return_value = {"id": "c1", "name": "Acme Corp"}
        res = self.dedup._find_company("ein", "12-3456789")
        self.assertIsNotNone(res)
        self.assertEqual(res["id"], "c1")
        self.mock_cur.execute.assert_called_with(
            'SELECT * FROM companies WHERE "ein"=%s AND "ein" IS NOT NULL LIMIT 1',
            ("12-3456789",)
        )

    def test_disallowed_company_query_field_rejected(self):
        for bad_field in ("salary", "password", "id; DROP TABLE companies;--", "raw_payload"):
            with self.assertRaises(ValueError):
                self.dedup._find_company(bad_field, "test_val")

    def test_allowed_person_query_fields(self):
        for field in ("linkedin_url", "email", "id"):
            self.assertIn(field, ALLOWED_PERSON_QUERY_FIELDS)

        self.mock_cur.fetchone.return_value = {"id": "p1", "full_name": "Jane Doe"}
        res = self.dedup._find_person("email", "jane@example.com")
        self.assertIsNotNone(res)
        self.mock_cur.execute.assert_called_with(
            'SELECT * FROM people WHERE "email"=%s AND "email" IS NOT NULL LIMIT 1',
            ("jane@example.com",)
        )

    def test_disallowed_person_query_field_rejected(self):
        for bad_field in ("ssn", "secret_token", "is_admin;--"):
            with self.assertRaises(ValueError):
                self.dedup._find_person(bad_field, "val")


class TestTrigramFuzzyMatching(unittest.TestCase):
    """Verifies pg_trgm trigram search and SequenceMatcher fallback in Deduplicator."""

    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cur
        self.dedup = Deduplicator(self.mock_conn)

    def test_find_company_by_trigram_delegation(self):
        self.mock_cur.fetchone.return_value = {
            "id": "c100",
            "name": "Acme Global Solutions LLC",
            "normalized_name": "ACME GLOBAL SOLUTIONS",
            "_similarity": 0.92,
        }
        res = self.dedup.find_company_by_trigram("Acme Global Solutions, Inc.", state_code="DE", threshold=0.85)
        self.assertIsNotNone(res)
        self.assertEqual(res["id"], "c100")
        self.assertEqual(res["_similarity"], 0.92)

    def test_find_company_by_trigram_empty_or_invalid(self):
        self.assertIsNone(self.dedup.find_company_by_trigram(""))
        self.assertIsNone(self.dedup.find_company_by_trigram(None))
        self.assertIsNone(self.dedup.find_company_by_trigram("   "))

    def test_fuzzy_matcher_fallback_on_trgm_exception(self):
        # Simulate pg_trgm not installed (throws Exception on similarity query)
        # Then falls back to SequenceMatcher across candidates
        def side_effect(sql, params=None):
            if "similarity(" in sql:
                raise Exception("function similarity(text, text) does not exist")
            return None

        self.mock_cur.execute.side_effect = side_effect
        self.mock_cur.fetchall.return_value = [
            {"id": "c1", "name": "Acme Widgets Inc", "normalized_name": "ACME WIDGETS", "state_code": "TX"},
            {"id": "c2", "name": "Other Company", "normalized_name": "OTHER COMPANY", "state_code": "TX"},
        ]

        with patch.object(self.dedup, "_fetch_company") as mock_fetch:
            mock_fetch.return_value = {"id": "c1", "name": "Acme Widgets Inc", "normalized_name": "ACME WIDGETS"}
            res = self.dedup._find_company_fuzzy("ACME WIDGETS", state_code="TX", threshold=0.88)
            self.assertIsNotNone(res)
            self.assertEqual(res["id"], "c1")
            self.assertGreaterEqual(res["_similarity"], 0.88)


class TestSpatialIntegration(unittest.TestCase):
    """Verifies PostGIS geometry synchronization and spatial radius querying."""

    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cur

    def test_sync_company_geometry_coordinate_bounds(self):
        # Invalid / out-of-bounds coordinates must be rejected
        self.assertFalse(sync_company_geometry(self.mock_conn, "c1", 95.0, -100.0))  # Lat > 90
        self.assertFalse(sync_company_geometry(self.mock_conn, "c1", -95.0, -100.0)) # Lat < -90
        self.assertFalse(sync_company_geometry(self.mock_conn, "c1", 35.0, 190.0))   # Lon > 180
        self.assertFalse(sync_company_geometry(self.mock_conn, "c1", 35.0, -190.0))  # Lon < -180
        self.assertFalse(sync_company_geometry(self.mock_conn, "c1", "invalid", -100.0))
        self.assertFalse(sync_company_geometry(self.mock_conn, "", 35.0, -100.0))
        self.assertFalse(sync_company_geometry(self.mock_conn, None, 35.0, -100.0))

    def test_sync_company_geometry_success(self):
        with patch("db_connector.DATABASE_TYPE", "postgresql"):
            ok = sync_company_geometry(self.mock_conn, "c1", 37.7749, -122.4194)
            self.assertTrue(ok)
            # Must set latitude, longitude, and PostGIS geom
            exec_sql = self.mock_cur.execute.call_args[0][0]
            self.assertIn("ST_SetSRID(ST_MakePoint(%s, %s), 4326)", exec_sql)
            params = self.mock_cur.execute.call_args[0][1]
            self.assertEqual(params, (37.7749, -122.4194, -122.4194, 37.7749, "c1"))

    def test_find_nearby_companies_invalid_input(self):
        self.assertEqual(find_nearby_companies(self.mock_conn, "bad", -122.0), [])
        self.assertEqual(find_nearby_companies(self.mock_conn, 37.0, "bad"), [])

    def test_find_nearby_companies_postgis_success(self):
        with patch("db_connector.DATABASE_TYPE", "postgresql"), \
             patch("db_connector.get_cursor", return_value=self.mock_cur):
            self.mock_cur.fetchall.return_value = [
                {"id": "c1", "name": "Near Corp", "distance_km": 1.25},
                {"id": "c2", "name": "Mid Corp", "distance_km": 4.80},
            ]
            results = find_nearby_companies(self.mock_conn, 37.7749, -122.4194, radius_km=5.0, limit=10)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0]["id"], "c1")
            self.assertEqual(results[0]["distance_km"], 1.25)
            # Verify PostGIS ST_DWithin query structure
            exec_sql = self.mock_cur.execute.call_args[0][0]
            self.assertIn("ST_DWithin", exec_sql)
            self.assertIn("ST_Distance", exec_sql)

    def test_find_nearby_companies_haversine_fallback(self):
        # Simulate PostGIS extension missing (raises error on ST_DWithin)
        with patch("db_connector.DATABASE_TYPE", "postgresql"), \
             patch("db_connector.get_cursor", return_value=self.mock_cur):
            calls = []
            def side_effect(sql, params=None):
                calls.append(sql)
                if "ST_DWithin" in sql:
                    raise Exception("function st_dwithin does not exist")
                return None

            self.mock_cur.execute.side_effect = side_effect
            self.mock_cur.fetchall.return_value = [
                {"id": "c1", "name": "Fallback Corp", "distance_km": 2.10}
            ]
            results = find_nearby_companies(self.mock_conn, 37.7749, -122.4194, radius_km=10.0, limit=20)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["name"], "Fallback Corp")
            # Verify fallback query was executed using Haversine formula
            self.assertTrue(any("LEAST(1.0, GREATEST(-1.0" in s for s in calls))


class TestDynamicSqlConstruction(unittest.TestCase):
    """Verifies that dynamic upsert and update statements sanitize column keys."""

    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cur

    def test_upsert_company_sanitizes_record_keys(self):
        # Malicious key in dictionary must be rejected before executing SQL
        malicious_record = {
            "name": "Acme Corp",
            "state_code; DROP TABLE companies;--": "TX"
        }
        with self.assertRaises(ValueError):
            upsert_company(self.mock_conn, malicious_record)

    def test_upsert_person_sanitizes_record_keys(self):
        malicious_record = {
            "full_name": "John Doe",
            "email' OR '1'='1": "john@example.com"
        }
        with self.assertRaises(ValueError):
            upsert_person(self.mock_conn, malicious_record)

    def test_update_company_fields_sanitizes_update_keys(self):
        with self.assertRaises(ValueError):
            update_company_fields(self.mock_conn, "c1", {"bad col": "val"})

    def test_update_person_fields_sanitizes_update_keys(self):
        with self.assertRaises(ValueError):
            update_person_fields(self.mock_conn, "p1", {"bad-col": "val"})


class TestMigrationsAndSetup(unittest.TestCase):
    """Verifies Phase 4 schema migrations and setup idempotency."""

    def test_m09_postgis_pg_trgm_migration_idempotent(self):
        mock_cur = MagicMock()
        migrate_schema.m09_postgis_pg_trgm_extensions(mock_cur)
        executed_sqls = [c[0][0] for c in mock_cur.execute.call_args_list]

        # Must execute CREATE EXTENSION IF NOT EXISTS for pg_trgm and postgis
        self.assertTrue(any("CREATE EXTENSION IF NOT EXISTS pg_trgm" in s for s in executed_sqls))
        self.assertTrue(any("CREATE EXTENSION IF NOT EXISTS postgis" in s for s in executed_sqls))
        # Must execute GIN trigram indexes
        self.assertTrue(any("idx_companies_name_trgm" in s for s in executed_sqls))
        self.assertTrue(any("idx_people_name_trgm" in s for s in executed_sqls))

    def test_m10_data_integrity_constraints_idempotent(self):
        mock_cur = MagicMock()
        migrate_schema.m10_data_integrity_constraints(mock_cur)
        executed_sqls = [c[0][0] for c in mock_cur.execute.call_args_list]

        self.assertTrue(any("idx_companies_quality_score" in s for s in executed_sqls))
        self.assertTrue(any("idx_people_quality_score" in s for s in executed_sqls))
        self.assertTrue(any("idx_companies_norm_name_state" in s for s in executed_sqls))

    def test_setup_postgres_non_destructive_by_default(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch("setup_postgres.psycopg2.connect", return_value=mock_conn):
            # Without drop_existing, DROP_TABLES_SQL must NOT be executed
            ok = setup_postgres.create_schema("localhost", 5432, "pwd", drop_existing=False)
            self.assertTrue(ok)
            executed = " ".join([c[0][0] for c in mock_cur.execute.call_args_list])
            self.assertNotIn("DROP TABLE IF EXISTS", executed)
            self.assertIn("CREATE TABLE IF NOT EXISTS companies", executed)

    def test_setup_postgres_drop_existing_opt_in(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch("setup_postgres.psycopg2.connect", return_value=mock_conn):
            # With drop_existing=True, DROP_TABLES_SQL IS executed
            ok = setup_postgres.create_schema("localhost", 5432, "pwd", drop_existing=True)
            self.assertTrue(ok)
            executed = " ".join([c[0][0] for c in mock_cur.execute.call_args_list])
            self.assertIn("DROP TABLE IF EXISTS", executed)


class TestConnectionPoolLifecycle(unittest.TestCase):
    """Verifies PostgreSQL connection pool safety, error discarding, and shutdown."""

    def test_release_connection_healthy(self):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = 0
        with patch.object(db_connector, "_PG_POOL", mock_pool):
            release_connection(mock_conn)
            mock_pool.putconn.assert_called_once_with(mock_conn, close=False)

    def test_release_connection_closed_or_broken(self):
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = 1  # Broken / closed connection
        with patch.object(db_connector, "_PG_POOL", mock_pool):
            release_connection(mock_conn)
            # Must discard broken connection with close=True
            mock_pool.putconn.assert_called_once_with(mock_conn, close=True)

    def test_release_connection_tolerates_pool_exceptions(self):
        mock_pool = MagicMock()
        mock_pool.putconn.side_effect = Exception("Pool full")
        mock_conn = MagicMock()
        mock_conn.closed = 0
        with patch.object(db_connector, "_PG_POOL", mock_pool):
            # Should not raise exception
            release_connection(mock_conn)
            mock_conn.close.assert_called_once()

    def test_close_pool_shutdown(self):
        mock_pool = MagicMock()
        with patch.object(db_connector, "_PG_POOL", mock_pool):
            close_pool()
            mock_pool.closeall.assert_called_once()
            self.assertIsNone(db_connector._PG_POOL)


class TestDatabaseBackupAndRestore(unittest.TestCase):
    """Verifies enterprise database backup and restoration automation."""

    def setUp(self):
        scripts_db = _project_root / "scripts" / "db"
        if str(scripts_db) not in sys.path:
            sys.path.insert(0, str(scripts_db))
        import backup_postgres
        import restore_postgres
        self.backup_mod = backup_postgres
        self.restore_mod = restore_postgres

    def test_backup_dry_run(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            backup_dir = Path(tmpdir)
            target = self.backup_mod.run_backup(backup_dir=backup_dir, dry_run=True)
            self.assertIsNotNone(target)
            self.assertTrue(target.name.endswith(".sql.gz"))

    def test_restore_dry_run(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w+", suffix=".sql.gz", delete=False) as f:
            f.write("mock dump content")
            dump_path = Path(f.name)

        try:
            success = self.restore_mod.run_restore(dump_path=dump_path, dry_run=True)
            self.assertTrue(success)
        finally:
            if dump_path.exists():
                dump_path.unlink()

    def test_restore_checksum_verification(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w+", suffix=".sql.gz", delete=False) as f:
            f.write("valid data content")
            dump_path = Path(f.name)

        try:
            expected_sha = self.restore_mod.compute_sha256(dump_path)
            # Valid match
            self.assertTrue(self.restore_mod.verify_backup_integrity(dump_path, expected_sha))
            # Mismatched / tampered sum
            self.assertFalse(self.restore_mod.verify_backup_integrity(dump_path, "0000000000000000000000000000000000000000000000000000000000000000"))
        finally:
            if dump_path.exists():
                dump_path.unlink()


if __name__ == "__main__":
    unittest.main()

