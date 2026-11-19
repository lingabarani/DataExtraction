"""
DataExtraction — Agent 8: Website Intelligence & Enrichment Workflow
===================================================================
Queue: website-intelligence-queue
Worker: packages.temporal.workers.worker_website_intelligence

Orchestrates official website intelligence & company enrichment:
- Deduplicates and verifies website candidates from Agent 1 & Agent 2
- Enforces strict SSRF protection, DNS validation, and SSL reachability
- Crawls internal pages (/about, /team, /leadership, /services, /contact) respecting robots.txt
- Audits and cross-verifies existing data against website evidence (tracking VERIFIED, CONFLICT, UNVERIFIED, NEW_DISCOVERY)
- Discovers enterprise technology stack signatures (CMS, Analytics, Hosting, Frameworks)
- Extracts C-suite executives, senior leadership, and corporate contact channels
- Preserves complete source provenance and field-level confidence
- Signals: pause, resume, cancel_domain
- Queries: get_status
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.website_intelligence_activities import (
        run_website_candidate_resolution_activity,
        run_website_verification_activity,
        run_website_crawl_and_enrichment_activity,
    )
    from packages.temporal.config import (
        QUEUE_WEBSITE_INTELLIGENCE,
        WEBSITE_INTELLIGENCE_RETRY_POLICY,
    )

TASK_QUEUE = QUEUE_WEBSITE_INTELLIGENCE


@workflow.defn(name="Agent8WebsiteIntelligenceWorkflow")
class Agent8WebsiteIntelligenceWorkflow:
    """
    Agent 8 Workflow: Website Intelligence & Enrichment.
    Executes between Phase 2 (Geospatial) and Phase 3 (Identity Resolution).
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._paused: bool = False
        self._cancelled_domains: set = set()
        self._results: Dict[str, Any] = {}

    @staticmethod
    def _safe_now() -> datetime:
        try:
            return workflow.now()
        except Exception:
            return datetime.now(timezone.utc)

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 8] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 8] Resume signal received")
        self._paused = False

    @workflow.signal
    def cancel_domain(self, domain: str) -> None:
        workflow.logger.warning("[Agent 8] Cancel domain signal received: %s", domain)
        self._cancelled_domains.add(domain.lower().strip())

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 8 - Website Intelligence & Enrichment",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "paused": self._paused,
            "cancelled_domains": list(self._cancelled_domains),
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        config = config or {}
        started_at = self._safe_now()
        self._status = "RUNNING"
        wf_id = workflow.info().workflow_id
        workflow.logger.info("[Agent 8] Website Intelligence started on queue: %s", TASK_QUEUE)

        candidate_limit = int(config.get("candidate_limit") or config.get("data_count") or 50)
        max_crawl_pages = int(config.get("max_crawl_pages") or 6)

        await workflow.wait_condition(lambda: not self._paused)

        # ── Step 1: Candidate Domain Resolution ──────────────────────────────
        try:
            candidates: List[Dict[str, Any]] = await workflow.execute_activity(
                run_website_candidate_resolution_activity,
                args=[wf_id, candidate_limit],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=WEBSITE_INTELLIGENCE_RETRY_POLICY,
            )
            self._results["candidates_found"] = len(candidates)
        except Exception as exc:
            workflow.logger.error("[Agent 8] Candidate resolution failed: %s", exc)
            self._status = "FAILED"
            return {
                "status": "FAILED",
                "error": f"Candidate resolution failed: {exc}",
                "domains_verified": 0,
                "domains_crawled": 0,
                "executives_found": 0,
                "duration_seconds": 0.0,
            }

        # Filter out cancelled domains
        active_candidates = [
            c for c in candidates
            if c.get("domain") and c["domain"].lower() not in self._cancelled_domains
        ]

        if not active_candidates:
            self._status = "SKIPPED"
            return {
                "status": "SKIPPED",
                "reason": "No active website candidates found",
                "domains_verified": 0,
                "domains_crawled": 0,
                "executives_found": 0,
                "duration_seconds": 0.0,
            }

        await workflow.wait_condition(lambda: not self._paused)

        # ── Step 2: SSRF & Reachability Verification ─────────────────────────
        try:
            verified_candidates: List[Dict[str, Any]] = await workflow.execute_activity(
                run_website_verification_activity,
                args=[active_candidates],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=WEBSITE_INTELLIGENCE_RETRY_POLICY,
            )
            self._results["domains_verified"] = len(verified_candidates)
        except Exception as exc:
            workflow.logger.error("[Agent 8] Verification step failed: %s", exc)
            verified_candidates = []
            self._results["domains_verified"] = 0

        await workflow.wait_condition(lambda: not self._paused)

        # ── Step 3: Multi-Page Crawl & Intelligence Enrichment ───────────────
        enrichment_stats: Dict[str, Any] = {}
        if verified_candidates:
            try:
                enrichment_stats = await workflow.execute_activity(
                    run_website_crawl_and_enrichment_activity,
                    args=[verified_candidates, wf_id, max_crawl_pages],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=WEBSITE_INTELLIGENCE_RETRY_POLICY,
                )
                self._results["enrichment"] = enrichment_stats
            except Exception as exc:
                workflow.logger.error("[Agent 8] Crawl and enrichment step failed: %s", exc)
                self._results["enrichment"] = {"status": "FAILED", "error": str(exc)}

        duration_seconds = round(max((self._safe_now() - started_at).total_seconds(), 0.0), 2)
        self._status = "COMPLETED"

        return {
            "status": self._status,
            "candidates_resolved": len(candidates),
            "domains_verified": len(verified_candidates),
            "domains_crawled": enrichment_stats.get("domains_crawled", 0),
            "contacts_found": enrichment_stats.get("contacts_saved", 0),
            "executives_found": enrichment_stats.get("executives_saved", 0),
            "tech_stack_detected": enrichment_stats.get("tech_stack_saved", 0),
            "cross_verifications_recorded": enrichment_stats.get("cross_verifications_saved", 0),
            "duration_seconds": duration_seconds,
            "results": self._results,
        }
