"""
DataExtraction — Router Auth Dependency Shim
=============================================
Backward-compatibility shim for legacy routers.
Canonical module: packages.api.dependencies
"""
from packages.api.dependencies import (  # noqa: F401
    UserPrincipal,
    get_current_user,
    get_optional_user,
    require_admin,
    _bearer_scheme,
)

# Re-export JWT config keys for any code that accessed them directly
from packages.infrastructure.config_manager import config_manager as _cfg
SECRET_KEY = _cfg.get_jwt_secret()
ALGORITHM = _cfg.get_jwt_algorithm()

__all__ = [
    "UserPrincipal",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "SECRET_KEY",
    "ALGORITHM",
    "_bearer_scheme",
]
