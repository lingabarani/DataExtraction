"""
DataExtraction — Pipeline Orchestration Router
===============================================
FastAPI endpoints for managing Temporal workflows and schedules.
Provides starting, pausing, resuming, cancelling, and querying pipelines.
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from packages.api.routers.deps import UserPrincipal, get_current_user
from packages.temporal.client import get_temporal_client
from packages.temporal.workflows.master_orchestration_workflow import MasterOrchestrationWorkflow
from packages.temporal.workflows.federal_ingestion_workflow import FederalIngestionWorkflow
from packages.temporal.workflows.gmaps_extraction_workflow import GMapsExtractionWorkflow
from packages.temporal.workflows.osm_state_workflow import OSMStateWorkflow
from packages.temporal.workflows.lead_enrichment_workflow import LeadEnrichmentWorkflow
from packages.temporal.workflows.dlq_replay_workflow import DLQReplayWorkflow

logger = logging.getLogger("dataextraction.api.pipelines")

router = APIRouter(prefix="/pipelines", tags=["Temporal Pipelines"])

WORKFLOW_MAP = {
    "MasterOrchestrationWorkflow": (MasterOrchestrationWorkflow, "federal-ingestion"),
    "FederalIngestionWorkflow": (FederalIngestionWorkflow, "federal-ingestion"),
    "GMapsExtractionWorkflow": (GMapsExtractionWorkflow, "gmaps-extraction"),
    "OSMStateWorkflow": (OSMStateWorkflow, "osm-extraction"),
    "LeadEnrichmentWorkflow": (LeadEnrichmentWorkflow, "data-pipeline"),
    "DLQReplayWorkflow": (DLQReplayWorkflow, "storage-ops"),
}


class PipelineStartRequest(BaseModel):
    workflow_type: str = Field(
        default="MasterOrchestrationWorkflow",
        description="Workflow class name to execute",
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration parameters passed to workflow.run()",
    )
    workflow_id: Optional[str] = Field(
        default=None,
        description="Optional custom workflow ID. If omitted, a UUID is generated.",
    )
    task_queue: Optional[str] = Field(
        default=None,
        description="Optional override task queue.",
    )


class PipelineActionResponse(BaseModel):
    workflow_id: str
    status: str
    message: Optional[str] = None
    run_id: Optional[str] = None


@router.post(
    "/start",
    response_model=PipelineActionResponse,
    summary="Start an extraction pipeline workflow",
)
async def start_pipeline(
    req: PipelineStartRequest,
    current_user: UserPrincipal = Depends(get_current_user),
):
    """
    Starts an asynchronous Temporal workflow.
    Defaults to MasterOrchestrationWorkflow.
    """
    if req.workflow_type not in WORKFLOW_MAP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown workflow type '{req.workflow_type}'. Supported: {list(WORKFLOW_MAP.keys())}",
        )

    wf_cls, default_queue = WORKFLOW_MAP[req.workflow_type]
    task_queue = req.task_queue or default_queue
    workflow_id = req.workflow_id or f"{req.workflow_type.lower()}-{uuid4().hex[:8]}"

    try:
        client = await get_temporal_client()
        handle = await client.start_workflow(
            wf_cls.run,
            req.config,
            id=workflow_id,
            task_queue=task_queue,
        )
        logger.info(
            "User %s started workflow %s (type=%s, queue=%s)",
            current_user.email,
            workflow_id,
            req.workflow_type,
            task_queue,
        )
        return PipelineActionResponse(
            workflow_id=handle.id,
            run_id=handle.first_execution_run_id,
            status="STARTED",
            message=f"Workflow {req.workflow_type} triggered successfully.",
        )
    except Exception as exc:
        logger.error("Failed to start workflow %s: %s", req.workflow_type, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start workflow: {str(exc)}",
        )


@router.get(
    "/{workflow_id}",
    summary="Query live workflow status",
)
async def get_pipeline_status(
    workflow_id: str,
    current_user: UserPrincipal = Depends(get_current_user),
):
    """
    Queries running or completed workflow state directly from Temporal.
    """
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        # Attempt to run query
        try:
            status_data = await handle.query("get_status")
            return {"workflow_id": workflow_id, "status": "RUNNING", "details": status_data}
        except Exception:
            # Fall back to workflow description
            desc = await handle.describe()
            return {
                "workflow_id": workflow_id,
                "status": desc.status.name,
                "start_time": desc.start_time.isoformat() if desc.start_time else None,
                "close_time": desc.close_time.isoformat() if desc.close_time else None,
            }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow '{workflow_id}' not found or unreachable: {exc}",
        )


@router.post(
    "/{workflow_id}/pause",
    response_model=PipelineActionResponse,
    summary="Pause a running workflow",
)
async def pause_pipeline(
    workflow_id: str,
    current_user: UserPrincipal = Depends(get_current_user),
):
    """
    Sends pause signal to an active workflow.
    """
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("pause")
        logger.info("Workflow %s paused by %s", workflow_id, current_user.email)
        return PipelineActionResponse(
            workflow_id=workflow_id,
            status="PAUSED",
            message="Pause signal sent successfully.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to signal pause: {exc}",
        )


@router.post(
    "/{workflow_id}/resume",
    response_model=PipelineActionResponse,
    summary="Resume a paused workflow",
)
async def resume_pipeline(
    workflow_id: str,
    current_user: UserPrincipal = Depends(get_current_user),
):
    """
    Sends resume signal to an active workflow.
    """
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("resume")
        logger.info("Workflow %s resumed by %s", workflow_id, current_user.email)
        return PipelineActionResponse(
            workflow_id=workflow_id,
            status="RESUMED",
            message="Resume signal sent successfully.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to signal resume: {exc}",
        )


@router.delete(
    "/{workflow_id}",
    response_model=PipelineActionResponse,
    summary="Cancel a workflow execution",
)
async def cancel_pipeline(
    workflow_id: str,
    current_user: UserPrincipal = Depends(get_current_user),
):
    """
    Gracefully cancels a running Temporal workflow.
    """
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        await handle.cancel()
        logger.warning("Workflow %s cancelled by %s", workflow_id, current_user.email)
        return PipelineActionResponse(
            workflow_id=workflow_id,
            status="CANCELLED",
            message="Cancellation request delivered.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel workflow: {exc}",
        )


@router.get(
    "/schedules/list",
    summary="List all registered extraction schedules",
)
async def list_schedules(
    current_user: UserPrincipal = Depends(get_current_user),
):
    """
    Returns list of automated cron schedules registered in Temporal.
    """
    try:
        client = await get_temporal_client()
        schedules = []
        async for sched in await client.list_schedules():
            schedules.append({
                "id": sched.id,
                "paused": sched.info.paused if hasattr(sched.info, "paused") else False,
                "recent_actions": len(sched.info.recent_actions) if hasattr(sched.info, "recent_actions") else 0,
            })
        return {"schedules": schedules, "total": len(schedules)}
    except Exception as exc:
        logger.warning("Schedule list query encountered error: %s", exc)
        return {"schedules": [], "total": 0, "notice": str(exc)}
