"""
DataExtraction — API Package
============================
Exports FastAPI application instance and factory lazily to keep package imports fast.
"""

import importlib
import sys


def __getattr__(name: str):
    if name in ("app", "create_app"):
        from packages.api.main import app, create_app
        return app if name == "app" else create_app
    if name == "dlq_router":
        mod = importlib.import_module("packages.api.routers.dlq_router")
        sys.modules.setdefault("api.dlq_router", mod)
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["app", "create_app"]
