"""
DataExtraction — API Key Management Router (admin only)
=======================================================
Add, rotate, disable and test API keys. Plaintext is accepted on create only and is
never returned, logged or echoed. Listings show the last 4 characters.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from packages.api.dependencies import UserPrincipal, require_admin
from packages.infrastructure.config_manager import ConfigurationError
from packages.infrastructure.key_vault import get_secrets_manager
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("api.secrets")
router = APIRouter(prefix="/api/v1/secrets", tags=["Secrets"])

Provider = Literal["groq", "aws", "linkedin", "search", "brave", "tavily"]


class KeyCreate(BaseModel):
    provider: Provider
    value: str = Field(..., min_length=8, max_length=4096, repr=False)
    label: str = Field("", max_length=120)
    priority: int = Field(100, ge=1, le=1000)
    expires_at: Optional[datetime] = None

    @field_validator("value")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 8:
            raise ValueError("key value is too short")
        return v


class KeyUpdate(BaseModel):
    status: Optional[Literal["active", "disabled", "invalid", "expired"]] = None
    priority: Optional[int] = Field(None, ge=1, le=1000)
    expires_at: Optional[datetime] = None
    clear_expiry: bool = False


def _db_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ConfigurationError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Key store unavailable")


@router.post("/keys", status_code=status.HTTP_201_CREATED)
def create_key(body: KeyCreate, admin: UserPrincipal = Depends(require_admin)) -> Dict[str, Any]:
    try:
        key_id = get_secrets_manager().add_key(
            body.provider, body.value, label=body.label, priority=body.priority,
            expires_at=body.expires_at, created_by=admin.email,
        )
    except ConfigurationError as exc:
        raise _db_error(exc)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except Exception as exc:
        logger.error("create_key failed: %s", type(exc).__name__)
        raise _db_error(exc)
    return {"id": key_id, "provider": body.provider, "label": body.label, "masked": "****" + body.value[-4:]}


@router.get("/keys")
def list_keys(provider: Optional[Provider] = None,
              _admin: UserPrincipal = Depends(require_admin)) -> Dict[str, List[Dict[str, Any]]]:
    try:
        keys = get_secrets_manager().list_keys(provider)
    except Exception as exc:
        raise _db_error(exc)
    return {"keys": keys}


@router.patch("/keys/{key_id}")
def update_key(key_id: str, body: KeyUpdate, _admin: UserPrincipal = Depends(require_admin)) -> Dict[str, Any]:
    try:
        ok = get_secrets_manager().update_key(
            key_id, status=body.status, priority=body.priority,
            expires_at=body.expires_at, clear_expiry=body.clear_expiry)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    except Exception as exc:
        raise _db_error(exc)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found or nothing to update")
    return {"id": key_id, "updated": True}


@router.delete("/keys/{key_id}")
def delete_key(key_id: str, _admin: UserPrincipal = Depends(require_admin)) -> Dict[str, Any]:
    try:
        ok = get_secrets_manager().delete_key(key_id)
    except Exception as exc:
        raise _db_error(exc)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    return {"id": key_id, "deleted": True}


@router.post("/keys/{key_id}/test")
def test_key(key_id: str, _admin: UserPrincipal = Depends(require_admin)) -> Dict[str, Any]:
    """Make one tiny request with this specific key. Marks it invalid on 401/403."""
    mgr = get_secrets_manager()
    try:
        rec = mgr.get_key_by_id(key_id)
    except Exception as exc:
        raise _db_error(exc)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    if rec.provider != "groq":
        return {"ok": None, "detail": f"Live test is not implemented for provider '{rec.provider}'"}
    from packages.infrastructure.llm.groq_provider import probe_groq_key
    result = probe_groq_key(rec.value)
    if result.get("status_code") in (401, 403):
        mgr.report_failure(rec, result["status_code"])
    return {"id": key_id, **result}
