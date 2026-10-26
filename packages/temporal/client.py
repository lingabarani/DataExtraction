"""
DataExtraction — Temporal Client Factory
========================================
Single source of truth for creating Temporal clients across workers,
API routers, and agent code.
"""

import logging
import os
from functools import lru_cache

from temporalio.client import Client, TLSConfig

logger = logging.getLogger("dataextraction.temporal.client")


async def get_temporal_client() -> Client:
    """
    Create and return a connected Temporal client.

    Reads configuration from environment variables:
      TEMPORAL_HOST      — e.g., "localhost:7233" or "your-ns.tmprl.cloud:7233"
      TEMPORAL_NAMESPACE — e.g., "dataextraction"
      TEMPORAL_TLS_CERT_PATH / TEMPORAL_TLS_KEY_PATH — optional TLS (production)
    """
    host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "dataextraction")
    tls_cert = os.getenv("TEMPORAL_TLS_CERT_PATH")
    tls_key = os.getenv("TEMPORAL_TLS_KEY_PATH")
    tls_ca = os.getenv("TEMPORAL_TLS_CA_PATH")

    tls: bool | TLSConfig = False
    if tls_cert and tls_key:
        tls = TLSConfig(
            client_cert=open(tls_cert, "rb").read(),
            client_private_key=open(tls_key, "rb").read(),
            server_root_ca_cert=open(tls_ca, "rb").read() if tls_ca else None,
        )
        logger.info("Temporal TLS enabled (cert=%s)", tls_cert)

    client = await Client.connect(host, namespace=namespace, tls=tls)
    logger.info("Temporal client connected: host=%s namespace=%s", host, namespace)
    return client
