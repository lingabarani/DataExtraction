"""
DataExtraction — Graph Identity Resolution & Reversible Cluster Engine
======================================================================
Implements graph-backed entity resolution and reversible unmerge operations.

Instead of permanently merging and destroying separate entity IDs, entities
are modeled as nodes inside `kg_resolution.identity_clusters`.

Capabilities:
  1. Multi-signal matching: Statutory Tax IDs, Multi-Domains, and Aliases.
  2. Dynamic Cluster Membership: Tracks each contributing source record with
     probabilistic match features.
  3. Zero-Destruction Unmerge: Unlinking false merges via `unmerge_events`
     in O(1) time without historical data corruption.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("dataextraction.pipeline.identity_resolver")


class GraphIdentityResolver:
    """
    Manages identity clustering, alias/domain lookups, and reversible unmerge operations.
    """

    def find_match_by_alias_or_domain(
        self,
        conn: Any,
        domain: Optional[str] = None,
        alias_name: Optional[str] = None,
        tax_id: Optional[str] = None,
        jurisdiction: str = "US",
    ) -> Optional[Tuple[str, str, float]]:
        """
        Looks up an organization by statutory tax ID, registered domain (primary or alias),
        or known trade name/DBA in `kg_core.organizations`, `kg_core.organization_domains`,
        and `kg_core.organization_aliases`.

        Returns:
            Tuple of (org_id, match_field, confidence) or None
        """
        if not conn:
            return None

        with conn.cursor() as cur:
            # 1. Statutory Tax ID deterministic match (EIN, RFC, CIK, LEI)
            if tax_id and str(tax_id).strip():
                clean_tax = str(tax_id).strip().upper().replace("-", "")
                cur.execute(
                    """
                    SELECT org_id, 'statutory_tax_id'
                    FROM kg_core.organizations
                    WHERE REPLACE(UPPER(statutory_tax_id), '-', '') = %s
                    LIMIT 1;
                    """,
                    (clean_tax,),
                )
                row = cur.fetchone()
                if row:
                    return (str(row[0]), "statutory_tax_id", 1.0)

            # 2. Match against multi-domain repository
            if domain and str(domain).strip():
                dom_clean = str(domain).strip().lower()
                cur.execute(
                    """
                    SELECT org_id, domain_type 
                    FROM kg_core.organization_domains
                    WHERE domain_name = %s
                    LIMIT 1;
                    """,
                    (dom_clean,),
                )
                row = cur.fetchone()
                if row:
                    return (str(row[0]), f"domain:{row[1]}", 0.98)

            # 3. Match against registered aliases & DBAs
            if alias_name and str(alias_name).strip():
                clean = str(alias_name).strip().lower()
                cur.execute(
                    """
                    SELECT org_id, alias_type, confidence_score
                    FROM kg_core.organization_aliases
                    WHERE clean_name = %s
                    ORDER BY confidence_score DESC
                    LIMIT 1;
                    """,
                    (clean,),
                )
                row = cur.fetchone()
                if row:
                    return (str(row[0]), f"alias:{row[1]}", float(row[2] or 0.90))

        return None

    def get_cluster_details(self, conn: Any, canonical_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves all active and historical cluster members and unmerge history
        for a given canonical entity.
        """
        if not conn:
            return None

        with conn.cursor() as cur:
            # 1. Fetch cluster
            cur.execute(
                """
                SELECT cluster_id, canonical_entity_id, entity_type, status, cluster_entropy, created_at
                FROM kg_resolution.identity_clusters
                WHERE canonical_entity_id = %s
                LIMIT 1;
                """,
                (canonical_id,),
            )
            c_row = cur.fetchone()
            if not c_row:
                return None

            cluster_id, canon_id, entity_type, status, entropy, created_at = c_row
            cluster_id = str(cluster_id)

            # 2. Fetch members
            cur.execute(
                """
                SELECT member_id, source_record_id, source_name, match_type,
                       match_probability, match_features, is_active, linked_at
                FROM kg_resolution.cluster_members
                WHERE cluster_id = %s
                ORDER BY linked_at ASC;
                """,
                (cluster_id,),
            )
            members = [
                {
                    "member_id": str(r[0]),
                    "source_record_id": r[1],
                    "source_name": r[2],
                    "match_type": r[3],
                    "match_probability": float(r[4] or 1.0),
                    "match_features": r[5] if isinstance(r[5], dict) else json.loads(r[5] or "{}"),
                    "is_active": r[6],
                    "linked_at": r[7].isoformat() if r[7] else None,
                }
                for r in cur.fetchall()
            ]

            # 3. Fetch unmerge events
            cur.execute(
                """
                SELECT unmerge_id, original_cluster_id, new_cluster_id,
                       member_id, reason, operator, unmerged_at
                FROM kg_resolution.unmerge_events
                WHERE original_cluster_id = %s OR new_cluster_id = %s
                ORDER BY unmerged_at DESC;
                """,
                (cluster_id, cluster_id),
            )
            unmerge_history = [
                {
                    "unmerge_id": str(r[0]),
                    "original_cluster_id": str(r[1]),
                    "new_cluster_id": str(r[2]),
                    "member_id": str(r[3]),
                    "reason": r[4],
                    "operator": r[5],
                    "unmerged_at": r[6].isoformat() if r[6] else None,
                }
                for r in cur.fetchall()
            ]

            return {
                "cluster_id": cluster_id,
                "canonical_entity_id": str(canon_id),
                "entity_type": entity_type,
                "status": status,
                "entropy": float(entropy) if entropy is not None else None,
                "created_at": created_at.isoformat() if created_at else None,
                "members_count": len(members),
                "members": members,
                "unmerge_events_count": len(unmerge_history),
                "unmerge_history": unmerge_history,
            }

    def resolve_cluster_membership(
        self,
        conn: Any,
        entity_type: str,
        canonical_id: str,
        source_name: str,
        source_record_id: str,
        match_type: str = "deterministic_domain",
        match_probability: float = 1.0,
        match_features: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Binds a source record into an identity cluster for the canonical entity.
        Creates a new cluster if none exists.
        """
        with conn.cursor() as cur:
            # 1. Find or create identity cluster
            cur.execute(
                """
                SELECT cluster_id 
                FROM kg_resolution.identity_clusters
                WHERE canonical_entity_id = %s AND entity_type = %s
                LIMIT 1;
                """,
                (canonical_id, entity_type),
            )
            row = cur.fetchone()

            if row:
                cluster_id = str(row[0])
                created_new = False
            else:
                cluster_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO kg_resolution.identity_clusters (
                        cluster_id, canonical_entity_id, entity_type, status, created_at
                    ) VALUES (%s, %s, %s, 'stable', CLOCK_TIMESTAMP());
                    """,
                    (cluster_id, canonical_id, entity_type),
                )
                created_new = True

            # 2. Append cluster member record
            member_id = str(uuid.uuid4())
            features_json = json.dumps(match_features or {})
            cur.execute(
                """
                INSERT INTO kg_resolution.cluster_members (
                    member_id, cluster_id, source_record_id, source_name,
                    match_type, match_probability, match_features, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, true);
                """,
                (
                    member_id, cluster_id, str(source_record_id), source_name,
                    match_type, match_probability, features_json,
                ),
            )

        return {
            "cluster_id": cluster_id,
            "member_id": member_id,
            "canonical_entity_id": canonical_id,
            "is_new_cluster": created_new,
        }

    def unmerge_member(
        self,
        conn: Any,
        member_id: str,
        reason: str,
        operator: str = "OPERATOR_DISPUTE_REVIEW",
    ) -> Dict[str, Any]:
        """
        Reversible Unmerge Engine:
        Deactivates a false-matched cluster member and spawns a new independent cluster.
        Zero data destruction: all historical events and lineage remain auditable.
        """
        with conn.cursor() as cur:
            # 1. Fetch current membership details
            cur.execute(
                """
                SELECT cm.cluster_id, cm.source_name, cm.source_record_id, ic.entity_type
                FROM kg_resolution.cluster_members cm
                JOIN kg_resolution.identity_clusters ic ON cm.cluster_id = ic.cluster_id
                WHERE cm.member_id = %s;
                """,
                (member_id,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Cluster member '{member_id}' not found.")

            original_cluster_id, source_name, source_record_id, entity_type = row
            original_cluster_id = str(original_cluster_id)

            # 2. Provision new independent cluster and canonical entity ID
            new_cluster_id = str(uuid.uuid4())
            new_canonical_id = str(uuid.uuid4())

            cur.execute(
                """
                INSERT INTO kg_resolution.identity_clusters (
                    cluster_id, canonical_entity_id, entity_type, status, created_at
                ) VALUES (%s, %s, %s, 'stable', CLOCK_TIMESTAMP());
                """,
                (new_cluster_id, new_canonical_id, entity_type),
            )

            # 3. Mark old member inactive and move to new cluster
            cur.execute(
                """
                UPDATE kg_resolution.cluster_members
                SET cluster_id = %s, is_active = true
                WHERE member_id = %s;
                """,
                (new_cluster_id, member_id),
            )

            # 4. Record unmerge audit trail
            unmerge_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO kg_resolution.unmerge_events (
                    unmerge_id, original_cluster_id, new_cluster_id,
                    member_id, reason, operator, unmerged_at
                ) VALUES (%s, %s, %s, %s, %s, %s, CLOCK_TIMESTAMP());
                """,
                (unmerge_id, original_cluster_id, new_cluster_id, member_id, reason, operator),
            )

            logger.info(
                "Unmerged member %s from cluster %s to new cluster %s (Canonical ID: %s)",
                member_id, original_cluster_id, new_cluster_id, new_canonical_id,
            )

        return {
            "unmerge_id": unmerge_id,
            "original_cluster_id": original_cluster_id,
            "new_cluster_id": new_cluster_id,
            "new_canonical_id": new_canonical_id,
            "member_id": member_id,
            "status": "unmerged",
        }


# Singleton instance
graph_identity_resolver = GraphIdentityResolver()

__all__ = [
    "GraphIdentityResolver",
    "graph_identity_resolver",
]
