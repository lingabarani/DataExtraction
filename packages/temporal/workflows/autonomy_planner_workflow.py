"""
DataExtraction — Autonomy Planner Workflow
==========================================
Scheduled every few minutes (config/schedules.yaml). Runs on the governance queue.
One cycle: observe -> plan -> guardrails -> start workflows -> audit.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.planner_activities import run_autonomy_planner_cycle_activity


@workflow.defn(name="AutonomyPlannerWorkflow")
class AutonomyPlannerWorkflow:
    @workflow.run
    async def run(self, config: dict) -> dict:
        return await workflow.execute_activity(
            run_autonomy_planner_cycle_activity,
            args=[config or {}],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=15)),
        )
