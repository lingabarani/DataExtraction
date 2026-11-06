"""
DataExtraction — Unit Test Suite: Task 7 (100k+ Load Test Harness)
==================================================================
Validates:
  1. Record generator schema compliance, NAICS codes, and email formatting.
  2. Duplicate cluster generation for entity resolution benchmark fidelity.
  3. Memory-safe streaming generator batching.
  4. Load test runner execution, latency percentile calculation, and throughput metrics.
  5. bulk_upsert_staging_records parameter formatting and execute_values integration.
"""

import unittest
from unittest.mock import MagicMock, patch

from packages.benchmarks.load_test_100k import (
    LoadTestMetrics,
    LoadTestRunner,
    StreamRecordGenerator,
)
from packages.infrastructure.staging_writer import bulk_upsert_staging_records


class TestLoadTest100k(unittest.TestCase):

    def setUp(self):
        self.generator = StreamRecordGenerator(seed=42, duplicate_ratio=0.20)

    def test_record_generator_schema_and_completeness(self):
        """Verifies record generator outputs complete company and executive payloads."""
        record = self.generator.generate_record(1)

        # Company fields
        self.assertIn("id", record)
        self.assertIn("company_name", record)
        self.assertIn("domain", record)
        self.assertIn("city", record)
        self.assertIn("state_code", record)
        self.assertIn("naics_code", record)
        self.assertIn("ein", record)

        # Executive fields
        self.assertIn("full_name", record)
        self.assertIn("title", record)
        self.assertIn("seniority_level", record)
        self.assertIn("department", record)
        self.assertIn("email", record)
        self.assertIn("@", record["email"])

    def test_record_generator_duplicate_clusters(self):
        """Verifies duplicate ratio creates intentional clusters for entity resolution testing."""
        records = [self.generator.generate_record(i) for i in range(1, 200)]
        domains = [r["domain"] for r in records]
        unique_domains = set(domains)

        # Since duplicate_ratio=0.20, unique domains should be less than total records
        self.assertLess(len(unique_domains), len(records))

    def test_streaming_batches_generator(self):
        """Verifies batch generator yields correct chunk counts without truncation."""
        batches = list(self.generator.generate_batches(total_records=250, batch_size=100))
        self.assertEqual(len(batches), 3)
        self.assertEqual(len(batches[0]), 100)
        self.assertEqual(len(batches[1]), 100)
        self.assertEqual(len(batches[2]), 50)
        self.assertEqual(sum(len(b) for b in batches), 250)

    def test_load_test_runner_dry_run_execution(self):
        """Verifies LoadTestRunner calculates valid percentiles and non-zero throughput."""
        runner = LoadTestRunner(dry_run=True)
        metrics: LoadTestMetrics = runner.run(total_records=500, batch_size=100)

        self.assertEqual(metrics.total_records, 500)
        self.assertEqual(metrics.batch_size, 100)
        self.assertEqual(metrics.total_batches, 5)
        self.assertGreater(metrics.throughput_rps, 0)
        self.assertGreater(metrics.total_duration_sec, 0)
        self.assertGreaterEqual(metrics.latency_p99_ms, metrics.latency_p50_ms)
        self.assertEqual(metrics.errors_encountered, 0)
        self.assertTrue(metrics.dry_run)

    @patch("psycopg2.extras.execute_values")
    def test_bulk_upsert_staging_records(self, mock_execute_values):
        """Verifies bulk_upsert_staging_records executes batch insertions for both companies and people."""
        mock_cur = MagicMock()
        records = [self.generator.generate_record(i) for i in range(1, 11)]

        comp_count, people_count = bulk_upsert_staging_records(mock_cur, records, source="TEST_LOAD")

        self.assertEqual(comp_count, 10)
        self.assertEqual(people_count, 10)
        # execute_values called twice: once for companies, once for people
        self.assertEqual(mock_execute_values.call_count, 2)


if __name__ == "__main__":
    unittest.main()

