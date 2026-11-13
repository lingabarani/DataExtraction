"""
DataExtraction — API Server Entry Point
========================================
Canonical entry point for running the FastAPI application directly (non-Docker).
For Docker deployments use Dockerfile.api which invokes this via uvicorn.

Local dev:  python packages/api/api_server.py          → port 8000
            API_PORT=3001 python packages/api/api_server.py → port 3001
"""

import os
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so all packages.* imports resolve correctly.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.api.main import app, create_app  # noqa: F401

__all__ = ["app", "create_app"]

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("API_PORT", "8000"))
    host = os.getenv("API_HOST", "0.0.0.0")
    reload = os.getenv("ENVIRONMENT", "development").lower() in ("development", "dev")
    workers = int(os.getenv("API_WORKERS", "1")) if not reload else 1

    uvicorn.run(
        "packages.api.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(_REPO_ROOT / "packages" / "api")] if reload else None,
        workers=workers,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
