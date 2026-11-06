"""
DataExtraction — API Package
============================
Exports FastAPI application instance and factory.
"""

import sys

# Ensure legacy module references like `api.dlq_router` resolve to canonical modules
try:
    from packages.api.routers import dlq_router
    sys.modules["api.dlq_router"] = dlq_router
except Exception:
    pass

def __getattr__(name: str):
    if name in ("app", "create_app"):
        from packages.api.main import app, create_app
        return app if name == "app" else create_app
    if name == "dlq_router":
        return sys.modules.get("api.dlq_router")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["app", "create_app"]
