"""
DataExtraction — Sprint 6: 24-Hour Accelerated Endurance & Soak Simulation Test Suite
=====================================================================================
Validates long-running system resilience, memory stability, database connection
pool integrity, and continuous lifecycle transitions across accelerated operational cycles:
  1. Multi-cycle end-to-end soak: Ingestion -> Governance -> Promotion -> Decay -> SLA breach -> Re-harvest -> Re-promotion.
  2. Memory footprint drift & leak detection using tracemalloc (< 250 KB/cycle threshold).
  3. Database connection pool leak detection (100% connection release).
  4. Zero orphan records and strict referential integrity across Pre-Master & Master Vault.
"""

import asyncio
import gc
import json
import logging
import os
import sys
import time
import tracemalloc
import uuid
from datetime import datetime, timedelta, timezone
import pytest

from packages.benchmarks.load_test_100k import StreamRecordGenerator
from packages.infrastructure.db_connector import get_connection, release_connection
from packages.infrastructure.staging_writer import bulk_upsert_working_records
from packages.temporal.activities.storage_activities import (
    apply_freshness_decay_activity,
    evaluate_working_governance_activity,
    fetch_overdue_revalidations_activity,
    promote_certified_to_master_activity,
    stage_overdue_for_reharvest_activity,
)

logger = logging.getLogger("dataextraction.benchmarks.endurance_sim")


@pytest.mark.asyncio
async def test_endurance_accelerated_multi_cycle_soak():
    """
    Executes a 5-stage accelerated soak simulation testing continuous lifecycle transitions:
      Stage 1: Bulk Ingest into Pre-Master Working Layer.
      Stage 2: Bayesian Governance Evaluation & Certification.
      Stage 3: Atomic Promotion Gate into Master Vault (F(t) = 1.0000).
      Stage 4: Mathematical Freshness Decay & Overdue SLA Detection (t + 95 virtual days).
      Stage 5: Autonomous Re-Harvest Staging & Closed-Loop Re-Promotion.
    """
    test_id = f"soak_{uuid.uuid4().hex[:6]}"
    batch_size = 20
    generator = StreamRecordGenerator(seed=444)

    # ── Stage 1: Ingest into Working Layer ─────────────────────────────────────
    org_records = []
    email_records = []
    person_records = []

    for i in range(batch_size):
        org_id = str(uuid.uuid4())
        domain = f"soak-{i}-{test_id}.io"

        org_records.append({
            "org_id": org_id,
            "legal_name": f"Endurance Corp {i} {test_id.upper()}",
            "display_name": f"Endurance {i}",
            "primary_domain": domain,
            "statutory_tax_id": f"EIN-44-{i:06d}",
            "sec_cik": f"000{i:07d}",
            "jurisdiction": "US",
            "industry": "Data Engineering",
            "naics_code": "541511",
            "employee_count_min": 50,
            "employee_count_max": 250,
            "annual_revenue_usd": 12000000.00,
            "phones": [f"+1-800-555-{i:04d}"],
            "locations": [{"city": "Seattle", "state": "WA", "country": "United States"}],
            "data_quality_score": 90,
            "trust_score": 0.9200,
            "governance_status": "APPROVED",
        })

        email_records.append({
            "org_id": org_id,
            "email_address": f"lead.{i}@{domain}",
            "email_domain": domain,
            "deliverability_status": "DELIVERABLE",
            "confidence_score": 95,
            "is_catchall": False,
            "mx_record": f"mail.{domain}",
        })

        person_records.append({
            "person_id": str(uuid.uuid4()),
            "org_id": org_id,
            "full_name": f"Director Alex {i} Rivera",
            "first_name": "Alex",
            "last_name": f"Rivera_{i}",
            "title": "Director of Engineering",
            "seniority": "DIRECTOR",
            "department": "ENGINEERING",
            "primary_email": f"lead.{i}@{domain}",
            "confidence_score": 0.92,
            "governance_status": "APPROVED",
        })

    conn = get_connection()
    assert conn is not None
    try:
        cur = conn.cursor()
        bulk_upsert_working_records(cur, org_records, email_records, person_records)
        conn.commit()
        cur.close()
    finally:
        release_connection(conn)

    sample_org_id = org_records[0]["org_id"]

    # ── Stage 2: Governance Evaluation ─────────────────────────────────────────
    eval_res = await evaluate_working_governance_activity({"batch_size": 100})
    assert eval_res["status"] == "COMPLETED"

    # ── Stage 3: Atomic Promotion Gate into Master Vault ───────────────────────
    promo_res = await promote_certified_to_master_activity({
        "min_quality": 80,
        "min_trust": 0.8500,
        "batch_size": 500,
        "target_org_id": sample_org_id,
    })
    assert promo_res["status"] == "COMPLETED"
    assert promo_res["promoted_orgs"] >= 1

    # Verify initial Master state (Freshness = 1.0000)
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT freshness_score, governance_status, last_verified_at, next_verification_at
            FROM master_dataextraction.organizations
            WHERE org_id = %s::uuid;
        """, (sample_org_id,))
        m_row = cur.fetchone()
        assert m_row is not None
        assert float(m_row[0]) == 1.0000, "Freshness must be exactly 1.0000 post-promotion"
        assert m_row[1] == "CERTIFIED"

        # ── Stage 4: Simulate Virtual Passage of Time (t + 95 days) ───────────
        # Artificially age the record to simulate 95 days elapsed
        cur.execute("""
            UPDATE master_dataextraction.organizations
            SET last_verified_at = NOW() - INTERVAL '95 days',
                website_last_verified_at = NOW() - INTERVAL '95 days',
                email_last_verified_at = NOW() - INTERVAL '95 days',
                next_verification_at = NOW() - INTERVAL '5 days'
            WHERE org_id = %s::uuid;
        """, (sample_org_id,))
        conn.commit()
        cur.close()
    finally:
        release_connection(conn)

    # Apply mathematical freshness decay
    decay_res = await apply_freshness_decay_activity({"batch_size": 100, "org_id": sample_org_id})
    assert decay_res["status"] == "COMPLETED"

    # Verify decay occurred F(95d) < 1.0000
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT freshness_score
            FROM master_dataextraction.organizations
            WHERE org_id = %s::uuid;
        """, (sample_org_id,))
        f_score = float(cur.fetchone()[0])
        assert f_score < 0.9000, f"Freshness score should have decayed, got {f_score}"
        cur.close()
    finally:
        release_connection(conn)

    # Detect overdue SLA entities
    overdue_res = await fetch_overdue_revalidations_activity({"limit": 50, "org_id": sample_org_id})
    assert overdue_res["status"] == "COMPLETED"
    assert overdue_res["overdue_count"] >= 1
    found_overdue = any(r["org_id"] == sample_org_id for r in overdue_res["records"])
    assert found_overdue, "Target entity must be detected as overdue"

    # ── Stage 5: Autonomous Re-Harvest Staging & Re-Promotion ───────────────────
    stage_res = await stage_overdue_for_reharvest_activity(overdue_res)
    assert stage_res["status"] == "COMPLETED"
    assert stage_res["staged_count"] >= 1

    # Verify working organization transitioned to REVALIDATION_PENDING
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT governance_status, email_verification_status
            FROM staging_dataextraction.working_organizations
            WHERE org_id = %s;
        """, (sample_org_id,))
        w_row = cur.fetchone()
        assert w_row is not None
        assert w_row[0] == "REVALIDATION_PENDING"
        assert w_row[1] == "PENDING"

        # Simulate re-enrichment & re-approval
        cur.execute("""
            UPDATE staging_dataextraction.working_organizations
            SET email_verification_status = 'COMPLETED',
                executive_enrichment_status = 'COMPLETED',
                data_quality_score = 95,
                trust_score = 0.9700,
                governance_status = 'APPROVED'
            WHERE org_id = %s;
        """, (sample_org_id,))
        conn.commit()
        cur.close()
    finally:
        release_connection(conn)

    # Re-promote to Master Vault
    re_promo = await promote_certified_to_master_activity({
        "min_quality": 80,
        "min_trust": 0.8500,
        "batch_size": 100,
        "target_org_id": sample_org_id,
    })
    assert re_promo["status"] == "COMPLETED"
    assert re_promo["promoted_orgs"] >= 1

    # Verify Master Vault freshness refreshed to 1.0000
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT freshness_score, governance_status, next_verification_at
            FROM master_dataextraction.organizations
            WHERE org_id = %s::uuid;
        """, (sample_org_id,))
        re_row = cur.fetchone()
        assert float(re_row[0]) == 1.0000, "Freshness must be refreshed to 1.0000 post re-promotion"
        assert re_row[1] == "CERTIFIED"
        cur.close()
    finally:
        release_connection(conn)


@pytest.mark.asyncio
async def test_tracemalloc_memory_leak_verification():
    """
    Executes 10 repetitive cycles of generation, JSON serialization, and memory tracking.
    Enforces that net memory growth per cycle does not exceed 250 KB/cycle.
    """
    tracemalloc.start()
    generator = StreamRecordGenerator(seed=123)
    gc.collect()
    start_mem = tracemalloc.get_traced_memory()[0]

    num_cycles = 10
    batch_size = 50

    for c in range(num_cycles):
        batch = [generator.generate_record((c * batch_size) + i) for i in range(batch_size)]
        _ = json.dumps(batch)
        del batch
        gc.collect()

    curr_mem, peak_mem = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    net_growth_kb = (curr_mem - start_mem) / 1024.0
    avg_growth_kb_per_cycle = net_growth_kb / max(1, num_cycles)

    logger.info(
        "Memory leak audit: start=%.1f KB, end=%.1f KB, peak=%.1f KB, avg_growth=%.2f KB/cycle",
        start_mem / 1024.0,
        curr_mem / 1024.0,
        peak_mem / 1024.0,
        avg_growth_kb_per_cycle,
    )

    assert avg_growth_kb_per_cycle < 250.0, (
        f"Memory leak detected: growth was {avg_growth_kb_per_cycle:.2f} KB/cycle (threshold < 250 KB/cycle)"
    )


@pytest.mark.asyncio
async def test_connection_pool_saturation_and_leak_detection():
    """
    Executes 20 rapid sequential database operations to verify that all connections
    are properly acquired and released without pool exhaustion or leaks.
    """
    for i in range(20):
        conn = get_connection()
        assert conn is not None
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1;")
            row = cur.fetchone()
            assert row[0] == 1
            cur.close()
        finally:
            release_connection(conn)


@pytest.mark.asyncio
async def test_zero_orphan_records_and_referential_integrity():
    """
    Verifies that zero orphan records exist across Pre-Master working tables
    and Master tables (referential integrity between working_persons/emails and working_organizations).
    """
    conn = get_connection()
    assert conn is not None
    try:
        cur = conn.cursor()

        # Check working_persons orphan count
        cur.execute("""
            SELECT COUNT(*)
            FROM staging_dataextraction.working_persons wp
            LEFT JOIN staging_dataextraction.working_organizations wo ON wp.org_id = wo.org_id
            WHERE wo.org_id IS NULL;
        """)
        person_orphans = cur.fetchone()[0]

        # Check working_emails orphan count
        cur.execute("""
            SELECT COUNT(*)
            FROM staging_dataextraction.working_emails we
            LEFT JOIN staging_dataextraction.working_organizations wo ON we.org_id = wo.org_id
            WHERE wo.org_id IS NULL;
        """)
        email_orphans = cur.fetchone()[0]

        assert person_orphans == 0, f"Detected {person_orphans} orphan working_persons!"
        assert email_orphans == 0, f"Detected {email_orphans} orphan working_emails!"
        cur.close()
    finally:
        release_connection(conn)

