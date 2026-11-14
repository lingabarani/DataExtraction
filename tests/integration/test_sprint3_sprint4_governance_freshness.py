"""
DataExtraction — Sprints 3 & 4 Verification Suite
=================================================
Verifies:
  1. Mandatory Promotion Gate (Sprint 3):
     - Bayesian Trust & Governance Scoring Engine (Quality >= 80, Trust >= 0.85, Sanctions CLEAR -> APPROVED vs QUARANTINED)
     - Working Layer Governance Activity (transitions working_organizations to APPROVED or QUARANTINED in DLQ)
     - Atomic Single-Transaction CTE Promotion (moves APPROVED working orgs, persons, emails to master_dataextraction.*)
     - Post-Promotion Invariants (freshness_score = 1.0000, governance_status = 'CERTIFIED', next_verification_at = NOW() + 90 days)
  2. Autonomous Freshness & SLA Revalidation Engine (Sprint 4):
     - Continuous exponential decay F(t) = exp(-lambda * delta_t) with calibrated half-lives
     - Dimension-specific SLA expiration detection (Website 30d, Email 90d, Exec 90d, Maps 180d, Registry 365d)
     - Overdue SLA detection activity (identifies entities with next_verification_at <= NOW() or freshness < 0.70)
     - Auto-reharvest staging activity (stages overdue entities into working_organizations with REVALIDATION_PENDING)
"""

import asyncio
import datetime
import json
import sys
import uuid
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.domain.trust_engine import trust_engine
from packages.domain.freshness_engine import freshness_engine
from packages.temporal.activities.storage_activities import (
    evaluate_working_governance_activity,
    promote_certified_to_master_activity,
    apply_freshness_decay_activity,
    fetch_overdue_revalidations_activity,
    stage_overdue_for_reharvest_activity,
)


@pytest.fixture
def db_conn():
    conn = get_connection()
    conn.rollback()
    yield conn
    try:
        conn.rollback()
    finally:
        release_connection(conn)


def test_trust_engine_scoring_and_sanctions():
    """Verify Bayesian Trust Engine approves high-integrity records and quarantines low-integrity or sanctioned records."""
    # 1. High Integrity Corporate Record
    valid_org = {
        "org_id": f"org-{uuid.uuid4().hex[:8]}",
        "legal_name": "Apex Enterprise Technologies Inc.",
        "display_name": "Apex Enterprise",
        "primary_domain": "apexenterprise.com",
        "website": "https://www.apexenterprise.com",
        "statutory_tax_id": "12-3456789",
        "sec_cik": "0001234567",
        "jurisdiction": "US",
        "industry": "Enterprise Software",
        "naics_code": "541511",
        "employee_count_min": 150,
        "employee_count_max": 200,
        "annual_revenue_usd": 25000000.0,
        "phones": ["+1-800-555-0199"],
        "locations": [{"city": "San Francisco", "state": "CA", "country": "USA", "lat": 37.7749, "lng": -122.4194}],
        "email_verification_status": "COMPLETED",
        "identity_confidence": 0.95,
        "contributing_sources": ["SEC_EDGAR", "GLEIF_LEI", "GOOGLE_MAPS"],
        "lineage_ids": ["src_1", "src_2"],
    }
    eval_res = trust_engine.evaluate_organization(valid_org)
    assert eval_res["is_certified"] is True, f"Expected certified record, got {eval_res}"
    assert eval_res["data_quality_score"] >= 80, f"Quality {eval_res['data_quality_score']} < 80"
    assert eval_res["trust_score"] >= 0.8500, f"Trust {eval_res['trust_score']} < 0.8500"
    assert eval_res["governance_status"] == "APPROVED"
    assert eval_res["is_suppressed"] is False

    # 2. Low Completeness & Suspicious Record (Should be Quarantined)
    sketchy_org = {
        "org_id": f"org-{uuid.uuid4().hex[:8]}",
        "legal_name": "Temporary Ghost Entity",
        "primary_domain": "tempmail.org",
        "identity_confidence": 0.40,
        "contributing_sources": ["GENERIC_WEB"],
    }
    sketchy_eval = trust_engine.evaluate_organization(sketchy_org)
    assert sketchy_eval["is_certified"] is False
    assert sketchy_eval["governance_status"] == "QUARANTINED"
    assert sketchy_eval["quarantine_reason"] is not None


def test_freshness_engine_decay_and_sla_detection():
    """Verify continuous exponential decay formula F(t) = exp(-lambda * delta_t) and dimension SLA detection."""
    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Fresh Entity (All verified right now)
    fresh_entity = {
        "website_last_verified_at": now,
        "email_last_verified_at": now,
        "executive_last_verified_at": now,
        "domain_last_verified_at": now,
        "maps_last_verified_at": now,
        "registry_last_verified_at": now,
    }
    f_res = freshness_engine.evaluate_organization_freshness(fresh_entity)
    assert f_res["composite_freshness"] == 1.0000
    assert len(f_res["overdue_dimensions"]) == 0
    assert f_res["is_overdue"] is False

    # 2. Stale Entity (Website 45d ago -> expired, Email 100d ago -> expired)
    stale_entity = {
        "website_last_verified_at": now - datetime.timedelta(days=45),
        "email_last_verified_at": now - datetime.timedelta(days=100),
        "executive_last_verified_at": now - datetime.timedelta(days=10),
        "domain_last_verified_at": now - datetime.timedelta(days=10),
        "maps_last_verified_at": now - datetime.timedelta(days=10),
        "registry_last_verified_at": now - datetime.timedelta(days=10),
    }
    stale_eval = freshness_engine.evaluate_organization_freshness(stale_entity)
    assert stale_eval["composite_freshness"] < 1.0000
    assert "website" in stale_eval["overdue_dimensions"]
    assert "email" in stale_eval["overdue_dimensions"]
    assert stale_eval["is_overdue"] is True
    assert len(stale_eval["recommended_actions"]) > 0


@pytest.mark.asyncio
async def test_working_layer_governance_and_atomic_promotion(db_conn):
    """
    Integration Test:
      1. Insert valid entity into staging_dataextraction.working_organizations with IN_ENRICHMENT
      2. Attach a working person and working email
      3. Insert a low-quality entity into staging_dataextraction.working_organizations
      4. Run evaluate_working_governance_activity:
         - Valid entity transitions to 'APPROVED'
         - Low-quality entity transitions to 'QUARANTINED'
      5. Run promote_certified_to_master_activity:
         - Valid entity atomically promoted to master_dataextraction.organizations with freshness = 1.0000
         - Working person promoted to master_dataextraction.persons
         - Working email promoted to master_dataextraction.contact_emails
         - Working status updated to 'PROMOTED'
    """
    valid_org_id = str(uuid.uuid4())
    valid_domain = f"corp-{valid_org_id[:8]}.com"
    valid_person_id = str(uuid.uuid4())
    valid_email = f"ceo@{valid_domain}"

    quarantine_org_id = str(uuid.uuid4())
    quarantine_domain = f"quarantine-{quarantine_org_id[:8]}.com"

    try:
        # Step 1: Insert test records into working layer
        with db_conn.cursor() as cur:
            # High-integrity org
            cur.execute("""
                INSERT INTO staging_dataextraction.working_organizations (
                    org_id, legal_name, display_name, primary_domain, website,
                    statutory_tax_id, sec_cik, jurisdiction, industry, naics_code,
                    employee_count_min, employee_count_max, annual_revenue_usd,
                    phones, locations, email_verification_status, identity_confidence,
                    contributing_sources, lineage_ids, governance_status
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s::jsonb, %s::jsonb, 'COMPLETED', %s,
                    %s, %s::jsonb, 'IN_ENRICHMENT'
                );
            """, (
                valid_org_id, f"Valid Global Corp {valid_org_id[:6]}", "Valid Corp",
                valid_domain, f"https://www.{valid_domain}", "99-8877665", "0001999888",
                "US", "Software", "541511", 100, 250, 15000000.0,
                json.dumps(["+1-555-0100"]),
                json.dumps([{"city": "Austin", "state": "TX", "lat": 30.2672, "lng": -97.7431}]),
                0.95, ["SEC_EDGAR", "GLEIF_LEI", "GOOGLE_MAPS"],
                json.dumps(["ln_1", "ln_2"])
            ))

            # Working person
            cur.execute("""
                INSERT INTO staging_dataextraction.working_persons (
                    person_id, org_id, full_name, first_name, last_name,
                    title, seniority, department, primary_email, confidence_score,
                    governance_status
                ) VALUES (
                    %s, %s, 'Jane Doe', 'Jane', 'Doe',
                    'Chief Executive Officer', 'C-Level', 'Executive', %s, 0.95,
                    'IN_ENRICHMENT'
                );
            """, (valid_person_id, valid_org_id, valid_email))

            # Working email
            cur.execute("""
                INSERT INTO staging_dataextraction.working_emails (
                    email_address, email_domain, org_id, deliverability_status,
                    confidence_score, mx_record, smtp_verified_at
                ) VALUES (
                    %s, %s, %s, 'DELIVERABLE',
                    98, 'mx1.mail.com', NOW()
                );
            """, (valid_email, valid_domain, valid_org_id))

            # Sub-threshold org (no tax id, low confidence -> quarantine)
            cur.execute("""
                INSERT INTO staging_dataextraction.working_organizations (
                    org_id, legal_name, primary_domain, identity_confidence,
                    contributing_sources, governance_status
                ) VALUES (
                    %s, 'Incomplete Scraping Lead', %s, 0.40,
                    ARRAY['GENERIC_WEB']::TEXT[], 'IN_ENRICHMENT'
                );
            """, (quarantine_org_id, quarantine_domain))
            db_conn.commit()

        # Step 2: Run evaluate_working_governance_activity
        eval_res = await evaluate_working_governance_activity({
            "batch_size": 100,
            "org_ids": [valid_org_id, quarantine_org_id],
        })
        assert eval_res["status"] == "COMPLETED"

        with db_conn.cursor() as cur:
            cur.execute("SELECT governance_status, data_quality_score, trust_score FROM staging_dataextraction.working_organizations WHERE org_id = %s;", (valid_org_id,))
            v_stat, v_q, v_t = cur.fetchone()
            assert v_stat == "APPROVED", f"Expected APPROVED, got {v_stat}"
            assert v_q >= 80, f"Expected quality >= 80, got {v_q}"
            assert v_t >= 0.85, f"Expected trust >= 0.85, got {v_t}"

            cur.execute("SELECT governance_status, data_quality_score, trust_score FROM staging_dataextraction.working_organizations WHERE org_id = %s;", (quarantine_org_id,))
            q_stat, q_q, q_t = cur.fetchone()
            assert q_stat == "QUARANTINED", f"Expected QUARANTINED, got {q_stat}"

        # Step 3: Run promote_certified_to_master_activity
        promo_res = await promote_certified_to_master_activity({"min_quality": 80, "min_trust": 0.85, "batch_size": 100})
        assert promo_res["status"] == "COMPLETED"
        assert promo_res["promoted_orgs"] >= 1

        with db_conn.cursor() as cur:
            # 1. Master org assertions
            cur.execute("""
                SELECT governance_status, freshness_score, next_verification_at, verification_source
                FROM master_dataextraction.organizations
                WHERE org_id = %s::uuid;
            """, (valid_org_id,))
            m_org = cur.fetchone()
            assert m_org is not None, "Organization was NOT promoted to master_dataextraction.organizations!"
            m_gov, m_fresh, m_next, m_src = m_org
            assert m_gov == "CERTIFIED"
            assert float(m_fresh) == 1.0000
            assert m_src == "PROMOTION_GATE"
            assert m_next is not None

            # 2. Master person assertions
            cur.execute("""
                SELECT current_primary_title, governance_status
                FROM master_dataextraction.persons
                WHERE person_id = %s::uuid;
            """, (valid_person_id,))
            m_per = cur.fetchone()
            assert m_per is not None, "Person was NOT promoted to master_dataextraction.persons!"
            assert m_per[0] == "Chief Executive Officer"
            assert m_per[1] == "CERTIFIED"

            # 3. Master email assertions
            cur.execute("""
                SELECT deliverability_status
                FROM master_dataextraction.contact_emails
                WHERE email_address = %s;
            """, (valid_email,))
            m_em = cur.fetchone()
            assert m_em is not None, "Email was NOT promoted to master_dataextraction.contact_emails!"
            assert m_em[0] in ("DELIVERABLE", "verified_deliverable")

            # 4. Working status assertions
            cur.execute("SELECT governance_status FROM staging_dataextraction.working_organizations WHERE org_id = %s;", (valid_org_id,))
            w_stat = cur.fetchone()[0]
            assert w_stat == "PROMOTED"

    finally:
        # Cleanup test records
        db_conn.rollback()
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM master_dataextraction.contact_emails WHERE email_address = %s;", (valid_email,))
            cur.execute("DELETE FROM master_dataextraction.persons WHERE person_id = %s::uuid;", (valid_person_id,))
            cur.execute("DELETE FROM master_dataextraction.organizations WHERE org_id = %s::uuid;", (valid_org_id,))
            cur.execute("DELETE FROM staging_dataextraction.working_emails WHERE email_address = %s;", (valid_email,))
            cur.execute("DELETE FROM staging_dataextraction.working_persons WHERE person_id = %s;", (valid_person_id,))
            cur.execute("DELETE FROM staging_dataextraction.working_organizations WHERE org_id IN (%s, %s);", (valid_org_id, quarantine_org_id))
            db_conn.commit()


@pytest.mark.asyncio
async def test_freshness_decay_and_autonomous_revalidation(db_conn):
    """
    Sprint 4 Autonomous Freshness & Revalidation Test:
      1. Insert a certified record in master_dataextraction.organizations with stale timestamps
      2. Execute apply_freshness_decay_activity -> verify freshness_score drops below 1.0
      3. Set next_verification_at to yesterday -> verify fetch_overdue_revalidations_activity detects it
      4. Execute stage_overdue_for_reharvest_activity -> verify record is restaged into working_organizations
         with governance_status = 'REVALIDATION_PENDING'
    """
    stale_org_id = str(uuid.uuid4())
    stale_domain = f"stale-{stale_org_id[:8]}.com"

    try:
        with db_conn.cursor() as cur:
            cur.execute("""
                INSERT INTO master_dataextraction.organizations (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    entity_status, governance_status, freshness_score, last_verified_at, next_verification_at,
                    website_last_verified_at, email_last_verified_at, executive_last_verified_at,
                    domain_last_verified_at, maps_last_verified_at, registry_last_verified_at
                ) VALUES (
                    %s::uuid, 'US', 'Stale Holdings LLC', 'Stale Holdings', %s,
                    'active', 'CERTIFIED', 1.0000, NOW() - INTERVAL '120 days', NOW() - INTERVAL '30 days',
                    NOW() - INTERVAL '60 days', NOW() - INTERVAL '120 days', NOW() - INTERVAL '120 days',
                    NOW() - INTERVAL '120 days', NOW() - INTERVAL '200 days', NOW() - INTERVAL '400 days'
                );
            """, (stale_org_id, stale_domain))
            db_conn.commit()

        # Step 2: Apply freshness decay
        decay_res = await apply_freshness_decay_activity({"batch_size": 100, "org_id": stale_org_id})
        assert decay_res["status"] == "COMPLETED"

        with db_conn.cursor() as cur:
            cur.execute("SELECT freshness_score FROM master_dataextraction.organizations WHERE org_id = %s::uuid;", (stale_org_id,))
            new_freshness = float(cur.fetchone()[0])
            assert new_freshness < 0.70, f"Expected decayed freshness < 0.70, got {new_freshness}"

        # Step 3: Fetch overdue revalidations
        fetch_res = await fetch_overdue_revalidations_activity({"limit": 100, "org_id": stale_org_id})
        assert fetch_res["status"] == "COMPLETED"
        found = [r for r in fetch_res["records"] if r["org_id"] == stale_org_id]
        assert len(found) == 1, f"Expected {stale_org_id} in overdue records, got {fetch_res['records']}"
        assert len(found[0]["overdue_dimensions"]) > 0

        # Step 4: Stage overdue for reharvest
        stage_res = await stage_overdue_for_reharvest_activity(fetch_res["records"])
        assert stage_res["status"] == "COMPLETED"
        assert stage_res["staged_count"] >= 1

        with db_conn.cursor() as cur:
            cur.execute("SELECT governance_status, email_verification_status, executive_enrichment_status FROM staging_dataextraction.working_organizations WHERE org_id = %s;", (stale_org_id,))
            staged_row = cur.fetchone()
            assert staged_row is not None, "Overdue record was NOT staged into working_organizations!"
            assert staged_row[0] == "REVALIDATION_PENDING"
            assert staged_row[1] == "PENDING"  # Email revalidation triggered
            assert staged_row[2] == "PENDING"  # Executive revalidation triggered

    finally:
        db_conn.rollback()
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM staging_dataextraction.working_organizations WHERE org_id = %s;", (stale_org_id,))
            cur.execute("DELETE FROM master_dataextraction.organizations WHERE org_id = %s::uuid;", (stale_org_id,))
            db_conn.commit()
