"""
DataExtraction — Unit Test Suite: Task 9 (7-Day Reliability & Chaos Fault Injection)
===================================================================================
Validates:
  1. Database transient network drop & connection recovery.
  2. OpenSearch 429 cluster backpressure & CDC watermark safety.
  3. OneReach outbound outage, exponential backoff, and PostgreSQL DLQ capture.
  4. Worker termination & idempotent workflow batch replay.
  5. 7-day reliability simulation metrics (MTBF, MTTR, zero data loss, 100% DLQ accuracy).
"""

import unittest
from packages.benchmarks.reliability_test_7d import (
    ChaosFaultInjector,
    ChaosFaultResult,
    ReliabilityReport,
    ReliabilitySimulator,
)


class TestReliability7d(unittest.TestCase):

    def setUp(self):
        self.injector = ChaosFaultInjector()

    def test_database_transient_disconnect_recovery(self):
        """Verifies Fault 1: Platform recovers from transient DB drop without data loss."""
        result: ChaosFaultResult = self.injector.test_database_transient_disconnect()

        self.assertEqual(result.fault_type, "DATABASE_TRANSIENT_DISCONNECT")
        self.assertTrue(result.recovered)
        self.assertFalse(result.data_loss_occurred)
        self.assertGreater(result.recovery_time_sec, 0.0)
        self.assertEqual(result.details["attempts_before_recovery"], 3)

    def test_opensearch_throttle_and_watermark_safety(self):
        """Verifies Fault 2: CDC watermark halts before 429 failed document and preserves safety."""
        result: ChaosFaultResult = self.injector.test_opensearch_throttle_and_watermark_safety()

        self.assertEqual(result.fault_type, "OPENSEARCH_429_THROTTLING")
        self.assertTrue(result.recovered)
        self.assertFalse(result.data_loss_occurred)
        self.assertEqual(result.details["halted_watermark"], 101)
        self.assertTrue(result.details["silent_skip_prevented"])

    def test_onereach_outbound_failure_and_dlq_routing(self):
        """Verifies Fault 3: Permanent outbound failure exhausts retries and enqueues to DLQ."""
        result: ChaosFaultResult = self.injector.test_onereach_outbound_failure_and_dlq()

        self.assertEqual(result.fault_type, "ONEREACH_OUTBOUND_OUTAGE")
        self.assertTrue(result.recovered)
        self.assertFalse(result.data_loss_occurred)
        self.assertTrue(result.dlq_routed)
        self.assertEqual(result.details["attempt_count"], 3)
        self.assertEqual(result.details["delivery_status"], "FAILED")

    def test_worker_crash_and_idempotent_recovery(self):
        """Verifies Fault 4: Worker termination mid-batch recovers idempotently without duplicate records."""
        result: ChaosFaultResult = self.injector.test_worker_crash_and_idempotent_recovery()

        self.assertEqual(result.fault_type, "WORKER_CRASH_RESUME")
        self.assertTrue(result.recovered)
        self.assertFalse(result.data_loss_occurred)
        self.assertTrue(result.details["idempotent_replay"])
        self.assertEqual(result.details["duplicate_records_created"], 0)

    def test_full_7d_simulation_run_and_certification(self):
        """Verifies complete 7-day reliability simulation achieves 100% recovery and certification."""
        simulator = ReliabilitySimulator(days=7, accelerated=True)
        report: ReliabilityReport = simulator.run()

        self.assertEqual(report.simulated_days, 7)
        self.assertEqual(report.total_faults_injected, 4)
        self.assertEqual(report.total_faults_recovered, 4)
        self.assertEqual(report.fault_recovery_rate_pct, 100.0)
        self.assertEqual(report.data_loss_rate_pct, 0.0)
        self.assertEqual(report.dlq_accuracy_pct, 100.0)
        self.assertTrue(report.overall_certified)
        self.assertGreater(report.mttr_sec, 0.0)
        self.assertGreater(report.mtbf_sec, 0.0)


if __name__ == "__main__":
    unittest.main()
