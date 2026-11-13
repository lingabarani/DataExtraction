"""
DataExtraction — Unified API Dependency Injection (Single Source of Truth)
===========================================================================
This is the CANONICAL auth/dependency module for all FastAPI route handlers.
All routers must import from here — never from packages.api.routers.deps or
packages.api.deps directly.

Provides:
  - JWT validation (HS256 or RS256) with strict error handling
  - UserPrincipal model
  - get_current_user / get_optional_user / require_admin
  - Database connection scoped to request lifecycle
  - Temporal client dependency
"""

import logging
from typing import Any, Generator, Optional

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
from pydantic import BaseModel

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.db_connector import get_connection, release_connection

logger = logging.getLogger("dataextraction.api.auth")

_bearer_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class UserPrincipal(BaseModel):
    """Authenticated user context attached to every protected request."""
    id: str
    email: str
    name: str
    workspace_id: str = "ws-001"
    is_admin: bool = False


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _decode_token(token: str) -> dict:
    """
    Decodes and validates a JWT token using the configured algorithm and key.
    Raises JWTError on invalid / expired tokens — never swallows exceptions.
    """
    algorithm = config_manager.get_jwt_algorithm().upper()
    key = (
        config_manager.get_jwt_public_key()
        if algorithm.startswith("RS")
        else config_manager.get_jwt_secret()
    )
    return jwt.decode(token, key, algorithms=[algorithm])


# ---------------------------------------------------------------------------
# Auth dependencies
# ---------------------------------------------------------------------------

def get_current_user(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    query_token: Optional[str] = Query(None, alias="token"),
) -> UserPrincipal:
    """
    Validates JWT from Bearer header or ?token= query parameter.
    Returns the authenticated UserPrincipal.
    When AUTH_REQUIRED=false is explicitly configured in non-production environments
    and no token is provided, falls back to the configured local operator principal.
    If a token is provided, it is always strictly verified regardless of AUTH_REQUIRED.
    """
    token: Optional[str] = None
    if auth_header and auth_header.credentials:
        token = auth_header.credentials
    elif query_token:
        token = query_token

    if not token:
        if not config_manager.is_auth_required():
            op = config_manager.get_operator_principal_config()
            logger.debug(
                "AUTH_REQUIRED=false (env=%s): using configured operator principal %s",
                config_manager.environment,
                op["email"],
            )
            return UserPrincipal(
                id=op["id"],
                email=op["email"],
                name=op["name"],
                workspace_id=op["workspace_id"],
                is_admin=op["is_admin"],
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token or ?token= parameter.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = _decode_token(token)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as exc:
        logger.warning("JWT decode failure from %s: %s", request.client and request.client.host, exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = payload.get("sub") or payload.get("email")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing subject identifier.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserPrincipal(
        id=str(payload.get("uid") or subject),
        email=str(subject),
        name=str(payload.get("name") or "User"),
        workspace_id=str(payload.get("workspace_id") or "ws-001"),
        is_admin=bool(payload.get("is_admin", False)),
    )


def get_optional_user(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    query_token: Optional[str] = Query(None, alias="token"),
) -> Optional[UserPrincipal]:
    """Returns UserPrincipal if a valid token is provided, otherwise None."""
    try:
        return get_current_user(request, auth_header, query_token)
    except HTTPException:
        return None


def require_admin(current_user: UserPrincipal = Depends(get_current_user)) -> UserPrincipal:
    """Enforces admin-only access. Raises HTTP 403 for non-admin users."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges are required for this operation.",
        )
    return current_user


# ---------------------------------------------------------------------------
# Database dependency
# ---------------------------------------------------------------------------

def get_db() -> Generator[Any, None, None]:
    """
    Yields a PostgreSQL connection from the pool, scoped to the request.
    Guarantees the connection is returned on completion or error.
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        try:
            release_connection(conn)
        except Exception as exc:
            logger.warning("Error releasing DB connection in dependency: %s", exc)


# ---------------------------------------------------------------------------
# Temporal client dependency
# ---------------------------------------------------------------------------

async def get_temporal_client_dep():
    """Yields a connected Temporal client for orchestration requests."""
    from packages.temporal.client import get_temporal_client
    return await get_temporal_client()


__all__ = [
    "UserPrincipal",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "get_db",
    "get_temporal_client_dep",
]
