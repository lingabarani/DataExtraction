"""
Base Source Adapter Interface for Discovery Engine.
All source adapters implement an async generator yielding SourceResults within a time budget.
"""

from __future__ import annotations

import abc
import logging
import time
from typing import Any, AsyncIterator, Dict

from packages.discovery.models import Budget, SearchIntent, SourceResult, SourceStatus

logger = logging.getLogger("discovery.source")


class SourceAdapter(abc.ABC):
    """Abstract base class for all discovery sources."""

    def __init__(
        self,
        name: str,
        source_type: str = "generic",
        weight: float = 1.0,
    ) -> None:
        self.name = name
        self.source_type = source_type
        self.weight = weight

    @abc.abstractmethod
    async def _execute_search(
        self,
        intent: SearchIntent,
        budget: Budget,
    ) -> AsyncIterator[SourceResult]:
        """Internal search generator to be overridden by subclasses."""
        pass

    async def search(
        self,
        intent: SearchIntent,
        budget: Budget,
    ) -> AsyncIterator[SourceResult]:
        """
        Public search entry point with exception containment, timing, and budget enforcement.
        Never raises unhandled exceptions to the orchestrator.
        """
        start_time = time.monotonic()
        if budget.is_expired():
            logger.info("Source %s skipped: budget expired", self.name)
            yield SourceResult(
                source=self.name,
                status=SourceStatus(
                    source=self.name,
                    status="empty",
                    count=0,
                    elapsed_ms=int((time.monotonic() - start_time) * 1000),
                    message="Skipped: Search budget expired",
                ),
            )
            return

        try:
            async for result in self._execute_search(intent, budget):
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                result.status.elapsed_ms = elapsed_ms
                yield result
                if budget.is_expired():
                    logger.info("Source %s cut off: budget expired", self.name)
                    break
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error("Source %s execution failed: %s", self.name, exc, exc_info=True)
            yield SourceResult(
                source=self.name,
                status=SourceStatus(
                    source=self.name,
                    status="error",
                    count=0,
                    elapsed_ms=elapsed_ms,
                    message=f"{type(exc).__name__}: {str(exc)}",
                ),
            )

    async def healthcheck(self) -> Dict[str, Any]:
        """Verify connectivity / operational status for this adapter."""
        return {
            "source": self.name,
            "status": "healthy",
            "type": self.source_type,
        }
