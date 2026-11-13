"""
Backward compatibility shim for BaseAgent -> BaseSupervisor.
"""
from packages.supervisor.base_supervisor import AgentDecision, BaseSupervisor
from packages.supervisor.base_supervisor import BaseSupervisor as BaseAgent

__all__ = ["AgentDecision", "BaseAgent", "BaseSupervisor"]
