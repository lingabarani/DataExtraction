"""
DataExtraction — Infrastructure & Persistence Layer
===================================================
Exports all external adapters, storage bridges, connection poolers, and telemetry sinks:
  - config_manager: Unified settings, secrets resolution, and environment loader
  - db_connector: PostgreSQL connection pooler and transactional context managers
  - dead_letter_queue: Zero-data-loss poison-pill capture with disk fallback
  - kg_ingestion_bridge: Knowledge Graph schema ingestion engine
  - partition_manager: Declarative hash/range table partition maintenance
  - opensearch_cdc_sync: OpenSearch 2.x CDC pipeline and index mapping synchronizer
  - storage_lakehouse: S3/MinIO multi-tier lakehouse client (landing, raw, bronze)
  - structured_logger: Contextual JSON structured logging & audit trail
  - http_client: Enterprise HTTP client with backoff and retry
"""

from packages.infrastructure.config_manager import config_manager, ConfigurationError
from packages.infrastructure.db_connector import (
    get_connection,
    get_cursor,
    get_db_pool_status,
    close_connection_pool,
)
from packages.infrastructure.dead_letter_queue import (
    enqueue_dead_letter,
    get_dead_letter_records,
    get_dead_letter_stats,
    replay_dead_letter,
    discard_dead_letter,
    drain_fallback_to_db,
)
from packages.infrastructure.kg_ingestion_bridge import (
    KnowledgeGraphIngestionBridge,
    kg_bridge,
)
from packages.infrastructure.partition_manager import (
    PartitionManager,
    partition_manager,
)
from packages.infrastructure.opensearch_cdc_sync import (
    OpenSearchCDCSyncClient,
    opensearch_cdc_sync,
)
from packages.infrastructure.storage_lakehouse import (
    LakehouseObservationClient,
    LakehouseStorageError,
    lakehouse_client,
)
from packages.infrastructure.structured_logger import (
    get_structured_logger,
    log_agent_decision,
    get_pipeline_health_metrics,
)
from packages.infrastructure.http_client import (
    get_http_client,
    EnterpriseHttpClient,
)

# Aliases for convenience
KGIngestionBridge = KnowledgeGraphIngestionBridge
OpenSearchCDCSync = OpenSearchCDCSyncClient

__all__ = [
    # Configuration
    "config_manager",
    "ConfigurationError",
    # Database Pool
    "get_connection",
    "get_cursor",
    "get_db_pool_status",
    "close_connection_pool",
    # Dead Letter Queue
    "enqueue_dead_letter",
    "get_dead_letter_records",
    "get_dead_letter_stats",
    "replay_dead_letter",
    "discard_dead_letter",
    "drain_fallback_to_db",
    # Knowledge Graph Bridge
    "KnowledgeGraphIngestionBridge",
    "KGIngestionBridge",
    "kg_bridge",
    # Partition Manager
    "PartitionManager",
    "partition_manager",
    # OpenSearch CDC Sync
    "OpenSearchCDCSyncClient",
    "OpenSearchCDCSync",
    "opensearch_cdc_sync",
    # Lakehouse S3/MinIO
    "LakehouseObservationClient",
    "LakehouseStorageError",
    "lakehouse_client",
    # Observability & Logging
    "get_structured_logger",
    "log_agent_decision",
    "get_pipeline_health_metrics",
    # HTTP Client
    "get_http_client",
    "EnterpriseHttpClient",
]
