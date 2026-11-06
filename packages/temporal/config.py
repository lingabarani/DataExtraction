"""
DataExtraction — Temporal Durable Orchestration Layer Configuration
===================================================================
Single source of truth for:
  - Exactly 6 Dedicated Agent Task Queues
  - Cluster host, namespace, and TLS connection parameters
  - Default execution timeouts, retry policies, and worker concurrency limits
"""

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, Any, Optional

try:
    from temporalio.common import RetryPolicy
except ImportError:
    class RetryPolicy:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass

# ── Exactly 6 Standardized Agent Task Queues ──────────────────────────────
QUEUE_REGISTRY: str = os.getenv("QUEUE_REGISTRY", "registry-ingestion-queue")
QUEUE_GEOSPATIAL: str = os.getenv("QUEUE_GEOSPATIAL", "geospatial-domain-queue")
QUEUE_IDENTITY: str = os.getenv("QUEUE_IDENTITY", "identity-clustering-queue")
QUEUE_EXECUTIVE: str = os.getenv("QUEUE_EXECUTIVE", "executive-contact-queue")
QUEUE_GOVERNANCE: str = os.getenv("QUEUE_GOVERNANCE", "governance-quality-queue")
QUEUE_SEARCH: str = os.getenv("QUEUE_SEARCH", "search-persistence-queue")
QUEUE_EMAIL_ENRICHMENT: str = os.getenv("QUEUE_EMAIL_ENRICHMENT", "email-enrichment-queue")

# ── Cluster Settings ──────────────────────────────────────────────────────
TEMPORAL_HOST: str = os.getenv("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE: str = os.getenv("TEMPORAL_NAMESPACE", "dataextraction")
TEMPORAL_TLS_CERT_PATH: Optional[str] = os.getenv("TEMPORAL_TLS_CERT_PATH")
TEMPORAL_TLS_KEY_PATH: Optional[str] = os.getenv("TEMPORAL_TLS_KEY_PATH")
TEMPORAL_TLS_CA_PATH: Optional[str] = os.getenv("TEMPORAL_TLS_CA_PATH")

# ── Activity & Workflow Timeouts ──────────────────────────────────────────
SCRAPER_ACTIVITY_TIMEOUT = timedelta(seconds=int(os.getenv("FEDERAL_SCRAPER_TIMEOUT_SECONDS", "7200")))
STANDARD_ACTIVITY_TIMEOUT = timedelta(hours=2)
EXTENDED_ACTIVITY_TIMEOUT = timedelta(hours=4)
SHORT_ACTIVITY_TIMEOUT = timedelta(minutes=15)
WORKFLOW_EXECUTION_TIMEOUT = timedelta(days=7)

# ── Standardized Retry Policies ───────────────────────────────────────────
DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=5,
    non_retryable_error_types=["PermissionError", "ValueError"],
)

REGISTRY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError", "ConfigurationError"],
)

IDENTITY_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError"],
)

GEOSPATIAL_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError"],
)

EXECUTIVE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=15),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=15),
    maximum_attempts=3,
    non_retryable_error_types=["PermissionError"],
)

GOVERNANCE_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=3,
)

SEARCH_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=5,
)

EMAIL_ENRICHMENT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=4,
    non_retryable_error_types=["PermissionError", "ValueError"],
)

# ── Worker Concurrency Defaults ───────────────────────────────────────────
WORKER_MAX_ACTIVITIES = {
    QUEUE_REGISTRY: int(os.getenv("REGISTRY_WORKER_MAX_CONCURRENT_ACTIVITIES", "6")),
    QUEUE_GEOSPATIAL: int(os.getenv("GEOSPATIAL_WORKER_MAX_CONCURRENT_ACTIVITIES", "10")),
    QUEUE_IDENTITY: int(os.getenv("IDENTITY_WORKER_MAX_CONCURRENT_ACTIVITIES", "8")),
    QUEUE_EXECUTIVE: int(os.getenv("EXECUTIVE_WORKER_MAX_CONCURRENT_ACTIVITIES", "8")),
    QUEUE_GOVERNANCE: int(os.getenv("GOVERNANCE_WORKER_MAX_CONCURRENT_ACTIVITIES", "8")),
    QUEUE_SEARCH: int(os.getenv("SEARCH_WORKER_MAX_CONCURRENT_ACTIVITIES", "12")),
    QUEUE_EMAIL_ENRICHMENT: int(os.getenv("EMAIL_ENRICHMENT_WORKER_MAX_CONCURRENT_ACTIVITIES", "10")),
}


def get_task_queues() -> Dict[str, str]:
    """Returns mapping of all agent roles to their designated task queues."""
    return {
        "agent_1_registry": QUEUE_REGISTRY,
        "agent_2_geospatial": QUEUE_GEOSPATIAL,
        "agent_3_identity": QUEUE_IDENTITY,
        "agent_4_executive": QUEUE_EXECUTIVE,
        "agent_5_governance": QUEUE_GOVERNANCE,
        "agent_6_search": QUEUE_SEARCH,
        "agent_7_email_enrichment": QUEUE_EMAIL_ENRICHMENT,
    }


__all__ = [
    "QUEUE_REGISTRY",
    "QUEUE_GEOSPATIAL",
    "QUEUE_IDENTITY",
    "QUEUE_EXECUTIVE",
    "QUEUE_GOVERNANCE",
    "QUEUE_SEARCH",
    "QUEUE_EMAIL_ENRICHMENT",
    "TEMPORAL_HOST",
    "TEMPORAL_NAMESPACE",
    "TEMPORAL_TLS_CERT_PATH",
    "TEMPORAL_TLS_KEY_PATH",
    "TEMPORAL_TLS_CA_PATH",
    "SCRAPER_ACTIVITY_TIMEOUT",
    "STANDARD_ACTIVITY_TIMEOUT",
    "EXTENDED_ACTIVITY_TIMEOUT",
    "SHORT_ACTIVITY_TIMEOUT",
    "WORKFLOW_EXECUTION_TIMEOUT",
    "DEFAULT_RETRY_POLICY",
    "REGISTRY_RETRY_POLICY",
    "IDENTITY_RETRY_POLICY",
    "GEOSPATIAL_RETRY_POLICY",
    "EXECUTIVE_RETRY_POLICY",
    "GOVERNANCE_RETRY_POLICY",
    "SEARCH_RETRY_POLICY",
    "EMAIL_ENRICHMENT_RETRY_POLICY",
    "WORKER_MAX_ACTIVITIES",
    "get_task_queues",
]

