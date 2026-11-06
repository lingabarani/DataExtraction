"""
DataExtraction — API Dependency Re-export
=========================================
Re-exports dependencies from packages.api.routers.deps.
"""

from packages.api.routers.deps import (
    UserPrincipal,
    get_current_user,
    get_optional_user,
    SECRET_KEY,
    ALGORITHM,
    _bearer_scheme,
)

__all__ = [
    "UserPrincipal",
    "get_current_user",
    "get_optional_user",
    "SECRET_KEY",
    "ALGORITHM",
    "_bearer_scheme",
]

