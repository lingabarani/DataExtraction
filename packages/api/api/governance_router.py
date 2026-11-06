"""
DataExtraction — Governance & Promotion Gate API Router
========================================================
Prefix: /api/governance
Tags: Governance, Quality & Promotion Gate

Provides operational telemetry, metrics, and interactive control endpoints for:
  1. Pre-Master Working Layer vs Master Vault Golden Records metrics
  2. Promotion Gate trigger & threshold configuration
  3. Autonomous Freshness Decay & SLA Revalidation sweep execution
  4. Quarantined records inspection and DLQ health
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from packages.api.dependencies import get_current_user, UserPrincipal
from packages.infrastructure.db_connector import get_connection, _release_connection
from packages.infrastructure.structured_logger import get_structured_logger
from packages.temporal.activities.storage_activities import (
    promote_certified_to_master_activity,
    apply_freshness_decay_activity,
    fetch_overdue_revalidations_activity,
    stage_overdue_for_reharvest_activity,
    evaluate_working_governance_activity,
)

logger = get_structured_logger("api.governance")

router = APIRouter(prefix="/api/governance", tags=["Governance & Promotion Gate"])


class PromotionTriggerRequest(BaseModel):
    min_quality: int = Field(80, ge=0, le=100, description="Minimum Bayesian quality score required for certification")
    min_trust: float = Field(0.8500, ge=0.0, le=1.0, description="Minimum Bayesian trust score required for certification")
    batch_size: int = Field(1000, ge=1, le=10000, description="Batch size for atomic CTE promotion")
    auto_evaluate_pre_master: bool = Field(True, description="Run working layer Bayesian evaluation before promotion")


class RevalidationSweepRequest(BaseModel):
    batch_size: int = Field(5000, ge=10, le=20000, description="Batch size of master entities to decay and inspect")
    auto_reharvest: bool = Field(True, description="Automatically stage detected overdue records into working_organizations")


@router.get("/stats")
def get_governance_stats(
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Returns real-time operational telemetry across Pre-Master Working Layer,
    Certification Gate, and Master Vault Golden Records.
    """
    conn = None
    try:
        conn = get_connection()
        if not conn:
            raise HTTPException(status_code=503, detail="Database connection unavailable")

        with conn.cursor() as cur:
            # 1. Working Organizations by status
            cur.execute("""
                SELECT governance_status, COUNT(*)
                FROM staging_dataextraction.working_organizations
                GROUP BY governance_status;
            """)
            wo_status_counts = dict(cur.fetchall())

            # 2. Working Persons and Emails
            cur.execute("SELECT COUNT(*) FROM staging_dataextraction.working_persons;")
            wp_count = cur.fetchone()[0]

            cur.execute("""
                SELECT deliverability_status, COUNT(*)
                FROM staging_dataextraction.working_emails
                GROUP BY deliverability_status;
            """)
            we_status_counts = dict(cur.fetchall())

            # 3. Master Golden Vault Stats
            cur.execute("""
                SELECT 
                    COUNT(*),
                    ROUND(AVG(COALESCE(data_quality_score, 0)), 1),
                    ROUND(AVG(COALESCE(trust_score, 0.95)), 4),
                    ROUND(AVG(COALESCE(freshness_score, 1.0)), 4),
                    COUNT(*) FILTER (WHERE next_verification_at <= NOW() OR freshness_score < 0.70)
                FROM master_dataextraction.organizations;
            """)
            m_org_row = cur.fetchone()

            cur.execute("SELECT COUNT(*) FROM master_dataextraction.persons;")
            m_person_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM master_dataextraction.contact_emails;")
            m_email_count = cur.fetchone()[0]

            # 4. DLQ stats — schema-qualified to staging_dataextraction
            cur.execute("SELECT COUNT(*) FROM staging_dataextraction.dead_letter_queue WHERE status = 'PENDING';")
            dlq_pending = cur.fetchone()[0]

        total_working = sum(wo_status_counts.values())
        approved_working = wo_status_counts.get("APPROVED", 0)
        quarantined_working = wo_status_counts.get("QUARANTINED", 0)
        promoted_working = wo_status_counts.get("PROMOTED", 0)
        in_enrichment = wo_status_counts.get("IN_ENRICHMENT", 0)
        reval_pending = wo_status_counts.get("REVALIDATION_PENDING", 0)

        quarantine_rate = round((quarantined_working / max(1, total_working)) * 100, 2)

        return {
            "status": "HEALTHY",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "working_layer": {
                "total_organizations": total_working,
                "in_enrichment": in_enrichment,
                "approved_for_promotion": approved_working,
                "promoted_to_master": promoted_working,
                "quarantined": quarantined_working,
                "revalidation_pending": reval_pending,
                "total_persons": wp_count,
                "total_emails": sum(we_status_counts.values()),
                "email_deliverability_breakdown": we_status_counts,
            },
            "master_vault": {
                "total_organizations": m_org_row[0],
                "average_quality_score": float(m_org_row[1] or 0),
                "average_trust_score": float(m_org_row[2] or 0),
                "average_freshness_score": float(m_org_row[3] or 0),
                "overdue_revalidations": m_org_row[4],
                "total_persons": m_person_count,
                "total_verified_emails": m_email_count,
            },
            "governance_gate": {
                "certification_threshold_quality": 80,
                "certification_threshold_trust": 0.8500,
                "quarantine_rate_percentage": quarantine_rate,
                "dlq_pending_records": dlq_pending,
            },
        }
    finally:
        if conn:
            _release_connection(conn)


@router.post("/promotion/trigger")
async def trigger_promotion_gate(
    body: PromotionTriggerRequest,
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Executes an atomic single-transaction promotion gate cycle:
    Promotes certified records (Quality >= min_quality, Trust >= min_trust, Sanctions CLEAR)
    from staging_dataextraction.working_* to master_dataextraction.*.
    """
    logger.info("Manual promotion gate triggered by user=%s", current_user.email)

    eval_summary = {}
    if body.auto_evaluate_pre_master:
        eval_summary = await evaluate_working_governance_activity({
            "batch_size": body.batch_size,
            "min_quality": body.min_quality,
            "min_trust": body.min_trust,
        })

    promo_result = await promote_certified_to_master_activity({
        "min_quality": body.min_quality,
        "min_trust": body.min_trust,
        "batch_size": body.batch_size,
    })

    return {
        "status": "COMPLETED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pre_evaluation": eval_summary,
        "promotion_gate_outcome": promo_result,
    }


@router.post("/revalidation/sweep")
async def trigger_revalidation_sweep(
    body: RevalidationSweepRequest,
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Executes the autonomous freshness decay and SLA revalidation sweep:
      1. Applies continuous mathematical exponential decay F(t) = exp(-lambda * delta_t)
      2. Detects expired SLA thresholds across all 6 dimensions
      3. Stages overdue entities back into working_organizations with REVALIDATION_PENDING
    """
    logger.info("Autonomous revalidation sweep triggered by user=%s", current_user.email)

    decay_res = await apply_freshness_decay_activity(batch_size=body.batch_size)
    fetch_res = await fetch_overdue_revalidations_activity(limit=body.batch_size)
    overdue_records = fetch_res.get("records", [])

    stage_res = {"status": "SKIPPED", "staged_count": 0}
    if body.auto_reharvest and overdue_records:
        stage_res = await stage_overdue_for_reharvest_activity(overdue_records)

    return {
        "status": "COMPLETED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "freshness_decay": decay_res,
        "overdue_detected": len(overdue_records),
        "reharvest_staging": stage_res,
    }


@router.get("/revalidation/overdue")
async def get_overdue_revalidations(
    limit: int = Query(100, ge=1, le=1000),
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Returns entities in Master Vault whose SLA verification interval has expired or freshness dropped below 0.70.
    """
    res = await fetch_overdue_revalidations_activity(limit=limit)
    return res


@router.get("/quarantine/records")
def get_quarantine_records(
    limit: int = Query(50, ge=1, le=200),
    current_user: UserPrincipal = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Returns quarantined records from Pre-Master working layer and DLQ.
    """
    conn = None
    records = []
    try:
        conn = get_connection()
        if conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT org_id, legal_name, primary_domain, data_quality_score,
                           trust_score, governance_status, updated_at
                    FROM staging_dataextraction.working_organizations
                    WHERE governance_status = 'QUARANTINED'
                    ORDER BY updated_at DESC
                    LIMIT %s;
                """, (limit,))
                rows = cur.fetchall()
                cols = [c[0] for c in cur.description] if cur.description else []
                for r in rows:
                    records.append(dict(zip(cols, r)))
    finally:
        if conn:
            _release_connection(conn)

    return {
        "status": "SUCCESS",
        "count": len(records),
        "records": records,
    }
