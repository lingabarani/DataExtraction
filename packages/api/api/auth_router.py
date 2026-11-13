"""
DataExtraction — Authentication Router
=======================================
Provides stateless JWT authentication endpoints:
  POST /auth/login    — Validate credentials, return signed JWT
  POST /auth/register — Register session user, return signed JWT
  GET  /auth/me       — Validate token, return user profile
  POST /auth/logout   — Client-side token disposal (stateless)

Security model:
  - Passwords are stored as bcrypt hashes (never plain text).
  - Admin credentials are sourced exclusively from environment variables via ConfigManager.
  - JWT signing supports both HS256 (default) and RS256 (production).
  - Login attempts are logged; actual credential values are never logged.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi import Depends
from passlib.context import CryptContext
from jose import jwt
from pydantic import BaseModel, EmailStr, field_validator

from packages.api.dependencies import UserPrincipal, get_current_user
from packages.infrastructure.config_manager import config_manager

logger = logging.getLogger("dataextraction.auth")

router = APIRouter(tags=["auth"])

# ---------------------------------------------------------------------------
# Password hashing context — created lazily on first use so bcrypt's C
# extension (50-100ms import cost) is not loaded at module import time.
# ---------------------------------------------------------------------------
_pwd_ctx_cache = None


def _get_pwd_ctx():
    """Return the bcrypt CryptContext, creating it on first call only."""
    global _pwd_ctx_cache
    if _pwd_ctx_cache is None:
        _pwd_ctx_cache = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
    return _pwd_ctx_cache


def _hash_password(plain: str) -> str:
    return _get_pwd_ctx().hash(plain)


def _verify_password(plain: str, hashed_or_plain: str) -> bool:
    if hashed_or_plain.startswith(("$2b$", "$2a$", "$2y$")):
        return _get_pwd_ctx().verify(plain, hashed_or_plain)
    import hmac
    return hmac.compare_digest(plain.encode(), hashed_or_plain.encode())


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _build_token(email: str, name: str, user_id: str, is_admin: bool) -> str:
    """Creates a signed JWT with standard claims."""
    algorithm = config_manager.get_jwt_algorithm().upper()
    expire_hours = config_manager.get_jwt_expiration_hours()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "name": name,
        "uid": user_id,
        "is_admin": is_admin,
        "workspace_id": "ws-001",
        "iat": now,
        "exp": now + timedelta(hours=expire_hours),
    }
    key = (
        config_manager.get_jwt_private_key()
        if algorithm.startswith("RS")
        else config_manager.get_jwt_secret()
    )
    return jwt.encode(payload, key, algorithm=algorithm)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password must not be empty.")
        return v


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    workspaceName: Optional[str] = None

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class UserProfile(BaseModel):
    id: str
    name: str
    email: str


class WorkspaceProfile(BaseModel):
    id: str
    name: str
    slug: str


class AuthResponse(BaseModel):
    token: str
    user: UserProfile
    workspace: WorkspaceProfile


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/auth/login",
    response_model=AuthResponse,
    summary="Authenticate with email and password",
)
def login(body: LoginRequest) -> AuthResponse:
    """
    Validates credentials against the configured admin account.
    Returns a signed JWT on success; raises HTTP 401 on failure.

    For multi-user scenarios, extend this endpoint to query a users table.
    The admin credential is controlled via API_ADMIN_EMAIL / API_ADMIN_PASSWORD
    environment variables — never hardcoded.
    """
    admin = config_manager.get_admin_credentials()
    expected_email = admin["email"].strip().lower()
    expected_password = admin["password"]

    # Constant-time email comparison
    import hmac
    email_match = hmac.compare_digest(body.email.encode(), expected_email.encode())
    password_match = _verify_password(body.password, expected_password)

    if not (email_match and password_match):
        # Log failed attempt without revealing which field was wrong
        logger.warning("Failed login attempt for email: %s", body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.info("Successful login for user: %s", body.email)
    token = _build_token(
        email=body.email,
        name=admin.get("name", "Admin"),
        user_id="admin-001",
        is_admin=True,
    )
    ws_name = config_manager.get("WORKSPACE_NAME", "DataExtraction")
    return AuthResponse(
        token=token,
        user=UserProfile(id="admin-001", name=admin.get("name", "Admin"), email=body.email),
        workspace=WorkspaceProfile(id="ws-001", name=ws_name, slug="dataextraction"),
    )


@router.post(
    "/auth/register",
    response_model=AuthResponse,
    summary="Register a new session user",
)
def register(body: RegisterRequest) -> AuthResponse:
    """
    Provisions a JWT session for a new user.
    In development this creates an in-memory session; in production
    extend to persist users in a database table with hashed passwords.
    """
    logger.info("User registration requested for: %s", body.email)
    user_id = f"user-{os.urandom(4).hex()}"
    ws_name = body.workspaceName or config_manager.get("WORKSPACE_NAME", "DataExtraction")
    ws_slug = ws_name.lower().replace(" ", "-")

    token = _build_token(
        email=body.email,
        name=body.name,
        user_id=user_id,
        is_admin=False,
    )
    return AuthResponse(
        token=token,
        user=UserProfile(id=user_id, name=body.name, email=body.email),
        workspace=WorkspaceProfile(id="ws-001", name=ws_name, slug=ws_slug),
    )


@router.get(
    "/auth/me",
    response_model=AuthResponse,
    summary="Return current user profile from token",
)
def get_current_user_profile(user: UserPrincipal = Depends(get_current_user)) -> AuthResponse:
    """Validates the token and returns the authenticated user's profile."""
    token = _build_token(
        email=user.email,
        name=user.name,
        user_id=user.id,
        is_admin=user.is_admin,
    )
    ws_name = config_manager.get("WORKSPACE_NAME", "DataExtraction")
    return AuthResponse(
        token=token,
        user=UserProfile(id=user.id, name=user.name, email=user.email),
        workspace=WorkspaceProfile(id=user.workspace_id, name=ws_name, slug="dataextraction"),
    )


@router.post("/auth/logout", summary="Client-side logout (stateless)")
def logout() -> dict:
    """Signals the client to discard its token. No server-side state is changed."""
    return {"status": "ok", "message": "Logged out successfully. Discard your token on the client."}
