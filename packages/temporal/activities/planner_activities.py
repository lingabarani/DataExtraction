"""Temporal activity that runs one Autonomy Planner cycle."""

import logging

from temporalio import activity

logger = logging.getLogger("dataextraction.activities.planner")


@activity.defn(name="run_autonomy_planner_cycle")
async def run_autonomy_planner_cycle_activity(options: dict) -> dict:
    """options: {"dry_run": bool | None}. Returns the cycle summary (no secrets, no prompts)."""
    from packages.agents.orchestration_agents.autonomy_planner import AutonomyPlannerAgent
    options = options or {}
    agent = AutonomyPlannerAgent()
    result = await agent.run_cycle(dry_run=options.get("dry_run"))
    logger.info("Planner cycle: status=%s mode=%s started=%d rejected=%d",
                result.get("status"), result.get("mode"),
                sum(1 for e in result.get("executed", []) if e.get("started")),
                len(result.get("rejected", [])))
    return result
