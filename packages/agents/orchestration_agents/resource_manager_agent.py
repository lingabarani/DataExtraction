"""
Backward compatibility shim for ResourceManagerAgent -> ResourceMonitor.
"""
from packages.supervisor.resource_monitor import ResourceMonitor as ResourceManagerAgent, ResourceMonitor

__all__ = ["ResourceManagerAgent", "ResourceMonitor"]
