"""
DataExtraction — Auth Dependency Re-export Shim
================================================
Backward-compatibility shim. All new code must import directly from:
    packages.api.dependencies

This module simply re-exports the canonical symbols so legacy code that
imports `from packages.api.deps import ...` continues to work.
"""
from packages.api.dependencies import (  # noqa: F401
    UserPrincipal,
    get_current_user,
    get_optional_user,
    require_admin,
    get_db,
)

__all__ = [
    "UserPrincipal",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "get_db",
]
