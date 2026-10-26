"""
OneExtraction — Authentication & Authorization Dependencies
Provides JWT authentication guards for all FastAPI route handlers.
Supports Authorization: Bearer <token> headers and query-based tokens for streaming downloads.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import sys
from pydantic import BaseModel

_BOTA_DIR = Path(__file__).resolve().parent.parent
if str(_BOTA_DIR) not in sys.path:
    sys.path.insert(0, str(_BOTA_DIR))

from config_manager import config_manager

SECRET_KEY = config_manager.get_jwt_secret()
ALGORITHM = config_manager.get_jwt_algorithm()

# Optional bearer scheme (does not automatically fail so query param can be checked)
_bearer_scheme = HTTPBearer(auto_error=False)


class UserPrincipal(BaseModel):
    id: str
    email: str
    name: str
    workspace_id: str = "ws-001"
    is_admin: bool = True


def get_current_user(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    query_token: Optional[str] = Query(None, alias="token"),
) -> UserPrincipal:
    """
    Validates JWT token from Bearer header or fallback query parameter.
    Raises HTTPException(401) if token is missing, invalid, or expired.
    """
    token = None
    if auth_header and auth_header.credentials:
        token = auth_header.credentials
    elif query_token:
        token = query_token

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide Bearer token header or token query parameter.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload missing subject identifier.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_name = payload.get("name", "Admin")
        user_id = payload.get("uid", "admin-001")
        return UserPrincipal(
            id=user_id,
            email=email,
            name=user_name,
            workspace_id="ws-001",
            is_admin=True,
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_optional_user(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    query_token: Optional[str] = Query(None, alias="token"),
) -> Optional[UserPrincipal]:
    """Permissive dependency: returns UserPrincipal if valid token provided, else None."""
    try:
        return get_current_user(request, auth_header, query_token)
    except HTTPException:
        return None
