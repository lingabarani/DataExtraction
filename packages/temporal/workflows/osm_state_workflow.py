"""
DataExtraction — OSM State Workflow
=====================================
Orchestrates OpenStreetMap extraction across all 50 US states.
Each state runs as a separate child workflow for independent retry.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.osm_activities import (
        run_osm_state_extraction_activity,
        run_osm_checkpoint_recovery_activity,
        run_osm_circuit_breaker_reset_activity,
    )

OSM_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(hours=1),
    maximum_attempts=3,
)

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


@workflow.defn(name="OSMSingleStateWorkflow")
class OSMSingleStateWorkflow:
    """Child workflow: OSM extraction for a single US state with checkpoint recovery."""

    @workflow.run
    async def run(self, config: dict) -> dict:
        state  = config["state"]
        scope  = config.get("scope", "incremental")
        osm_config = config.get("osm_config", {})

        workflow.logger.info("OSM single state: %s scope=%s", state, scope)

        # Attempt checkpoint recovery first
        checkpoint_result = await workflow.execute_activity(
            run_osm_checkpoint_recovery_activity,
            args=[state],
            task_queue="osm-extraction",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        if checkpoint_result.get("checkpoint_restored"):
            workflow.logger.info("OSM %s: Restored from checkpoint at %s",
                                 state, checkpoint_result.get("resumed_from"))

        # Run extraction
        result = await workflow.execute_activity(
            run_osm_state_extraction_activity,
            args=[state, {**osm_config, "scope": scope}],
            task_queue="osm-extraction",
            start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=timedelta(minutes=15),
            retry_policy=OSM_RETRY,
        )
        return {**result, "checkpoint": checkpoint_result}


@workflow.defn(name="OSMStateWorkflow")
class OSMStateWorkflow:
    """
    Orchestrates OSM extraction for all 50 US states.
    States run in parallel batches of 5 (circuit-breaker aware).
    """

    BATCH_SIZE = 5  # Max concurrent state extractions

    def __init__(self) -> None:
        self._results: dict[str, dict] = {}
        self._paused: bool = False
        self._current_batch: int = 0

    @workflow.signal
    def pause(self) -> None:
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        self._paused = False

    @workflow.query
    def get_status(self) -> dict:
        completed = [s for s, r in self._results.items() if r.get("status") == "SUCCESS"]
        failed    = [s for s, r in self._results.items() if r.get("status") == "FAILED"]
        return {
            "workflow_id": workflow.info().workflow_id,
            "paused": self._paused,
            "current_batch": self._current_batch,
            "completed_states": completed,
            "failed_states": failed,
            "total_states": len(US_STATES),
            "progress_pct": round(len(self._results) / len(US_STATES) * 100, 1),
        }

    @workflow.run
    async def run(self, config: dict) -> dict:
        states = config.get("states")
        if not states or states == "all_50_us":
            states = US_STATES
        scope = config.get("scope", "incremental")
        osm_config = config.get("osm_config", {})

        workflow.logger.info(
            "OSMStateWorkflow: %d states scope=%s batch_size=%d",
            len(states), scope, self.BATCH_SIZE,
        )

        # Run states in batches to respect Overpass API rate limits
        for batch_idx in range(0, len(states), self.BATCH_SIZE):
            await workflow.wait_condition(lambda: not self._paused)
            self._current_batch = batch_idx // self.BATCH_SIZE + 1
            batch = states[batch_idx: batch_idx + self.BATCH_SIZE]

            # Start all child workflows in the batch concurrently
            handles = []
            for state in batch:
                handle = await workflow.start_child_workflow(
                    OSMSingleStateWorkflow.run,
                    args=[{"state": state, "scope": scope, "osm_config": osm_config}],
                    id=f"osm-state-{state}-{workflow.info().workflow_id[:8]}",
                    task_queue="osm-extraction",
                )
                handles.append((state, handle))

            for state, handle in handles:
                try:
                    result = await handle
                    self._results[state] = {"status": "SUCCESS", **result}
                except Exception as exc:
                    self._results[state] = {"status": "FAILED", "error": str(exc)}
                    workflow.logger.error("OSM state %s FAILED: %s", state, exc)

        completed = sum(1 for r in self._results.values() if r["status"] == "SUCCESS")
        return {
            "scope": scope,
            "total_states": len(states),
            "successful_states": completed,
            "failed_states": len(states) - completed,
            "results": self._results,
        }
