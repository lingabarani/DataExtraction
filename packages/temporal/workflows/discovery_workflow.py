"""
Discovery Search Temporal Workflow.
Orchestrates long-running multi-source discovery queries and automatic database persistence.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.discovery_activities import (
        persist_discovery_results_activity,
        run_discovery_search_activity,
    )

DISCOVERY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=3,
)


@workflow.defn(name="DiscoverySearchWorkflow")
class DiscoverySearchWorkflow:
    """End-to-end workflow executing discovery search and persisting results."""

    @workflow.run
    async def run(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # 1. Execute discovery search across sources
        answer = await workflow.execute_activity(
            run_discovery_search_activity,
            params,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=DISCOVERY_RETRY,
        )

        # 2. Persist canonical organizations and people
        persist_summary = await workflow.execute_activity(
            persist_discovery_results_activity,
            answer,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=DISCOVERY_RETRY,
        )

        return {
            "search_answer": answer,
            "persistence": persist_summary,
        }
