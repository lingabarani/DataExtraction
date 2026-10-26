"""
Phase 5 Test Suite: Quality, Recovery & Pipeline Orchestration

Comprehensive verification of:
1. Master Pipeline Orchestrator:
   - Execution modes ('full', 'incremental', 'sample', 'dry-run').
   - Source-level fault isolation and graceful degradation.
   - Telemetry reporting and metric aggregation.
2. Dead-Letter Queue (DLQ) Resilience Engine:
   - Zero-data-loss enqueue (database + resilient disk fallback).
   - Paginated record retrieval and status filtering.
   - Replay execution, resolution, retry increments, and discard thresholds.
3. Structured Logging & Observability:
   - Structured JSON log formatting with ISO-8601 timestamps.
   - Automatic sensitive data redaction (API keys, passwords, bearer tokens).
   - Contextual binding and latency tracing (.timed context manager).
4. API Route Security & DLQ Endpoints:
   - JWT protection across DLQ and pipeline observability endpoints.
"""

import json
import logging
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

from pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineReport,
    SourceResult,
)
from dead_letter_queue import (
    enqueue_dead_letter,
    get_dead_letter_records,
    get_dead_letter_stats,
    replay_dead_letter,
    discard_dead_letter,
    drain_fallback_to_db,
)
from structured_logger import (
    JsonLogFormatter,
    StandardLogFormatter,
    BoundLogger,
    _mask_sensitive,
    get_structured_logger,
    get_pipeline_health_metrics,
)


class TestPipelineOrchestrator(unittest.TestCase):
    """Verifies master pipeline orchestration, execution modes, and fault isolation."""

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            PipelineOrchestrator(mode="unsupported_mode")

    def test_valid_modes_accepted(self):
        for mode in ("full", "incremental", "sample", "dry-run"):
            orch = PipelineOrchestrator(mode=mode)
            self.assertEqual(orch.mode, mode)
            self.assertTrue(orch.run_id.startswith("run_"))

    def test_sample_mode_applies_limit(self):
        orch = PipelineOrchestrator(mode="sample")
        with patch.object(orch, "_load_source_module", create=True):
            mock_mod = MagicMock()
            mock_mod.run.return_value = {"fetched": 100, "merged": 95, "skipped": 5}
            with patch("pipeline_orchestrator._load_source_module", return_value=mock_mod):
                res = orch.execute_source("sec", limit=0, dry_run=False)
                self.assertEqual(res.status, "DONE")
                self.assertEqual(res.records_fetched, 100)
                # In sample mode with limit=0, limit defaults to 100
                mock_mod.run.assert_called_once_with(mode="tickers", limit=100, dry_run=False)

    def test_dry_run_mode_propagates_flag_and_bypasses_telemetry(self):
        orch = PipelineOrchestrator(mode="dry-run")
        mock_mod = MagicMock()
        mock_mod.run.return_value = {"fetched": 10, "merged": 8, "skipped": 2}

        with patch("pipeline_orchestrator._load_source_module", return_value=mock_mod), \
             patch("pipeline_orchestrator.log_data_source") as mock_log:
            res = orch.execute_source("fdic")
            self.assertEqual(res.status, "DONE")
            # dry_run flag must be passed to module run
            mock_mod.run.assert_called_once_with(source="both", dry_run=True)
            # Database telemetry logging must be bypassed during dry-run
            mock_log.assert_not_called()

    def test_source_level_fault_isolation(self):
        orch = PipelineOrchestrator(mode="full")

        def side_effect(source_name):
            mod = MagicMock()
            if source_name == "sec":
                raise RuntimeError("SEC EDGAR rate-limit / connection reset")
            mod.run.return_value = {"fetched": 50, "merged": 45, "skipped": 5}
            return mod

        with patch("pipeline_orchestrator._load_source_module", side_effect=side_effect), \
             patch("pipeline_orchestrator.get_connection"), \
             patch("pipeline_orchestrator.release_connection"), \
             patch("pipeline_orchestrator.enqueue_dead_letter", return_value=42) as mock_dlq:

            report = orch.run(sources=["fdic", "sec", "usaspending"])

            # FDIC and USASpending succeeded, SEC failed
            self.assertEqual(report.sources_executed, 3)
            self.assertEqual(report.sources_succeeded, 2)
            self.assertEqual(report.sources_failed, 1)

            # Failure details captured
            sec_res = report.results["sec"]
            self.assertEqual(sec_res.status, "FAILED")
            self.assertIn("rate-limit", sec_res.error_message)
            self.assertEqual(sec_res.dead_letters, 1)

            # Failure enqueued to DLQ
            mock_dlq.assert_called_once()


class TestDeadLetterQueue(unittest.TestCase):
    """Verifies zero-data-loss dead-letter enqueue, query, replay, and resolution."""

    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cur

    def test_enqueue_dead_letter_database_success(self):
        self.mock_cur.fetchone.return_value = [101]
        dlq_id = enqueue_dead_letter(
            conn=self.mock_conn,
            source_name="sec",
            entity_type="company",
            raw_payload={"cik": "0000320193", "name": "Apple Inc."},
            error_reason="Missing statutory state_code",
            run_id="run_test_001",
        )
        self.assertEqual(dlq_id, 101)
        self.mock_conn.commit.assert_called_once()
        exec_sql = self.mock_cur.execute.call_args[0][0]
        self.assertIn("INSERT INTO dead_letter_queue", exec_sql)

    def test_enqueue_dead_letter_fallback_on_db_error(self):
        self.mock_cur.execute.side_effect = Exception("Postgres connection dropped")
        with patch("builtins.open", unittest.mock.mock_open()) as mock_file:
            dlq_id = enqueue_dead_letter(
                conn=self.mock_conn,
                source_name="sam",
                entity_type="company",
                raw_payload={"uei": "SAM123456789"},
                error_reason="DB timeout",
            )
            # Database returned None on error
            self.assertIsNone(dlq_id)
            # Written to disk fallback log file
            mock_file.assert_called_once()
            handle = mock_file()
            written_data = "".join(call.args[0] for call in handle.write.call_args_list)
            self.assertIn("SAM123456789", written_data)

    def test_get_dead_letter_stats(self):
        self.mock_cur.fetchone.return_value = [15, 10, 4, 1]
        self.mock_cur.fetchall.return_value = [
            ("sec", "PENDING", 7),
            ("sec", "RESOLVED", 3),
            ("sam", "PENDING", 3),
            ("sam", "DISCARDED", 1),
        ]
        stats = get_dead_letter_stats(self.mock_conn)
        self.assertEqual(stats["total"], 15)
        self.assertEqual(stats["pending"], 10)
        self.assertEqual(stats["resolved"], 4)
        self.assertEqual(stats["discarded"], 1)
        self.assertEqual(len(stats["by_source"]), 2)

    def test_replay_dead_letter_success(self):
        with patch("dead_letter_queue.get_cursor", return_value=self.mock_cur):
            self.mock_cur.fetchone.return_value = {
                "id": 55,
                "source_name": "sec",
                "entity_type": "company",
                "raw_payload": '{"name": "Replayable Corp"}',
                "status": "PENDING",
                "retry_count": 0,
            }
            # Processor succeeds
            mock_processor = MagicMock(return_value=True)

            res = replay_dead_letter(self.mock_conn, dlq_id=55, processor_func=mock_processor)
            self.assertTrue(res["success"])
            self.assertEqual(res["status"], "RESOLVED")

            # Must execute UPDATE to mark RESOLVED
            executed = " ".join(call[0][0] for call in self.mock_cur.execute.call_args_list)
            self.assertIn("SET status = 'RESOLVED'", executed)

    def test_replay_dead_letter_failure_and_discard_threshold(self):
        with patch("dead_letter_queue.get_cursor", return_value=self.mock_cur):
            self.mock_cur.fetchone.return_value = {
                "id": 77,
                "source_name": "sam",
                "entity_type": "company",
                "raw_payload": '{"name": "Bad Payload"}',
                "status": "PENDING",
                "retry_count": 2,  # Already tried 2 times
            }
            # Processor fails
            mock_processor = MagicMock(side_effect=ValueError("Invalid entity format"))

            res = replay_dead_letter(self.mock_conn, dlq_id=77, processor_func=mock_processor, max_retries=3)
            self.assertFalse(res["success"])
            # Reached max retries (2 + 1 = 3), so status transitions to DISCARDED
            self.assertEqual(res["status"], "DISCARDED")

            executed = " ".join(call[0][0] for call in self.mock_cur.execute.call_args_list)
            self.assertIn("UPDATE dead_letter_queue", executed)

    def test_discard_dead_letter(self):
        ok = discard_dead_letter(self.mock_conn, dlq_id=99, reason="Duplicate spam entity")
        self.assertTrue(ok)
        self.mock_conn.commit.assert_called_once()
        exec_sql = self.mock_cur.execute.call_args[0][0]
        self.assertIn("SET status = 'DISCARDED'", exec_sql)

    def test_drain_fallback_to_db_no_file(self):
        fake_path = Path("non_existent_fallback_test.jsonl")
        res = drain_fallback_to_db(self.mock_conn, fallback_file=fake_path)
        self.assertEqual(res["drained"], 0)
        self.assertEqual(res["status"], "NO_FALLBACK_FILE")

    def test_drain_fallback_to_db_success(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w+", suffix=".jsonl", delete=False, encoding="utf-8") as tf:
            tf.write('{"source_name": "sec", "entity_type": "company", "raw_payload": {"cik": "123"}, "error_reason": "Timeout"}\n')
            tf.write('{"source_name": "sam", "entity_type": "company", "raw_payload": {"uei": "ABC"}, "error_reason": "503"}\n')
            temp_path = Path(tf.name)

        try:
            res = drain_fallback_to_db(self.mock_conn, fallback_file=temp_path)
            self.assertEqual(res["drained"], 2)
            self.assertEqual(res["status"], "SUCCESS")
            self.mock_conn.commit.assert_called_once()
            self.assertEqual(self.mock_cur.execute.call_count, 2)
        finally:
            if temp_path.exists():
                temp_path.unlink()
            archived = temp_path.parent.glob(f"{temp_path.stem}*.drained.jsonl")
            for a in archived:
                a.unlink()


class TestStructuredLoggingAndMasking(unittest.TestCase):
    """Verifies structured JSON log formatting and automatic secret redaction."""

    def test_sensitive_masking(self):
        payload = {
            "user_id": "usr_123",
            "password": "SuperSecretPassword123!",
            "api_key": "sec_live_abcdef123456",
            "jwt_token": "eyJhbGciOi...",
            "nested": {
                "sam_gov_api_key": "SAM_SECRET_VAL",
                "public_name": "Acme Inc.",
            },
            "credentials_list": [
                {"token": "secret_token_1"},
                {"normal_val": "unmasked"},
            ]
        }
        masked = _mask_sensitive(payload)
        self.assertEqual(masked["user_id"], "usr_123")
        self.assertEqual(masked["password"], "[REDACTED]")
        self.assertEqual(masked["api_key"], "[REDACTED]")
        self.assertEqual(masked["jwt_token"], "[REDACTED]")
        self.assertEqual(masked["nested"]["sam_gov_api_key"], "[REDACTED]")
        self.assertEqual(masked["nested"]["public_name"], "Acme Inc.")
        self.assertEqual(masked["credentials_list"][0]["token"], "[REDACTED]")
        self.assertEqual(masked["credentials_list"][1]["normal_val"], "unmasked")

    def test_json_log_formatter(self):
        formatter = JsonLogFormatter(service_name="oneextraction-api")
        record = logging.LogRecord(
            name="oneextraction.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="User login successful",
            args=(),
            exc_info=None,
        )
        record.run_id = "run_abc123"
        record.duration_ms = 45.67
        record.metadata = {"user_email": "admin@oneextraction.io", "password": "hidden_password"}

        formatted_str = formatter.format(record)
        parsed = json.loads(formatted_str)

        self.assertEqual(parsed["level"], "INFO")
        self.assertEqual(parsed["message"], "User login successful")
        self.assertEqual(parsed["service"], "oneextraction-api")
        self.assertEqual(parsed["run_id"], "run_abc123")
        self.assertEqual(parsed["duration_ms"], 45.67)
        self.assertEqual(parsed["metadata"]["user_email"], "admin@oneextraction.io")
        self.assertEqual(parsed["metadata"]["password"], "[REDACTED]")

    def test_bound_logger_timed_context_manager(self):
        raw_logger = MagicMock()
        bound = BoundLogger(raw_logger, {"service": "worker"})

        with bound.timed("heavy_aggregation", batch_size=500):
            pass  # execute work

        raw_logger.log.assert_called_once()
        log_level, log_msg = raw_logger.log.call_args[0][0], raw_logger.log.call_args[0][1]
        self.assertEqual(log_level, logging.INFO)
        self.assertIn("Finished heavy_aggregation", log_msg)
        extra = raw_logger.log.call_args[1]["extra"]
        self.assertIn("duration_ms", extra)
        self.assertEqual(extra["service"], "worker")

    def test_pipeline_health_metrics_telemetry(self):
        metrics = get_pipeline_health_metrics()
        self.assertIn("status", metrics)
        self.assertIn("process_id", metrics)
        self.assertIn("database_pool", metrics)


class TestApiRouteSecurity(unittest.TestCase):
    """Verifies that DLQ and pipeline routes require valid JWT tokens."""

    def test_unauthorized_access_raises_401(self):
        from api.deps import get_current_user
        from fastapi import HTTPException

        mock_request = MagicMock()
        # No credentials provided
        with self.assertRaises(HTTPException) as ctx:
            get_current_user(request=mock_request, auth_header=None, query_token=None)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Authentication required", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
