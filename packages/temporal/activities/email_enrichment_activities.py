"""
DataExtraction — Temporal Activities for Email Discovery & Verification
========================================================================
Implements durable activities for:
  - Creating and tracking enrichment jobs
  - Fetching canonical pending organizations (keyset pagination)
  - Batch web scraping, obfuscation decoding, and SMTP mailbox probing
  - Transactional persistence and audit logging
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from temporalio import activity

from packages.domain.email_enricher import email_enrichment_engine
from packages.infrastructure.email_enrichment_repository import email_enrichment_repo
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("temporal.activities.email_enrichment")


@activity.defn(name="create_enrichment_job_activity")
async def create_enrichment_job_activity(
    job_type: str = "POST_DEDUP_CANONICAL",
    target_table: str = "staging_dataextraction.working_organizations",
    batch_size: int = 500,
    max_concurrency: int = 50,
) -> str:
    """Initializes job record in email_enrichment_jobs and returns generated job_id."""
    activity.logger.info("Starting enrichment job (type=%s, table=%s, batch=%d)", job_type, target_table, batch_size)
    job_id = email_enrichment_repo.create_job(
        job_type=job_type,
        target_table=target_table,
        batch_size=batch_size,
        max_concurrency=max_concurrency,
        metadata={"temporal_activity_id": activity.info().activity_id},
    )
    return job_id


@activity.defn(name="fetch_pending_enrichment_batch_activity")
async def fetch_pending_enrichment_batch_activity(
    last_id: Optional[str] = None,
    limit: int = 500,
    target_table: str = "staging_dataextraction.working_organizations",
) -> List[Dict[str, Any]]:
    """Fetches next keyset chunk of canonical companies requiring email discovery."""
    activity.logger.info("Fetching pending canonical companies (table=%s, last_id=%s, limit=%d)", target_table, last_id, limit)
    records = email_enrichment_repo.get_pending_canonical_companies(last_id=last_id, limit=limit, target_table=target_table)
    activity.logger.info("Fetched %d companies for enrichment", len(records))
    return records


@activity.defn(name="enrich_email_batch_activity")
async def enrich_email_batch_activity(
    companies: List[Dict[str, Any]],
    job_id: Optional[str] = None,
    probe_smtp: bool = True,
) -> Dict[str, Any]:
    """
    Executes async web crawl, domain profiling, and SMTP probing across batch.
    Persists outcomes transactionally and records audit telemetry.
    """
    if not companies:
        return {"processed": 0, "successful": 0, "failed": 0, "last_id": None}

    activity.logger.info("Executing email enrichment for batch of %d companies", len(companies))
    results = await email_enrichment_engine.enrich_companies_batch(companies, probe_smtp=probe_smtp)

    successful = 0
    failed = 0
    last_id = companies[-1]["id"] if companies else None

    for res in results:
        try:
            # 1. Save enrichment result and update company record
            email_enrichment_repo.save_enrichment_result(
                company_id=res.company_id,
                domain=res.domain,
                primary_email=res.primary_email,
                all_emails=res.all_emails,
                discovery_source=res.discovery_source,
                deliverability_status=res.deliverability_status,
                confidence_score=res.confidence_score,
                is_catchall=res.is_catchall,
                tech_stack=res.tech_stack,
                cms_detected=res.cms_detected,
                ssl_valid=res.ssl_valid,
                site_speed_ms=res.site_speed_ms,
                http_status_code=res.http_status_code,
                job_id=job_id,
            )

            # 2. Record audit probe trace
            email_enrichment_repo.record_audit_probe(
                target_domain=res.domain,
                probed_email=res.primary_email,
                probe_type="BATCH_DISCOVERY",
                duration_ms=float(res.site_speed_ms or 0),
                is_success=bool(res.primary_email and res.deliverability_status in ("DELIVERABLE", "MX_CONFIRMED")),
                company_id=res.company_id,
                job_id=job_id,
            )

            if res.primary_email and res.deliverability_status in ("DELIVERABLE", "MX_CONFIRMED", "RISKY"):
                successful += 1
            else:
                failed += 1

        except Exception as exc:
            failed += 1
            activity.logger.warning("Error saving enrichment result for company %s: %s", res.company_id, exc)

    # 3. Update job checkpoint
    if job_id:
        email_enrichment_repo.update_job_progress(
            job_id=job_id,
            processed_delta=len(companies),
            success_delta=successful,
            failed_delta=failed,
            last_processed_id=last_id,
        )

    return {
        "processed": len(companies),
        "successful": successful,
        "failed": failed,
        "last_id": last_id,
    }


@activity.defn(name="finalize_enrichment_job_activity")
async def finalize_enrichment_job_activity(
    job_id: str,
    error_message: Optional[str] = None,
) -> None:
    """Marks the enrichment job as COMPLETED or FAILED."""
    activity.logger.info("Finalizing enrichment job %s (error=%s)", job_id, error_message)
    email_enrichment_repo.complete_job(job_id=job_id, error_message=error_message)

