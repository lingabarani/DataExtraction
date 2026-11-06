"""
DataExtraction — API Server (Legacy Compatibility Shim)
=======================================================
This entry point is maintained for backward compatibility. The canonical application
factory and entry point now lives in `packages.api.main.app`.
"""

import warnings
from packages.api.main import app, create_app

warnings.warn(
    "packages.api.api_server is deprecated. Use packages.api.main:app instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["app", "create_app"]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("packages.api.main:app", host="0.0.0.0", port=3001, reload=True)
