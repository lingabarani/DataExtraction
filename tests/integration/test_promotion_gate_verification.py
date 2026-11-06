"""
DataExtraction — Promotion Gate Verification & Master Vault Integration Test
=============================================================================
Validates:
  1. Mandatory Quality >= 80 & Trust Score >= 0.85 promotion threshold
  2. Sub-threshold record quarantine and non-promotion
  3. Atomic CTE transaction invariants (working layer -> master_vault)
  4. ConfigManager integration (dynamic threshold resolution)
  5. Rollback on CTE database execution exception
"""

import asyncio
import pytest
import uuid
from unittest.mock import MagicMock, patch

from packages.infrastructure.config_manager import config_manager
from packages.temporal.activities.storage_activities import promote_certified_to_master_activity


def test_promotion_gate_config_resolution():
    """Validates that Promotion Gate loads dynamic thresholds from ConfigManager."""
    cfg = config_manager.get_promotion_gate_config()
    assert "min_quality_score" in cfg
    assert "min_trust_score" in cfg
    assert "batch_chunk_size" in cfg
    assert "freshness_initial_score" in cfg
    assert "revalidation_interval_days" in cfg
    assert cfg["min_quality_score"] >= 80
    assert cfg["min_trust_score"] >= 0.85
    assert cfg["freshness_initial_score"] == 1.0


@pytest.mark.asyncio
async def test_promotion_gate_threshold_and_atomic_cte_mocked():
    """
    Verifies that promote_certified_to_master_activity executes the atomic
    multi-row CTE with exact parameters and commits the transaction.
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.rowcount = 5

    with patch("packages.temporal.activities.storage_activities.get_connection", return_value=mock_conn), \
         patch("packages.temporal.activities.storage_activities.release_connection") as mock_release:
        
        result = await promote_certified_to_master_activity({
            "min_quality": 85,
            "min_trust": 0.90,
            "batch_size": 250,
            "target_org_id": None,
        })

        assert result["status"] == "COMPLETED"
        assert result["promoted_orgs"] == 5
        assert mock_conn.commit.called
        assert mock_release.called

        # Verify that parameters passed to the execute query match thresholds
        execute_calls = mock_cur.execute.call_args_list
        assert len(execute_calls) >= 1
        query_sql, params = execute_calls[0][0]
        assert "WITH locked_batch AS" in query_sql
        assert "INSERT INTO master_dataextraction.organizations" in query_sql
        assert params[0] == 85  # min_quality
        assert params[1] == 0.90  # min_trust
        assert params[4] == 250  # batch_size


@pytest.mark.asyncio
async def test_promotion_gate_transaction_rollback_on_error():
    """
    Verifies that if an error occurs during CTE execution,
    the transaction is rolled back and no partial records leak.
    """
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.execute.side_effect = RuntimeError("Deadlock detected during promotion CTE")

    with patch("packages.temporal.activities.storage_activities.get_connection", return_value=mock_conn), \
         patch("packages.temporal.activities.storage_activities.release_connection"):

        result = await promote_certified_to_master_activity({"min_quality": 80})

        # Must report 0 promoted and trigger rollback
        assert result["status"] == "COMPLETED"
        assert result["promoted_orgs"] == 0
        assert mock_conn.rollback.called
        assert not mock_conn.commit.called


@pytest.mark.asyncio
async def test_promotion_gate_live_db_if_available():
    """
    Live database integration verification (skipped if local PostgreSQL is unreachable).
    Tests atomic promotion of certified records from working_organizations to master.
    """
    from packages.infrastructure.db_connector import get_connection, release_connection
    conn = None
    try:
        from packages.temporal.client import _is_port_open
        from packages.infrastructure.db_connector import DB_HOST, DB_PORT
        if not _is_port_open(f"{DB_HOST}:{DB_PORT}", timeout=0.15):
            pytest.skip("PostgreSQL connection not reachable")
        conn = get_connection()
    except Exception:
        pytest.skip("PostgreSQL connection not available in local test environment")

    test_org_pass = str(uuid.uuid4())
    test_org_fail = str(uuid.uuid4())

    try:
        with conn.cursor() as cur:
            # 1. Insert Passing Record (Quality=95, Trust=0.95, APPROVED)
            cur.execute("""
                INSERT INTO staging_dataextraction.working_organizations (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    data_quality_score, trust_score, governance_status, created_at, updated_at
                ) VALUES (
                    %s, 'US', 'Promotion Gate Pass Inc', 'Pass Inc', 'pass-inc.com',
                    95, 0.95, 'APPROVED', NOW(), NOW()
                );
            """, (test_org_pass,))

            # 2. Insert Sub-threshold Record (Quality=65, Trust=0.60, PENDING)
            cur.execute("""
                INSERT INTO staging_dataextraction.working_organizations (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    data_quality_score, trust_score, governance_status, created_at, updated_at
                ) VALUES (
                    %s, 'US', 'Promotion Gate Fail Inc', 'Fail Inc', 'fail-inc.com',
                    65, 0.60, 'PENDING', NOW(), NOW()
                );
            """, (test_org_fail,))
            conn.commit()

        # Run promotion activity specifically targeting test_org_pass
        res = await promote_certified_to_master_activity({
            "target_org_id": test_org_pass,
            "min_quality": 80,
            "min_trust": 0.85,
        })
        assert res["promoted_orgs"] >= 1

        # Assert database invariants
        with conn.cursor() as cur:
            # Passing org must be in master
            cur.execute("SELECT count(*) FROM master_dataextraction.organizations WHERE org_id = %s::uuid;", (test_org_pass,))
            assert cur.fetchone()[0] == 1, "Passing entity must exist in master vault"

            # Failing org must NOT be in master
            cur.execute("SELECT count(*) FROM master_dataextraction.organizations WHERE org_id = %s::uuid;", (test_org_fail,))
            assert cur.fetchone()[0] == 0, "Sub-threshold entity must NOT exist in master vault"

    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM master_dataextraction.organizations WHERE org_id = %s::uuid;", (test_org_pass,))
                cur.execute("DELETE FROM staging_dataextraction.working_organizations WHERE org_id IN (%s, %s);", (test_org_pass, test_org_fail))
                conn.commit()
        except Exception:
            pass
        if conn:
            release_connection(conn)
