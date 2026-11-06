"""
DataExtraction — Legacy Agents Shim (Deprecated)
================================================
This package has been relocated to `packages.supervisor` to eliminate polysemy.
All symbols are re-exported here for strict backward compatibility.
"""

import warnings

warnings.warn(
    "packages.agents has been renamed to packages.supervisor. "
    "Please update your imports to packages.supervisor.",
    DeprecationWarning,
    stacklevel=2,
)

from packages.supervisor.base_supervisor import BaseSupervisor, AgentDecision, BaseAgent
from packages.supervisor.resource_monitor import ResourceMonitor, ResourceManagerAgent
from packages.supervisor.quality_monitor import QualityMonitor, DataQualityAgent
from packages.supervisor import tools

__all__ = [
    "BaseSupervisor",
    "AgentDecision",
    "BaseAgent",
    "ResourceMonitor",
    "ResourceManagerAgent",
    "QualityMonitor",
    "DataQualityAgent",
    "tools",
]
