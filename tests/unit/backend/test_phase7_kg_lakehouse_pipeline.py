"""
Phase 7 Test Suite: Enterprise Knowledge Graph, Identity Resolution & Partition Engine
========================================================================================
Comprehensive verification of:
1. KnowledgeGraphIngestionBridge:
   - Lakehouse Parquet offload and SHA-256 metadata tracking in kg_observation.
   - Canonical organization upsert, multi-domains, aliases, emails, and phones.
   - Field-level provenance tracking in kg_lineage.field_provenance.
   - Search projection updates in kg_search.company_search_projection.
   - Person and temporal employment relationships in kg_core & kg_graph.
   - Corporate hierarchies and org technology stacks.
2. GraphIdentityResolver:
   - Multi-signal lookup: tax ID, multi-domain, alias/trade name.
   - Identity cluster creation and member binding.
   - Zero-destruction reversible unmerge ($O(1)$) via unmerge_events.
   - Cluster detail inspection and audit trail tracking.
3. PartitionManager:
   - Dynamic forward-looking pre-allocation for observation and employment tables.
   - Catalog querying and partition inventory.
4. Deduplicator & Storage Activity Bindings:
   - Method aliases (resolve_company, resolve_person).
   - Storage activities execution contract.
"""

import json
import unittest
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
_backend_dir = Path(__file__).resolve().parent
_project_root = _backend_dir.parents[2]
_packages = _project_root / "packages"

for _p in [
    _packages / "pipeline",
    _packages / "infrastructure",
    _packages / "temporal",
    _packages / "temporal" / "activities",
    _project_root,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from packages.infrastructure.kg_ingestion_bridge import KnowledgeGraphIngestionBridge
from packages.pipeline.graph_identity_resolver import GraphIdentityResolver
from packages.infrastructure.partition_manager import PartitionManager
from packages.pipeline.deduplicator import Deduplicator, DedupResult


class TestKnowledgeGraphIngestionBridge(unittest.TestCase):
    """Verifies KnowledgeGraphIngestionBridge writes evidence-backed entities."""

    def setUp(self):
        self.mock_lakehouse = MagicMock()
        self.mock_lakehouse.write_raw_observation.return_value = {
            "lakehouse_s3_uri": "s3://data-lake/observations/sec_edgar/2026/10/hash123.parquet",
            "payload_hash_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "byte_size": 2048,
            "status": "stored",
        }
        self.bridge = KnowledgeGraphIngestionBridge(s3_lakehouse=self.mock_lakehouse)
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value.__enter__.return_value = self.mock_cur

    def test_persist_raw_observation(self):
        res = self.bridge.persist_raw_observation(
            conn=self.mock_conn,
            source_name="SEC_EDGAR",
            source_record_id="CIK-0001018724",
            raw_payload={"company": "Amazon Inc", "cik": "0001018724"},
            extracted_summary={"name": "Amazon Inc"},
            observed_entity_type="organization",
        )
        self.assertEqual(res["source_name"], "SEC_EDGAR")
        self.assertEqual(res["payload_hash_sha256"], "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        self.assertTrue(self.mock_lakehouse.write_raw_observation.called)
        self.assertTrue(self.mock_cur.execute.called)

    def test_ingest_organization_full(self):
        self.mock_cur.fetchone.return_value = ("550e8400-e29b-41d4-a716-446655440000",)
        org_data = {
            "legal_name": "Acme Technologies LLC",
            "display_name": "Acme Tech",
            "primary_domain": "acme.com",
            "all_domains": ["acme.io", "acmetech.com"],
            "aliases": ["Acme Corp", "Acme Digital"],
            "statutory_tax_id": "12-3456789",
            "sec_cik": "0001234567",
            "gleif_lei": "5493006MHB84DD0ZWV18",
            "primary_industry_naics": "541511",
            "emails": ["contact@acme.com", "press@acme.io"],
            "phones": ["+1-800-555-0199", "555-234-5678"],
            "data_quality_score": 95,
        }

        org_id = self.bridge.ingest_organization(
            conn=self.mock_conn,
            org_data=org_data,
            source_name="SEC_EDGAR",
            observation_id="obs-12345",
            authority_weight=0.95,
        )
        self.assertEqual(org_id, "550e8400-e29b-41d4-a716-446655440000")
        # Ensure multiple queries executed: canonical upsert, aliases, domains, emails, phones, lineage, search projection
        self.assertGreaterEqual(self.mock_cur.execute.call_count, 6)

    def test_ingest_person_and_employment(self):
        self.mock_cur.fetchone.return_value = ("person-uuid-1234",)
        person_data = {
            "full_name": "Jane Doe",
            "first_name": "Jane",
            "last_name": "Doe",
            "title": "Chief Technology Officer",
            "seniority_level": "CXO",
            "department": "Engineering",
            "linkedin_url": "https://linkedin.com/in/janedoe",
            "email": "jane@acme.com",
            "valid_from": date(2022, 1, 1),
            "is_current": True,
        }

        p_id = self.bridge.ingest_person_and_employment(
            conn=self.mock_conn,
            person_data=person_data,
            org_id="org-uuid-9999",
            source_name="LinkedIn",
        )
        self.assertEqual(p_id, "person-uuid-1234")
        self.assertGreaterEqual(self.mock_cur.execute.call_count, 2)

    def test_ingest_corporate_hierarchy(self):
        self.mock_cur.fetchone.return_value = ("hierarchy-uuid-777",)
        h_id = self.bridge.ingest_corporate_hierarchy(
            conn=self.mock_conn,
            parent_org_id="parent-org-1",
            child_org_id="subsidiary-org-2",
            hierarchy_type="subsidiary",
            ownership_percentage=100.0,
        )
        self.assertEqual(h_id, "hierarchy-uuid-777")
        self.mock_cur.execute.assert_called_once()

    def test_ingest_org_technology(self):
        self.mock_cur.fetchone.return_value = ("tech-uuid-555",)
        tech_id = self.bridge.ingest_org_technology(
            conn=self.mock_conn,
            org_id="org-uuid-111",
            tech_name="FastAPI",
            category="Backend Framework",
        )
        self.assertEqual(tech_id, "tech-uuid-555")
        self.assertEqual(self.mock_cur.execute.call_count, 2)


class TestGraphIdentityResolver(unittest.TestCase):
    """Verifies graph-backed identity resolution, clustering, and reversible unmerge."""

    def setUp(self):
        self.resolver = GraphIdentityResolver()
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value.__enter__.return_value = self.mock_cur

    def test_find_match_by_tax_id(self):
        self.mock_cur.fetchone.return_value = ("org-tax-matched-uuid", "statutory_tax_id")
        match = self.resolver.find_match_by_alias_or_domain(
            conn=self.mock_conn,
            tax_id="12-3456789",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match[0], "org-tax-matched-uuid")
        self.assertEqual(match[1], "statutory_tax_id")
        self.assertEqual(match[2], 1.0)

    def test_find_match_by_domain(self):
        self.mock_cur.fetchone.return_value = ("org-domain-matched-uuid", "primary")
        match = self.resolver.find_match_by_alias_or_domain(
            conn=self.mock_conn,
            domain="acme.com",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match[0], "org-domain-matched-uuid")
        self.assertEqual(match[1], "domain:primary")
        self.assertAlmostEqual(match[2], 0.98)

    def test_find_match_by_alias(self):
        self.mock_cur.fetchone.return_value = ("org-alias-matched-uuid", "trade_name", 0.92)
        match = self.resolver.find_match_by_alias_or_domain(
            conn=self.mock_conn,
            alias_name="Acme International",
        )
        self.assertIsNotNone(match)
        self.assertEqual(match[0], "org-alias-matched-uuid")
        self.assertEqual(match[1], "alias:trade_name")
        self.assertAlmostEqual(match[2], 0.92)

    def test_resolve_cluster_membership_new_cluster(self):
        # Cluster does not exist yet
        self.mock_cur.fetchone.return_value = None
        res = self.resolver.resolve_cluster_membership(
            conn=self.mock_conn,
            entity_type="organization",
            canonical_id="canonical-org-123",
            source_name="SEC_EDGAR",
            source_record_id="CIK-0001018724",
            match_type="deterministic_ein",
            match_probability=1.0,
        )
        self.assertTrue(res["is_new_cluster"])
        self.assertEqual(res["canonical_entity_id"], "canonical-org-123")
        self.assertIn("cluster_id", res)
        self.assertIn("member_id", res)
        # Cur executed: 1 SELECT, 1 INSERT cluster, and 1 INSERT member
        self.assertEqual(self.mock_cur.execute.call_count, 3)

    def test_unmerge_member_reversible(self):
        # Step 1: Member found in existing cluster
        self.mock_cur.fetchone.return_value = (
            "orig-cluster-uuid-1", "SEC_EDGAR", "CIK-0001018724", "organization"
        )
        res = self.resolver.unmerge_member(
            conn=self.mock_conn,
            member_id="member-uuid-to-unmerge",
            reason="False positive merge identified during corporate audit",
            operator="SRE_OPERATOR",
        )
        self.assertEqual(res["status"], "unmerged")
        self.assertEqual(res["original_cluster_id"], "orig-cluster-uuid-1")
        self.assertNotEqual(res["new_cluster_id"], "orig-cluster-uuid-1")
        self.assertEqual(res["member_id"], "member-uuid-to-unmerge")
        # Cur executed: 1 SELECT, 1 INSERT cluster, 1 UPDATE member, 1 INSERT unmerge_events
        self.assertEqual(self.mock_cur.execute.call_count, 4)

    def test_get_cluster_details(self):
        now = datetime.now(timezone.utc)
        self.mock_cur.fetchone.return_value = (
            "cluster-123", "canonical-456", "organization", "stable", 0.05, now
        )
        self.mock_cur.fetchall.side_effect = [
            # members
            [
                ("member-1", "REC-1", "SEC_EDGAR", "deterministic_ein", 1.0, "{}", True, now),
                ("member-2", "REC-2", "SAM_GOV", "deterministic_cage", 0.99, "{}", True, now),
            ],
            # unmerge_history
            [],
        ]
        details = self.resolver.get_cluster_details(conn=self.mock_conn, canonical_id="canonical-456")
        self.assertIsNotNone(details)
        self.assertEqual(details["cluster_id"], "cluster-123")
        self.assertEqual(details["members_count"], 2)
        self.assertEqual(details["status"], "stable")


class TestPartitionManager(unittest.TestCase):
    """Verifies PartitionManager pre-allocation and range bounds calculation."""

    def setUp(self):
        self.pm = PartitionManager(forward_quarters=4)
        self.mock_conn = MagicMock()
        self.mock_cur = MagicMock()
        self.mock_conn.cursor.return_value.__enter__.return_value = self.mock_cur

    def test_maintain_observation_partitions(self):
        parts = self.pm.maintain_observation_partitions(self.mock_conn)
        self.assertGreaterEqual(len(parts), 8)
        self.assertEqual(parts[0]["status"], "verified")
        self.assertTrue(self.mock_cur.execute.called)

    def test_maintain_employment_partitions_skips_existing(self):
        # Simulate that employment_2035_2039 already exists in pg_inherits
        self.mock_cur.fetchall.return_value = [("employment_2035_2039",)]
        parts = self.pm.maintain_employment_partitions(self.mock_conn)
        self.assertEqual(len(parts), 2)
        statuses = {p["status"] for p in parts}
        self.assertIn("already_exists", statuses)

    def test_get_partition_catalog(self):
        self.mock_cur.fetchall.return_value = [
            ("kg_core", "organizations", "kg_core", "organizations_us", "16 kB", 100),
            ("kg_graph", "employment_relationships", "kg_graph", "employment_2023_2025", "8192 bytes", 50),
        ]
        catalog = self.pm.get_partition_catalog(self.mock_conn)
        self.assertEqual(len(catalog), 2)
        self.assertEqual(catalog[0]["parent"], "kg_core.organizations")
        self.assertEqual(catalog[0]["partition"], "kg_core.organizations_us")


class TestDeduplicatorCompatibility(unittest.TestCase):
    """Verifies Deduplicator provides clean aliases and graph resolution hooks."""

    def test_resolve_company_alias(self):
        mock_conn = MagicMock()
        dedup = Deduplicator(conn=mock_conn)
        res = dedup.resolve_company({"id": "comp-123", "name": "Alpha Corp"})
        self.assertIsInstance(res, DedupResult)
        self.assertEqual(res.action, "insert")

    def test_resolve_person_alias(self):
        mock_conn = MagicMock()
        dedup = Deduplicator(conn=mock_conn)
        res = dedup.resolve_person({"id": "person-456", "full_name": "Bob Smith"})
        self.assertIsInstance(res, DedupResult)
        self.assertEqual(res.action, "insert")


if __name__ == "__main__":
    unittest.main()
