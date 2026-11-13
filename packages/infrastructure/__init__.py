"""
DataExtraction — Infrastructure & Persistence Layer
===================================================
Lazily exports all external adapters, storage bridges, connection poolers,
and telemetry sinks via PEP 562 __getattr__ to keep cold-start imports fast.
"""

import importlib

_SYMBOL_MAP = {
    # Configuration
    "config_manager": ("packages.infrastructure.config_manager", "config_manager"),
    "ConfigurationError": ("packages.infrastructure.config_manager", "ConfigurationError"),
    # Database Pool
    "get_connection": ("packages.infrastructure.db_connector", "get_connection"),
    "get_cursor": ("packages.infrastructure.db_connector", "get_cursor"),
    "get_db_pool_status": ("packages.infrastructure.db_connector", "get_db_pool_status"),
    "close_connection_pool": ("packages.infrastructure.db_connector", "close_connection_pool"),
    # Dead Letter Queue
    "enqueue_dead_letter": ("packages.infrastructure.dead_letter_queue", "enqueue_dead_letter"),
    "get_dead_letter_records": ("packages.infrastructure.dead_letter_queue", "get_dead_letter_records"),
    "get_dead_letter_stats": ("packages.infrastructure.dead_letter_queue", "get_dead_letter_stats"),
    "replay_dead_letter": ("packages.infrastructure.dead_letter_queue", "replay_dead_letter"),
    "discard_dead_letter": ("packages.infrastructure.dead_letter_queue", "discard_dead_letter"),
    "drain_fallback_to_db": ("packages.infrastructure.dead_letter_queue", "drain_fallback_to_db"),
    # Knowledge Graph Bridge
    "KnowledgeGraphIngestionBridge": ("packages.infrastructure.kg_ingestion_bridge", "KnowledgeGraphIngestionBridge"),
    "KGIngestionBridge": ("packages.infrastructure.kg_ingestion_bridge", "KnowledgeGraphIngestionBridge"),
    "kg_bridge": ("packages.infrastructure.kg_ingestion_bridge", "kg_bridge"),
    # Partition Manager
    "PartitionManager": ("packages.infrastructure.partition_manager", "PartitionManager"),
    "partition_manager": ("packages.infrastructure.partition_manager", "partition_manager"),
    # OpenSearch CDC Sync
    "OpenSearchCDCSyncClient": ("packages.infrastructure.opensearch_cdc_sync", "OpenSearchCDCSyncClient"),
    "OpenSearchCDCSync": ("packages.infrastructure.opensearch_cdc_sync", "OpenSearchCDCSyncClient"),
    "opensearch_cdc_sync": ("packages.infrastructure.opensearch_cdc_sync", "opensearch_cdc_sync"),
    # Lakehouse S3/MinIO
    "LakehouseObservationClient": ("packages.infrastructure.storage_lakehouse", "LakehouseObservationClient"),
    "LakehouseStorageError": ("packages.infrastructure.storage_lakehouse", "LakehouseStorageError"),
    "lakehouse_client": ("packages.infrastructure.storage_lakehouse", "lakehouse_client"),
    # Observability & Logging
    "get_structured_logger": ("packages.infrastructure.structured_logger", "get_structured_logger"),
    "log_agent_decision": ("packages.infrastructure.structured_logger", "log_agent_decision"),
    "get_pipeline_health_metrics": ("packages.infrastructure.structured_logger", "get_pipeline_health_metrics"),
    # HTTP Client
    "get_http_client": ("packages.infrastructure.http_client", "get_http_client"),
    "EnterpriseHttpClient": ("packages.infrastructure.http_client", "EnterpriseHttpClient"),
}


def __getattr__(name: str):
    if name in _SYMBOL_MAP:
        mod_path, attr = _SYMBOL_MAP[name]
        return getattr(importlib.import_module(mod_path), attr)
    return importlib.import_module(f"packages.infrastructure.{name}")


__all__ = list(_SYMBOL_MAP.keys())
