"""
DataExtraction — Email Enrichment API Router
=============================================
Endpoints for managing and triggering email discovery and verification:
  - POST /api/enrichment/email/jobs          -> Trigger batch discovery saga
  - GET  /api/enrichment/email/jobs/{job_id} -> Query job execution metrics
  - GET  /api/enrichment/email/jobs          -> List recent jobs with pagination
  - GET  /api/enrichment/email/audit/{id}    -> Retrieve audit and handshake traces
  - GET  /api/enrichment/email/results/{id}  -> Retrieve latest enrichment result
  - POST /api/enrichment/email/probe-single  -> Live interactive crawl & SMTP probe
"""

import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from packages.api.dependencies import get_current_user, require_admin, UserPrincipal
from packages.domain.email_enricher import email_enrichment_engine
from packages.infrastructure.email_enrichment_repository import email_enrichment_repo
from packages.infrastructure.structured_logger import get_structured_logger
from packages.scrapers.web.email_crawler import AsyncEmailWebCrawler
from packages.temporal.client import get_temporal_client
from packages.temporal.config import QUEUE_EMAIL_ENRICHMENT
try:
    from packages.temporal.workflows.w7_email_enrichment_workflow import EmailEnrichmentWorkflow
except ImportError:
    class EmailEnrichmentWorkflow:  # type: ignore
        run = "EmailEnrichmentWorkflow"

logger = get_structured_logger("api.enrichment_router")

router = APIRouter(prefix="/api/enrichment", tags=["Email Enrichment"])


# ── Request / Response Models ─────────────────────────────────────────────────

class StartEmailEnrichmentJobRequest(BaseModel):
    batch_size: int = Field(default=200, ge=1, le=2000, description="Records per activity batch")
    max_records: int = Field(default=5000, ge=1, le=50000, description="Max total records to enrich")
    probe_smtp: bool = Field(default=True, description="Execute active non-intrusive SMTP RCPT TO probe")
    target_table: str = Field(default="companies", description="Target database table")
    workflow_id: Optional[str] = Field(default=None, description="Custom Temporal workflow ID")


class ProbeSingleDomainRequest(BaseModel):
    domain: str = Field(..., description="Target apex domain (e.g. acme.com)")
    website_url: Optional[str] = Field(default=None, description="Optional target homepage URL")
    probe_smtp: bool = Field(default=True, description="Whether to execute active SMTP verification")


class ProbeSingleDomainResponse(BaseModel):
    domain: str
    primary_email: Optional[str] = None
    all_emails: List[str] = Field(default_factory=list)
    discovery_source: str
    deliverability_status: str
    confidence_score: float
    is_catchall: bool
    tech_stack: List[str] = Field(default_factory=list)
    cms_detected: Optional[str] = None
    ssl_valid: bool = False
    site_speed_ms: Optional[int] = None
    http_status_code: Optional[int] = None
    duration_ms: float


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/email/jobs", status_code=status.HTTP_202_ACCEPTED)
async def trigger_email_enrichment_job(
    payload: StartEmailEnrichmentJobRequest,
    current_user: UserPrincipal = Depends(require_admin),
) -> Dict[str, Any]:
    """
    Triggers an asynchronous post-deduplication email enrichment saga via Temporal.
    Enforces that only canonical entities (is_canonical=TRUE) without emails are processed.
    """
    wf_id = payload.workflow_id or f"email-enrichment-{int(time.time())}"
    config = {
        "batch_size": payload.batch_size,
        "max_records": payload.max_records,
        "probe_smtp": payload.probe_smtp,
        "target_table": payload.target_table,
        "verify_dedup_completed": True,
    }

    try:
        client = await get_temporal_client()
        handle = await client.start_workflow(
            EmailEnrichmentWorkflow.run,
            args=[config],
            id=wf_id,
            task_queue=QUEUE_EMAIL_ENRICHMENT,
        )
        logger.info(
            "User %s initiated email enrichment saga (id=%s, queue=%s)",
            current_user.email, handle.id, QUEUE_EMAIL_ENRICHMENT,
        )
        return {
            "status": "ACCEPTED",
            "workflow_id": handle.id,
            "run_id": handle.result_run_id,
            "task_queue": QUEUE_EMAIL_ENRICHMENT,
            "message": "Email enrichment workflow initiated on post-dedup canonical entities",
        }
    except Exception as exc:
        logger.error("Failed to start email enrichment workflow: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initiate email enrichment saga: {str(exc)}",
        )


@router.get("/email/jobs/{job_id}")
async def get_email_enrichment_job(
    job_id: str,
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieves real-time execution status and progress for a specific enrichment job."""
    job = email_enrichment_repo.get_job_by_id(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Enrichment job '{job_id}' not found",
        )
    return job


@router.get("/email/jobs")
async def list_email_enrichment_jobs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: UserPrincipal = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Lists recent enrichment jobs with pagination and status filtering."""
    return email_enrichment_repo.get_recent_jobs(
        limit=limit,
        offset=offset,
        status_filter=status_filter,
    )


@router.get("/email/audit/{company_id}")
async def get_email_discovery_audit(
    company_id: str,
    limit: int = Query(100, ge=1, le=500),
    current_user: UserPrincipal = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Retrieves full crawl and SMTP handshake audit traces for a specific organization."""
    return email_enrichment_repo.get_audit_for_company(company_id=company_id, limit=limit)


@router.get("/email/results/{company_id}")
async def get_email_enrichment_result(
    company_id: str,
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retrieves latest consolidated email enrichment result for a company."""
    result = email_enrichment_repo.get_enrichment_result_by_company_id(company_id=company_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Enrichment result for company '{company_id}' not found",
        )
    return result


@router.post("/email/probe-single", response_model=ProbeSingleDomainResponse)
async def probe_single_domain(
    payload: ProbeSingleDomainRequest,
    current_user: UserPrincipal = Depends(get_current_user),
) -> ProbeSingleDomainResponse:
    """
    Live on-demand probe for a single website or domain.
    Executes real-time contact page crawling, obfuscation decoding, and SMTP verification.
    """
    start_time = time.time()
    domain = payload.domain.strip().lower()
    url = payload.website_url or f"https://{domain}"

    try:
        crawler = AsyncEmailWebCrawler()
        crawl_results = await crawler.crawl_site(url)

        res = email_enrichment_engine.process_discovered_emails(
            company_id=f"probe-{domain}",
            domain=domain,
            crawl_results=crawl_results,
            probe_smtp=payload.probe_smtp,
        )

        duration_ms = (time.time() - start_time) * 1000
        return ProbeSingleDomainResponse(
            domain=domain,
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
            duration_ms=round(duration_ms, 2),
        )
    except Exception as exc:
        logger.error("Live probe failed for domain %s: %s", domain, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Single domain probe failed: {str(exc)}",
        )

