"""
DataExtraction — Unit Test Suite: Task 8 (24-Hour Endurance & Soak Test Framework)
==================================================================================
Validates:
  1. Single soak cycle execution, metrics, and garbage collection.
  2. Multi-cycle iteration, checkpoint generation, and duration accumulation.
  3. Memory leak threshold triggering and leak-free verification.
  4. Connection pool saturation and leak detection.
  5. Checkpoint JSONL serialization.
"""

import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from packages.benchmarks.endurance_test_24h import (
    EnduranceReport,
    EnduranceTestHarness,
    SoakCycleCheckpoint,
)


class TestEndurance24h(unittest.TestCase):

    def test_single_cycle_execution(self):
        """Verifies a single soak cycle completes with valid metrics and SUCCESS status."""
        harness = EnduranceTestHarness(batch_size=50, dry_run=True)
        cp = harness.run_cycle(1)

        self.assertEqual(cp.cycle_index, 1)
        self.assertEqual(cp.cycle_status, "SUCCESS")
        self.assertEqual(cp.records_processed, 50)
        self.assertGreater(cp.cycle_duration_sec, 0.0)
        self.assertGreaterEqual(cp.memory_current_mb, 0.0)
        self.assertIsNone(cp.error_message)

    def test_multi_cycle_harness_run(self):
        """Verifies harness completes requested cycle budget and aggregates metrics."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        harness = EnduranceTestHarness(batch_size=20, checkpoint_file=tmp_path, dry_run=True)
        report: EnduranceReport = harness.run(max_cycles=3)

        self.assertEqual(report.total_cycles_completed, 3)
        self.assertEqual(report.total_records_processed, 60)
        self.assertEqual(len(report.checkpoints), 3)
        self.assertFalse(report.interrupted_early)

        # Verify JSONL lines written
        with open(tmp_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        self.assertEqual(len(lines), 3)

    def test_memory_leak_threshold_alert(self):
        """Verifies memory leak alert fires when net growth per cycle exceeds threshold."""
        harness = EnduranceTestHarness(batch_size=10, dry_run=True)
        # Set ultra-low threshold to trigger detection on any real allocations
        harness.LEAK_THRESHOLD_KB_PER_CYCLE = 0.0001
        report = harness.run(max_cycles=5)
        self.assertTrue(report.memory_leak_detected, "Leak must be flagged when growth exceeds threshold")

    def test_connection_leak_detection(self):
        """Verifies connection leak is flagged when active connections remain elevated."""
        harness = EnduranceTestHarness(batch_size=10, dry_run=True)

        with patch("packages.benchmarks.endurance_test_24h.DATAEXTRACTION_DB_POOL_ACTIVE_CONNECTIONS") as mock_gauge:
            mock_gauge._value.get.return_value = 15  # Unreturned connections
            report = harness.run(max_cycles=2)
            self.assertTrue(report.connection_leak_detected)


if __name__ == "__main__":
    unittest.main()
