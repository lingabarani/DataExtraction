"""
DataExtraction — Agent Temporal Query Tool
==========================================
Provides inspection utilities for querying running/completed workflows,
execution history, and registered schedules.
"""

import logging
from typing import Dict, Any, List, Optional
from packages.temporal.client import get_temporal_client

logger = logging.getLogger("dataextraction.agents.tools.temporal")


async def list_active_workflows(workflow_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Lists currently running workflows, optionally filtered by type.
    """
    client = await get_temporal_client()
    query = "ExecutionStatus='Running'"
    if workflow_type:
        query += f" AND WorkflowType='{workflow_type}'"

    workflows = []
    try:
        async for wf in await client.list_workflows(query):
            workflows.append({
                "id": wf.id,
                "run_id": wf.run_id,
                "workflow_type": wf.workflow_type,
                "start_time": wf.start_time.isoformat() if wf.start_time else None,
                "status": "RUNNING"
            })
    except Exception as exc:
        logger.warning("Error querying active workflows: %s", exc)
    return workflows


async def list_completed_workflows(workflow_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Lists recently completed workflows.
    """
    client = await get_temporal_client()
    query = "ExecutionStatus='Completed'"
    if workflow_type:
        query += f" AND WorkflowType='{workflow_type}'"

    workflows = []
    try:
        async for wf in await client.list_workflows(query):
            workflows.append({
                "id": wf.id,
                "run_id": wf.run_id,
                "workflow_type": wf.workflow_type,
                "close_time": wf.close_time.isoformat() if wf.close_time else None,
                "status": "COMPLETED"
            })
            if len(workflows) >= limit:
                break
    except Exception as exc:
        logger.warning("Error querying completed workflows: %s", exc)
    return workflows


async def list_schedules() -> List[Dict[str, Any]]:
    """
    Lists all registered Temporal schedules and next actions.
    """
    client = await get_temporal_client()
    schedules = []
    try:
        async for sched in await client.list_schedules():
            schedules.append({
                "id": sched.id,
                "paused": getattr(sched.schedule.state, "paused", False) if hasattr(sched, "schedule") else False,
            })
    except Exception as exc:
        logger.warning("Error querying schedules: %s", exc)
    return schedules

