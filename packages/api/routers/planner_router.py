"""DataExtraction — Autonomy Planner router: decisions, run-now, config."""

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from packages.api.dependencies import UserPrincipal, get_current_user, require_admin
from packages.infrastructure.db_connector import get_db_cursor

router = APIRouter(prefix="/api/v1/planner", tags=["Autonomy Planner"])


class RunRequest(BaseModel):
    dry_run: bool = True


@router.get("/decisions")
def list_decisions(limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0),
                   _user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        with get_db_cursor() as (_c, cur):
            cur.execute(
                """
                SELECT id, ts, mode, dry_run, llm_provider, llm_model, plan_json, executed_json,
                       rejected_json, note
                FROM ops_dataextraction.planner_decisions
                ORDER BY ts DESC LIMIT %s OFFSET %s
                """, (limit, offset))
            rows = cur.fetchall()
    except Exception:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Planner history unavailable")
    cols = ("id", "ts", "mode", "dry_run", "llm_provider", "llm_model", "plan", "executed", "rejected", "note")
    return {"decisions": [dict(zip(cols, r)) for r in rows]}


@router.post("/run")
async def run_now(body: RunRequest, _admin: UserPrincipal = Depends(require_admin)) -> Dict[str, Any]:
    """Run one planner cycle immediately. dry_run=true (default) records the plan and starts nothing."""
    from packages.agents.orchestration_agents.autonomy_planner import AutonomyPlannerAgent
    result = await AutonomyPlannerAgent().run_cycle(dry_run=body.dry_run)
    return result


@router.get("/config")
def get_config(_user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    from packages.agents.orchestration_agents.autonomy_planner import (
        ALLOWLIST, dry_run_default, load_planner_config)
    return {
        "config": load_planner_config(),
        "dry_run_default": dry_run_default(),
        "allowed_workflows": {n: {"queue": s.queue, "parameters": sorted(s.params), "description": s.description}
                              for n, s in ALLOWLIST.items()},
    }
