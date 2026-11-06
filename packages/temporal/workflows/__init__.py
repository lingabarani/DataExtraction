"""
DataExtraction — Temporal Workflows Package
===========================================
Exports all 6 Enterprise Agent Child Workflows and Master Orchestrator Saga.
"""

try:
    from packages.temporal.workflows.master_orchestrator import (
        MasterOrchestrator,
        MasterOrchestrationWorkflow,
    )
    from packages.temporal.workflows.w1_registry_workflow import Agent1RegistryWorkflow
    from packages.temporal.workflows.w2_geospatial_workflow import Agent2GeospatialWorkflow
    from packages.temporal.workflows.w3_identity_workflow import Agent3IdentityWorkflow
    from packages.temporal.workflows.w4_executive_workflow import Agent4ExecutiveWorkflow
    from packages.temporal.workflows.w5_governance_workflow import Agent5GovernanceWorkflow
    from packages.temporal.workflows.w6_search_sync_workflow import Agent6SearchSyncWorkflow
    from packages.temporal.workflows.federal_ingestion_workflow import FederalIngestionWorkflow
    from packages.temporal.workflows.open_data_ingestion_workflow import OpenDataIngestionWorkflow
    from packages.temporal.workflows.gmaps_extraction_workflow import GMapsExtractionWorkflow
    from packages.temporal.workflows.osm_state_workflow import OSMStateWorkflow, OSMSingleStateWorkflow
    from packages.temporal.workflows.lead_enrichment_workflow import LeadEnrichmentWorkflow
    from packages.temporal.workflows.w7_email_enrichment_workflow import (
        EmailEnrichmentWorkflow,
        Agent7EmailEnrichmentWorkflow,
    )
    from packages.temporal.workflows.dlq_replay_workflow import DLQReplayWorkflow
except ImportError:
    class _MockWF: pass
    MasterOrchestrator = _MockWF  # type: ignore
    MasterOrchestrationWorkflow = _MockWF  # type: ignore
    Agent1RegistryWorkflow = _MockWF  # type: ignore
    Agent2GeospatialWorkflow = _MockWF  # type: ignore
    Agent3IdentityWorkflow = _MockWF  # type: ignore
    Agent4ExecutiveWorkflow = _MockWF  # type: ignore
    Agent5GovernanceWorkflow = _MockWF  # type: ignore
    Agent6SearchSyncWorkflow = _MockWF  # type: ignore
    FederalIngestionWorkflow = _MockWF  # type: ignore
    OpenDataIngestionWorkflow = _MockWF  # type: ignore
    GMapsExtractionWorkflow = _MockWF  # type: ignore
    OSMStateWorkflow = _MockWF  # type: ignore
    OSMSingleStateWorkflow = _MockWF  # type: ignore
    LeadEnrichmentWorkflow = _MockWF  # type: ignore
    EmailEnrichmentWorkflow = _MockWF  # type: ignore
    Agent7EmailEnrichmentWorkflow = _MockWF  # type: ignore
    DLQReplayWorkflow = _MockWF  # type: ignore

__all__ = [
    "MasterOrchestrator",
    "MasterOrchestrationWorkflow",
    "Agent1RegistryWorkflow",
    "Agent2GeospatialWorkflow",
    "Agent3IdentityWorkflow",
    "Agent4ExecutiveWorkflow",
    "Agent5GovernanceWorkflow",
    "Agent6SearchSyncWorkflow",
    "Agent7EmailEnrichmentWorkflow",
    "EmailEnrichmentWorkflow",
    "FederalIngestionWorkflow",
    "OpenDataIngestionWorkflow",
    "GMapsExtractionWorkflow",
    "OSMStateWorkflow",
    "OSMSingleStateWorkflow",
    "LeadEnrichmentWorkflow",
    "DLQReplayWorkflow",
]
