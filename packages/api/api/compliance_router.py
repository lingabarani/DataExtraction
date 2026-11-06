"""
DataExtraction Enterprise — GDPR/CCPA Compliance & SOC-2 Audit Router
Exposes suppression endpoints, right-to-be-forgotten purge execution, and audit log inspection.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from packages.api.dependencies import get_current_user, require_admin, UserPrincipal
from packages.domain.compliance_manager import ComplianceManager
from packages.infrastructure.audit_trail_repository import AuditTrailRepository

router = APIRouter(prefix="/api/compliance", tags=["Compliance & Governance"])


class OptOutRequest(BaseModel):
    identifier: str = Field(..., description="Email, phone number, or domain to opt-out")
    identifier_type: str = Field("email", description="'email', 'phone', or 'domain'")
    reason: str = Field("GDPR_FORGOTTEN", description="Regulatory or consumer reason")


class PurgeRequest(BaseModel):
    identifier: str = Field(..., description="Identifier whose PII records must be scrubbed")
    identifier_type: str = Field("email", description="'email', 'phone', or 'domain'")
    dry_run: bool = Field(False, description="Simulate record count without mutating database")


@router.post("/opt-out", status_code=status.HTTP_200_OK)
def register_opt_out(
    payload: OptOutRequest,
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """Registers an active suppression entry to block outbound extraction and emailing."""
    try:
        return ComplianceManager.register_suppression(
            identifier=payload.identifier,
            identifier_type=payload.identifier_type,
            reason=payload.reason,
            actor_email=current_user.email,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to record opt-out: {str(exc)}",
        )


@router.post("/purge", status_code=status.HTTP_200_OK)
def execute_compliance_purge(
    payload: PurgeRequest,
    current_user: UserPrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Executes a GDPR/CCPA right-to-be-forgotten PII purge across lead and people tables.
    Restricted to administrative operators.
    """
    try:
        return ComplianceManager.execute_purge(
            identifier=payload.identifier,
            identifier_type=payload.identifier_type,
            dry_run=payload.dry_run,
            actor_email=current_user.email,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Purge execution failed: {str(exc)}",
        )


@router.get("/status/{identifier}")
def check_suppression_status(
    identifier: str,
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """Checks whether an identifier is actively suppressed from extraction."""
    is_suppressed = ComplianceManager.is_suppressed(identifier)
    return {
        "identifier": identifier,
        "hashed_identifier": ComplianceManager.hash_identifier(identifier),
        "is_suppressed": is_suppressed,
    }


@router.get("/audit-logs")
def get_audit_trail_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    current_user: UserPrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """Retrieves immutable SOC-2 Type II audit logs for compliance review."""
    logs = AuditTrailRepository.query_access_logs(
        limit=limit,
        offset=offset,
        action=action,
        user_id=user_id,
    )
    return {
        "count": len(logs),
        "limit": limit,
        "offset": offset,
        "logs": logs,
    }

