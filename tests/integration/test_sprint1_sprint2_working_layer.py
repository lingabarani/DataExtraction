"""
DataExtraction — Sprints 1 & 2 Verification Suite
=================================================
Verifies:
  1. Database Foundation (Sprint 1):
     - staging_dataextraction.working_organizations table & indexes
     - staging_dataextraction.working_persons table & indexes
     - staging_dataextraction.working_emails table & indexes
     - master_dataextraction.organizations lifecycle & freshness columns
     - master_dataextraction.persons lifecycle & trust columns
  2. Pre-Master Working Layer Redirection (Sprint 2):
     - Agent 3 (Identity Resolution) writes to staging_dataextraction.working_organizations
     - Agent 7 (Email Verification) reads pending orgs and writes to staging_dataextraction.working_emails
     - Agent 4 (Executive Discovery) writes to staging_dataextraction.working_persons
     - ZERO rows written to master_dataextraction.* during pre-master enrichment
"""

import sys
import uuid
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in [str(REPO_ROOT), str(REPO_ROOT / "packages"), str(REPO_ROOT / "packages" / "infrastructure")]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.infrastructure.kg_ingestion_bridge import kg_ingestion_bridge
from packages.infrastructure.email_enrichment_repository import email_enrichment_repo


@pytest.fixture(scope="module")
def db_conn():
    conn = get_connection()
    yield conn
    release_connection(conn)


def test_sprint1_schema_working_tables_exist(db_conn):
    """Test that all three pre-master working canvas tables exist in staging_dataextraction."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'staging_dataextraction'
              AND table_name IN ('working_organizations', 'working_persons', 'working_emails')
            ORDER BY table_name;
        """)
        found_tables = {r[0] for r in cur.fetchall()}
        assert "working_organizations" in found_tables, "working_organizations table missing"
        assert "working_persons" in found_tables, "working_persons table missing"
        assert "working_emails" in found_tables, "working_emails table missing"


def test_sprint1_master_lifecycle_columns_exist(db_conn):
    """Test that master_dataextraction tables possess all required lifecycle, freshness, and trust columns."""
    with db_conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = 'master_dataextraction' 
              AND table_name = 'organizations'
              AND column_name IN (
                  'governance_status', 'trust_score', 'freshness_score', 
                  'last_verified_at', 'next_verification_at', 'website_last_verified_at', 
                  'email_last_verified_at', 'executive_last_verified_at', 'domain_last_verified_at'
              );
        """)
        org_cols = {r[0] for r in cur.fetchall()}
        expected_org_cols = {
            'governance_status', 'trust_score', 'freshness_score', 
            'last_verified_at', 'next_verification_at', 'website_last_verified_at', 
            'email_last_verified_at', 'executive_last_verified_at', 'domain_last_verified_at'
        }
        assert expected_org_cols.issubset(org_cols), f"Missing master organization columns: {expected_org_cols - org_cols}"

        cur.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_schema = 'master_dataextraction' 
              AND table_name = 'persons'
              AND column_name IN ('governance_status', 'trust_score', 'last_verified_at', 'next_verification_at');
        """)
        person_cols = {r[0] for r in cur.fetchall()}
        expected_person_cols = {'governance_status', 'trust_score', 'last_verified_at', 'next_verification_at'}
        assert expected_person_cols.issubset(person_cols), f"Missing master person columns: {expected_person_cols - person_cols}"


def test_sprint2_pre_master_redirection_end_to_end(db_conn):
    """
    End-to-End Simulation of Sprint 2:
      1. Agent 3 writes to staging_dataextraction.working_organizations
      2. Zero records written to master_dataextraction.organizations
      3. Agent 7 discovers and writes to staging_dataextraction.working_emails and updates status
      4. Agent 4 writes to staging_dataextraction.working_persons
      5. Zero records written to master_dataextraction.persons
    """
    test_org_id = f"test-org-{uuid.uuid4().hex[:8]}"
    test_domain = f"{test_org_id}.com"
    test_person_id = f"test-person-{uuid.uuid4().hex[:8]}"

    try:
        # ── Step 1: Agent 3 Identity Resolution writes to Working Layer ───────
        org_data = {
            "org_id": test_org_id,
            "legal_name": "Antigravity Solutions Inc",
            "display_name": "Antigravity Solutions",
            "primary_domain": test_domain,
            "website": f"https://{test_domain}",
            "statutory_tax_id": "12-3456789",
            "jurisdiction": "US",
            "industry": "Enterprise Software",
            "employee_count_min": 100,
            "employee_count_max": 250,
            "data_quality_score": 92,
        }
        res_org_id = kg_ingestion_bridge.ingest_working_organization(
            conn=db_conn,
            org_data=org_data,
            source_name="AGENT_3_SPLINK",
            canonical_cluster_id=f"cluster-{test_org_id}",
            identity_confidence=0.985,
        )
        db_conn.commit()
        assert res_org_id == test_org_id

        # Verify record in working_organizations
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT legal_name, email_verification_status, executive_enrichment_status, governance_status
                FROM staging_dataextraction.working_organizations
                WHERE org_id = %s;
            """, (test_org_id,))
            row = cur.fetchone()
            assert row is not None, "Working organization was not stored!"
            assert row[0] == "Antigravity Solutions Inc"
            assert row[1] == "PENDING"
            assert row[2] == "PENDING"
            assert row[3] == "IN_ENRICHMENT"

            # ZERO WRITES TO MASTER VERIFICATION
            cur.execute("""
                SELECT COUNT(1) FROM master_dataextraction.organizations
                WHERE primary_domain = %s;
            """, (test_domain,))
            master_count = cur.fetchone()[0]
            assert master_count == 0, "VIOLATION: Record was leaked directly into master_dataextraction.organizations!"

        # ── Step 2: Agent 7 Email Discovery reads from Working Layer ─────────
        pending_batch = email_enrichment_repo.get_pending_canonical_companies(
            last_id=None,
            limit=1000,
            target_table="staging_dataextraction.working_organizations",
        )
        assert any(c["id"] == test_org_id for c in pending_batch), "Agent 7 could not find pending working organization"

        # Simulate discovery & 5-tier verification
        discovered_email = f"contact@{test_domain}"
        email_enrichment_repo.save_enrichment_result(
            company_id=test_org_id,
            domain=test_domain,
            primary_email=discovered_email,
            all_emails=[discovered_email, f"press@{test_domain}"],
            discovery_source="WEBSITE_CRAWL",
            deliverability_status="DELIVERABLE",
            confidence_score=95.0,
            is_catchall=False,
            tech_stack=["React", "PostgreSQL"],
            cms_detected=None,
            ssl_valid=True,
            site_speed_ms=120,
            http_status_code=200,
        )

        # Verify working_emails and working_organizations status
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT email_address, deliverability_status, confidence_score
                FROM staging_dataextraction.working_emails
                WHERE org_id = %s ORDER BY email_address;
            """, (test_org_id,))
            emails = cur.fetchall()
            assert len(emails) >= 1, "Working emails were not persisted!"
            assert any(e[0] == discovered_email and e[1] == "DELIVERABLE" for e in emails)

            cur.execute("""
                SELECT email_verification_status 
                FROM staging_dataextraction.working_organizations 
                WHERE org_id = %s;
            """, (test_org_id,))
            email_status = cur.fetchone()[0]
            assert email_status == "COMPLETED", "Working organization status was not transitioned to COMPLETED"

        # ── Step 3: Agent 4 Executive Discovery writes to Working Layer ───────
        person_data = {
            "person_id": test_person_id,
            "full_name": "Dr. Sarah Chen",
            "first_name": "Sarah",
            "last_name": "Chen",
            "title": "Chief Technology Officer",
            "seniority": "C-Suite",
            "department": "Engineering",
            "primary_email": f"sarah.chen@{test_domain}",
            "linkedin_url": f"https://linkedin.com/in/{test_person_id}",
            "confidence_score": 0.95,
        }
        res_person_id = kg_ingestion_bridge.ingest_working_person(
            conn=db_conn,
            person_data=person_data,
            org_id=test_org_id,
            confidence_score=0.95,
        )
        db_conn.commit()
        assert res_person_id == test_person_id

        # Verify working_persons record
        with db_conn.cursor() as cur:
            cur.execute("""
                SELECT full_name, title, org_id, governance_status
                FROM staging_dataextraction.working_persons
                WHERE person_id = %s;
            """, (test_person_id,))
            p_row = cur.fetchone()
            assert p_row is not None, "Working person was not stored!"
            assert p_row[0] == "Dr. Sarah Chen"
            assert p_row[1] == "Chief Technology Officer"
            assert p_row[2] == test_org_id
            assert p_row[3] == "IN_ENRICHMENT"

            # ZERO WRITES TO MASTER PERSONS VERIFICATION
            cur.execute("""
                SELECT COUNT(1) FROM master_dataextraction.persons
                WHERE full_name = 'Dr. Sarah Chen';
            """, )
            master_person_count = cur.fetchone()[0]
            assert master_person_count == 0, "VIOLATION: Person record was leaked directly into master_dataextraction.persons!"

    finally:
        # Cleanup test artifacts
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM staging_dataextraction.working_organizations WHERE org_id = %s;", (test_org_id,))
            cur.execute("DELETE FROM staging_dataextraction.working_persons WHERE person_id = %s;", (test_person_id,))
            cur.execute("DELETE FROM staging_dataextraction.working_emails WHERE org_id = %s;", (test_org_id,))
            db_conn.commit()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
