"""
DataExtraction — Platform SRE Supervisor Temporal Query Tool
===========================================================
Provides cluster visibility, workflow inspection, and query execution for
platform supervisors.
"""

import logging
from typing import Dict, Any, List, Optional
from packages.temporal.client import get_temporal_client

logger = logging.getLogger("dataextraction.supervisor.tools.temporal")


async def list_active_workflows(workflow_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Lists currently running Temporal workflows, optionally filtered by workflow type.
    """
    workflows = []
    try:
        client = await get_temporal_client()
        query = "ExecutionStatus='Running'"
        if workflow_type:
            query += f" AND WorkflowType='{workflow_type}'"

        async for wf in await client.list_workflows(query):
            workflows.append({
                "id": wf.id,
                "run_id": wf.run_id,
                "workflow_type": wf.workflow_type,
                "start_time": wf.start_time.isoformat() if wf.start_time else None,
                "status": "RUNNING"
            })
    except Exception as exc:
        logger.warning("Error querying active workflows from Temporal cluster: %s", exc)

    return workflows


async def list_completed_workflows(workflow_type: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Lists recently completed workflows for health auditing.
    """
    workflows = []
    try:
        client = await get_temporal_client()
        query = "ExecutionStatus='Completed'"
        if workflow_type:
            query += f" AND WorkflowType='{workflow_type}'"

        count = 0
        async for wf in await client.list_workflows(query):
            workflows.append({
                "id": wf.id,
                "run_id": wf.run_id,
                "workflow_type": wf.workflow_type,
                "close_time": wf.close_time.isoformat() if wf.close_time else None,
                "status": "COMPLETED"
            })
            count += 1
            if count >= limit:
                break
    except Exception as exc:
        logger.warning("Error querying completed workflows: %s", exc)

    return workflows


async def list_schedules() -> List[Dict[str, Any]]:
    """
    Lists all registered Temporal schedules and next actions.
    """
    schedules = []
    try:
        client = await get_temporal_client()
        async for sched in await client.list_schedules():
            schedules.append({
                "id": sched.id,
                "paused": getattr(sched.schedule.state, "paused", False) if hasattr(sched, "schedule") else False,
            })
    except Exception as exc:
        logger.warning("Error querying schedules from Temporal cluster: %s", exc)
    return schedules


__all__ = [
    "list_active_workflows",
    "list_completed_workflows",
    "list_schedules",
]

