"""
Backward compatibility shim for DataQualityAgent -> QualityMonitor.
"""
from packages.supervisor.quality_monitor import QualityMonitor as DataQualityAgent, QualityMonitor

__all__ = ["DataQualityAgent", "QualityMonitor"]
