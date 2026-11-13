"""
DataExtraction — Temporal Client Factory & Connection Pool
========================================================
Single source of truth for creating and caching Temporal clients across
workers, API routers, and agent code with circuit breaker and health probing.
"""

import asyncio
import logging
import os
import socket
from typing import Optional
try:
    from temporalio.client import Client, TLSConfig
except ImportError:
    Client = object  # type: ignore
    TLSConfig = object  # type: ignore

logger = logging.getLogger("dataextraction.temporal.client")

_CACHED_CLIENT: Optional[Client] = None


def _is_port_open(host_str: str, timeout: float = 0.2) -> bool:
    """Fast non-blocking TCP socket probe avoiding Windows SYN retries and DNS hangs."""
    try:
        parts = host_str.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 7233
        # Normalize localhost to numeric IP to prevent Windows NetBIOS/DNS hang in sandbox
        if host in ("localhost", "0.0.0.0"):
            host = "127.0.0.1"
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        res = s.connect_ex((host, port))
        s.close()
        return res == 0
    except (socket.timeout, ConnectionRefusedError, OSError, PermissionError, Exception):
        return False


async def get_temporal_client(timeout_seconds: float = 3.0) -> Client:
    """
    Create or retrieve a cached, connected Temporal client.

    Reads configuration from environment variables:
      TEMPORAL_HOST      — e.g., "localhost:7233" or "your-ns.tmprl.cloud:7233"
      TEMPORAL_NAMESPACE — e.g., "dataextraction"
      TEMPORAL_TLS_CERT_PATH / TEMPORAL_TLS_KEY_PATH — optional TLS (production)
    """
    global _CACHED_CLIENT
    if _CACHED_CLIENT is not None:
        return _CACHED_CLIENT

    host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    namespace = os.getenv("TEMPORAL_NAMESPACE", "dataextraction")
    tls_cert = os.getenv("TEMPORAL_TLS_CERT_PATH")
    tls_key = os.getenv("TEMPORAL_TLS_KEY_PATH")
    tls_ca = os.getenv("TEMPORAL_TLS_CA_PATH")

    if Client is object or not hasattr(Client, "connect"):
        raise ConnectionError("temporalio client library is not available")

    # Fast pre-flight socket probe avoids thread-locking inside gRPC channel construction
    if not _is_port_open(host, timeout=min(timeout_seconds, 0.25)):
        raise ConnectionError(f"Temporal server at {host} is not reachable (TCP port closed)")

    tls: bool | TLSConfig = False
    if tls_cert and tls_key and os.path.exists(tls_cert) and os.path.exists(tls_key):
        tls = TLSConfig(
            client_cert=open(tls_cert, "rb").read(),
            client_private_key=open(tls_key, "rb").read(),
            server_root_ca_cert=open(tls_ca, "rb").read() if tls_ca and os.path.exists(tls_ca) else None,
        )
        logger.info("Temporal TLS enabled (cert=%s)", tls_cert)

    try:
        client = await asyncio.wait_for(
            Client.connect(host, namespace=namespace, tls=tls),
            timeout=timeout_seconds,
        )
        logger.info("Temporal client connected: host=%s namespace=%s", host, namespace)
        _CACHED_CLIENT = client
        return client
    except Exception as err:
        if "not found" in str(err).lower() and namespace != "default":
            logger.warning("Namespace '%s' not found on Temporal cluster. Falling back to 'default'.", namespace)
            try:
                client = await asyncio.wait_for(
                    Client.connect(host, namespace="default", tls=tls),
                    timeout=timeout_seconds,
                )
                logger.info("Temporal client connected to fallback namespace 'default' on host=%s", host)
                _CACHED_CLIENT = client
                return client
            except Exception:
                pass
        logger.warning("Failed to connect to Temporal cluster (%s:%s): %s", host, namespace, err)
        raise


async def is_temporal_healthy(timeout_seconds: float = 1.0) -> bool:
    """Health check probe for Temporal connectivity with fast pre-flight socket validation."""
    if Client is object or not hasattr(Client, "connect"):
        return False
    host = os.getenv("TEMPORAL_HOST", "localhost:7233")
    if not _is_port_open(host, timeout=min(timeout_seconds, 0.2)):
        return False
    try:
        await get_temporal_client(timeout_seconds=timeout_seconds)
        return True
    except Exception:
        return False


def reset_temporal_client() -> None:
    """Clear cached client upon connection failure to allow reconnect."""
    global _CACHED_CLIENT
    _CACHED_CLIENT = None
