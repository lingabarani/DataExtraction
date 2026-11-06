"""
DataExtraction — Unit Test Suite: Worker 7 (Email Enrichment & Verification)
===========================================================================
Validates:
  1. Worker 7 configuration, queue binding to QUEUE_EMAIL_ENRICHMENT
  2. Complete activity registration:
     - create_enrichment_job_activity
     - fetch_pending_enrichment_batch_activity
     - enrich_email_batch_activity
     - finalize_enrichment_job_activity
  3. Workflow definitions registered:
     - EmailEnrichmentWorkflow
     - Agent7EmailEnrichmentWorkflow
  4. Concurrency limits and client integration
  5. Graceful shutdown handler
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from packages.temporal.config import QUEUE_EMAIL_ENRICHMENT, WORKER_MAX_ACTIVITIES
from packages.temporal.workers.worker_email_enrichment import run_worker, main, TASK_QUEUE, MAX_ACTIVITIES
from packages.temporal.activities.email_enrichment_activities import (
    create_enrichment_job_activity,
    fetch_pending_enrichment_batch_activity,
    enrich_email_batch_activity,
    finalize_enrichment_job_activity,
)
from packages.temporal.workflows.w7_email_enrichment_workflow import (
    EmailEnrichmentWorkflow,
    Agent7EmailEnrichmentWorkflow,
)


class TestWorkerEmailEnrichment(unittest.IsolatedAsyncioTestCase):

    def test_queue_and_concurrency_config(self):
        """Verifies queue matches canonical queue registry and concurrency is bounded."""
        self.assertEqual(TASK_QUEUE, QUEUE_EMAIL_ENRICHMENT)
        self.assertEqual(TASK_QUEUE, "email-enrichment-queue")
        self.assertGreater(MAX_ACTIVITIES, 0)
        self.assertLessEqual(MAX_ACTIVITIES, 100)

    @patch("packages.temporal.workers.worker_email_enrichment.Worker")
    @patch("packages.temporal.workers.worker_email_enrichment.get_temporal_client", new_callable=AsyncMock)
    async def test_worker_initialization_and_registrations(self, mock_get_client, mock_worker_cls):
        """Verifies worker registers all required activities and workflows with Temporal."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_worker_instance = MagicMock()
        mock_worker_instance.run = AsyncMock()
        mock_worker_cls.return_value = mock_worker_instance

        await run_worker()

        mock_get_client.assert_awaited_once()
        mock_worker_cls.assert_called_once()
        kwargs = mock_worker_cls.call_args[1]

        # Verify task queue
        self.assertEqual(kwargs["task_queue"], "email-enrichment-queue")

        # Verify workflows
        workflows = kwargs["workflows"]
        self.assertIn(EmailEnrichmentWorkflow, workflows)
        self.assertIn(Agent7EmailEnrichmentWorkflow, workflows)

        # Verify activities
        activities = kwargs["activities"]
        self.assertIn(create_enrichment_job_activity, activities)
        self.assertIn(fetch_pending_enrichment_batch_activity, activities)
        self.assertIn(enrich_email_batch_activity, activities)
        self.assertIn(finalize_enrichment_job_activity, activities)

        # Verify concurrency
        self.assertEqual(kwargs["max_concurrent_activities"], MAX_ACTIVITIES)

        # Verify worker.run was awaited
        mock_worker_instance.run.assert_awaited_once()

    @patch("packages.temporal.workers.worker_email_enrichment.run_worker")
    @patch("packages.temporal.workers.worker_email_enrichment.asyncio.run")
    def test_main_clean_exit_on_interrupt(self, mock_asyncio_run, mock_run_worker):
        """Verifies main catches KeyboardInterrupt and shuts down gracefully without unhandled exception."""
        mock_run_worker.return_value = None
        mock_asyncio_run.side_effect = KeyboardInterrupt()
        try:
            main()
        except KeyboardInterrupt:
            self.fail("main() failed to catch KeyboardInterrupt gracefully")


if __name__ == "__main__":
    unittest.main()
