"""
Backward compatibility shim for BaseAgent -> BaseSupervisor.
"""
from packages.supervisor.base_supervisor import BaseSupervisor as BaseAgent, BaseSupervisor, AgentDecision

__all__ = ["BaseAgent", "BaseSupervisor", "AgentDecision"]
