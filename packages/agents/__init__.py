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

from packages.supervisor import tools
from packages.supervisor.base_supervisor import AgentDecision, BaseAgent, BaseSupervisor
from packages.supervisor.quality_monitor import DataQualityAgent, QualityMonitor
from packages.supervisor.resource_monitor import ResourceManagerAgent, ResourceMonitor

__all__ = [
    "AgentDecision",
    "BaseAgent",
    "BaseSupervisor",
    "DataQualityAgent",
    "QualityMonitor",
    "ResourceManagerAgent",
    "ResourceMonitor",
    "tools",
]
