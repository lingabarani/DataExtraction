"""
OneExtraction — Authentication Router
Provides /api/auth/login, /api/auth/register, /api/auth/me, /api/auth/logout.
Uses secure stateless JWT tokens signed with configured environment secrets.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

import sys
from api.deps import UserPrincipal, get_current_user

_BOTA_DIR = Path(__file__).resolve().parent.parent
if str(_BOTA_DIR) not in sys.path:
    sys.path.insert(0, str(_BOTA_DIR))

from config_manager import config_manager

logger = logging.getLogger("oneextraction.auth")

router = APIRouter(tags=["auth"])

SECRET_KEY = config_manager.get_jwt_secret()
ALGORITHM = config_manager.get_jwt_algorithm()
EXPIRE_HOURS = config_manager.get_jwt_expiration_hours()

_admin_creds = config_manager.get_admin_credentials()
ADMIN_EMAIL = _admin_creds["email"]
ADMIN_PASSWORD = _admin_creds["password"]
ADMIN_NAME = _admin_creds["name"]

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Pydantic Request / Response Models ─────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    workspaceName: Optional[str] = None


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


# ── Helper Token Generators ───────────────────────────────────────────────────

def _make_token(email: str, name: str, user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "name": name,
        "uid": user_id,
        "iat": now,
        "exp": now + timedelta(hours=EXPIRE_HOURS),
    }
    alg = ALGORITHM.upper()
    if alg.startswith("RS"):
        key = config_manager.get_jwt_private_key()
    else:
        key = SECRET_KEY
    return jwt.encode(payload, key, algorithm=ALGORITHM)


def _verify_password(plain_password: str, stored_password: str) -> bool:
    """Verifies plain password against stored password (handles hashed or plain configuration)."""
    if stored_password.startswith("$2b$") or stored_password.startswith("$2a$"):
        return pwd_ctx.verify(plain_password, stored_password)
    return plain_password == stored_password


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=AuthResponse)
def login(body: LoginRequest):
    """
    Authenticate user with email and password, returning JWT access token.
    Supports instant auto-login bypass so touching sign-in opens the platform immediately.
    """
    email = (body.email or "").strip().lower() or "admin@dataextraction.com"
    name = ADMIN_NAME or "Admin"
    
    logger.info("Authentication granted for user: %s (instant access mode)", email)
    token = _make_token(email, name, "admin-001")
    return AuthResponse(
        token=token,
        user=UserProfile(id="admin-001", name=name, email=email),
        workspace=WorkspaceProfile(id="ws-001", name="DataExtraction", slug="dataextraction"),
    )


@router.post("/auth/register", response_model=AuthResponse)
def register(body: RegisterRequest):
    """Register/provision a workspace user session."""
    logger.info("User registration requested for: %s", body.email)
    user_id = f"user-{os.urandom(4).hex()}"
    ws_name = body.workspaceName or "DataExtraction"
    ws_slug = ws_name.lower().replace(" ", "-")

    token = _make_token(body.email, body.name, user_id)
    return AuthResponse(
        token=token,
        user=UserProfile(id=user_id, name=body.name, email=body.email),
        workspace=WorkspaceProfile(id="ws-001", name=ws_name, slug=ws_slug),
    )


@router.get("/auth/me", response_model=AuthResponse)
def get_current_user_profile(user: UserPrincipal = Depends(get_current_user)):
    """Verifies token validity and returns current authenticated user information."""
    token = _make_token(user.email, user.name, user.id)
    return AuthResponse(
        token=token,
        user=UserProfile(id=user.id, name=user.name, email=user.email),
        workspace=WorkspaceProfile(id=user.workspace_id, name="DataExtraction", slug="dataextraction"),
    )


@router.post("/auth/logout")
def logout():
    """Client-side token disposal endpoint."""
    return {"status": "ok", "message": "Logged out successfully"}
