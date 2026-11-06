"""
DataExtraction — Master Orchestration Workflow (Legacy Shim)
=============================================================
This module is maintained for backward compatibility. The canonical implementation
now lives in `packages.temporal.workflows.master_orchestrator.MasterOrchestrator`.
"""

import warnings
from packages.temporal.workflows.master_orchestrator import (
    MasterOrchestrator,
    MasterOrchestrationWorkflow,
)

warnings.warn(
    "packages.temporal.workflows.master_orchestration_workflow is deprecated and will be removed "
    "in a future release. Import MasterOrchestrator from packages.temporal.workflows.master_orchestrator instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["MasterOrchestrationWorkflow", "MasterOrchestrator"]
