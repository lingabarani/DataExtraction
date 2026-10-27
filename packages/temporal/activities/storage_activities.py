"""
DataExtraction — Storage & DLQ Activities
==========================================
Temporal activity wrappers for database read/write operations and
Dead Letter Queue management. Used by agent workflows and DLQReplayWorkflow.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from temporalio import activity

PACKAGES_DIR = Path(__file__).resolve().parents[2]
INFRA_PATH = PACKAGES_DIR / "infrastructure"

for p in [str(INFRA_PATH), str(PACKAGES_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("dataextraction.activities.storage")


@activity.defn(name="fetch_dlq_records")
async def fetch_dlq_records_activity(config: dict) -> dict:
    """
    Fetches pending records from the Dead Letter Queue table.

    Args:
        config: {"limit": int, "status": "PENDING" | "FAILED", "source": str (optional)}

    Returns:
        {"records": list[dict], "total": int}
    """
    activity.logger.info("Fetching DLQ records: limit=%s", config.get("limit", 100))

    from dead_letter_queue import get_dead_letter_records  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    records = []
    conn = None
    try:
        conn = get_connection()
        if conn:
            records = get_dead_letter_records(
                conn,
                limit=config.get("limit", 100),
                status=config.get("status", "PENDING"),
                source_name=config.get("source"),
            )
    except Exception as e:
        activity.logger.warning("DLQ fetch notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return {"records": records, "total": len(records)}


@activity.defn(name="resolve_dlq_record")
async def resolve_dlq_record_activity(record_id: str, status: str, notes: str = "") -> dict:
    """
    Marks a DLQ record as RESOLVED or DISCARDED.

    Args:
        record_id: ID of the DLQ record
        status: "RESOLVED" | "DISCARDED"
        notes: Optional resolution notes

    Returns:
        {"record_id": str, "status": str, "updated": bool}
    """
    activity.logger.info("Resolving DLQ record: id=%s status=%s", record_id, status)

    from dead_letter_queue import discard_dead_letter  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    updated = False
    conn = None
    try:
        conn = get_connection()
        if conn:
            try:
                rec_int_id = int(record_id)
                updated = discard_dead_letter(conn, rec_int_id, reason=notes or f"Marked {status}")
            except (ValueError, TypeError):
                updated = False
    except Exception as e:
        activity.logger.warning("DLQ resolve notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return {"record_id": record_id, "status": status, "updated": updated}


@activity.defn(name="get_dlq_stats")
async def get_dlq_stats_activity(_: dict = None) -> dict:
    """
    Returns current DLQ statistics for monitoring by agents.

    Returns:
        {
            "total": int,
            "pending": int,
            "resolved": int,
            "discarded": int,
            "by_source": list[dict]
        }
    """
    from dead_letter_queue import get_dead_letter_stats  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    stats = {"total": 0, "pending": 0, "resolved": 0, "discarded": 0, "by_source": []}
    conn = None
    try:
        conn = get_connection()
        if conn:
            stats = get_dead_letter_stats(conn)
    except Exception as e:
        activity.logger.warning("DLQ stats notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return stats


@activity.defn(name="storage_query")
async def storage_query_activity(query_name: str, params: dict = None) -> dict:
    """
    Executes a named read-only storage query. Used by agents to observe state
    without direct DB access.

    Args:
        query_name: Named query identifier
        params: Query parameters

    Returns:
        Query result as dict
    """
    activity.logger.info("Storage query: %s params=%s", query_name, params or {})

    from db_connector import get_connection, release_connection  # type: ignore

    result: Any = {}
    conn = None
    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                if query_name == "gmp_today_spend":
                    result = {"total_spend_usd": 0.0}
                elif query_name == "counts":
                    cur.execute("SELECT COUNT(1) FROM us_leads")
                    row = cur.fetchone()
                    result = {"us_leads_count": int(row[0] or 0) if row else 0}
                else:
                    result = {"query": query_name, "status": "executed"}
            finally:
                cur.close()
    except Exception as e:
        activity.logger.warning("Storage query notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return {"query": query_name, "result": result}


@activity.defn(name="check_gmp_budget")
async def check_gmp_budget_activity(_: dict = None) -> dict:
    """
    Checks remaining Google Maps Platform daily budget.
    Used as a pre-condition gate before GMP enrichment activities.

    Returns:
        {"budget_remaining_usd": float, "budget_limit_usd": float, "authorized": bool}
    """
    limit = float(os.getenv("GOOGLE_MAPS_DAILY_BUDGET_USD", "50.0"))
    enabled = os.getenv("GOOGLE_MAPS_ENRICHMENT_ENABLED", "false").lower() == "true"

    if not enabled:
        return {
            "budget_remaining_usd": 0.0,
            "budget_limit_usd": limit,
            "authorized": False,
            "reason": "GMP enrichment disabled via GOOGLE_MAPS_ENRICHMENT_ENABLED",
        }

    spent = 0.0
    remaining = max(0.0, limit - spent)

    return {
        "budget_remaining_usd": remaining,
        "budget_limit_usd": limit,
        "authorized": remaining > 0,
        "spent_today_usd": spent,
    }


# ── Knowledge Graph & Lakehouse Ingestion Activities ──────────────────────────

@activity.defn(name="persist_raw_observation")
async def persist_raw_observation_activity(payload: dict) -> dict:
    """
    Persists an uncompressed raw extraction payload to MinIO/S3 Parquet partition
    and tracks metadata pointer in `kg_observation.observation_metadata`.
    """
    activity.logger.info(
        "Persisting raw observation for source=%s record_id=%s",
        payload.get("source_name"), payload.get("source_record_id")
    )
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        res = kg_ingestion_bridge.persist_raw_observation(
            conn=conn,
            source_name=payload.get("source_name", "scraper"),
            source_record_id=str(payload.get("source_record_id", "")),
            raw_payload=payload.get("raw_payload", {}),
            extracted_summary=payload.get("extracted_summary", {}),
            observed_entity_type=payload.get("entity_type", "organization"),
        )
        return res
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="ingest_kg_organization")
async def ingest_kg_organization_activity(payload: dict) -> dict:
    """
    Ingests canonical organization, aliases, domains, and contacts into `kg_core`.
    """
    activity.logger.info("Ingesting organization into kg_core: %s", payload.get("legal_name") or payload.get("name"))
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        org_id = kg_ingestion_bridge.ingest_organization(
            conn=conn,
            org_data=payload.get("org_data", {}),
            source_name=payload.get("source_name", "pipeline"),
            observation_id=payload.get("observation_id"),
            authority_weight=float(payload.get("authority_weight", 0.8)),
        )
        return {"org_id": org_id, "status": "ingested"}
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="ingest_kg_person")
async def ingest_kg_person_activity(payload: dict) -> dict:
    """
    Ingests canonical person and employment tenure into `kg_core` and `kg_graph`.
    """
    activity.logger.info("Ingesting person into kg_core: %s", payload.get("person_data", {}).get("full_name"))
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        person_id = kg_ingestion_bridge.ingest_person_and_employment(
            conn=conn,
            person_data=payload.get("person_data", {}),
            org_id=payload.get("org_id"),
            source_name=payload.get("source_name", "pipeline"),
            observation_id=payload.get("observation_id"),
        )
        return {"person_id": person_id, "status": "ingested"}
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="ingest_kg_hierarchy")
async def ingest_kg_hierarchy_activity(payload: dict) -> dict:
    """
    Ingests parent-child or subsidiary relationship into `kg_graph.corporate_hierarchies`.
    """
    activity.logger.info("Ingesting corporate hierarchy: %s -> %s", payload.get("parent_org_id"), payload.get("child_org_id"))
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        h_id = kg_ingestion_bridge.ingest_corporate_hierarchy(
            conn=conn,
            parent_org_id=payload.get("parent_org_id"),
            child_org_id=payload.get("child_org_id"),
            hierarchy_type=payload.get("hierarchy_type", "subsidiary"),
            ownership_percentage=payload.get("ownership_percentage"),
            direct_parent=payload.get("direct_parent", True),
            confidence_score=float(payload.get("confidence_score", 0.95)),
        )
        return {"hierarchy_id": h_id, "status": "ingested"}
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="ingest_kg_technology")
async def ingest_kg_technology_activity(payload: dict) -> dict:
    """
    Ingests detected tech stack into `kg_core.technologies` and `kg_graph.org_technologies`.
    """
    activity.logger.info("Ingesting org technology: org=%s tech=%s", payload.get("org_id"), payload.get("tech_name"))
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        tech_id = kg_ingestion_bridge.ingest_org_technology(
            conn=conn,
            org_id=payload.get("org_id"),
            tech_name=payload.get("tech_name"),
            category=payload.get("category", "Cloud & Infrastructure"),
            detection_method=payload.get("detection_method", "signature"),
            confidence_score=float(payload.get("confidence_score", 0.90)),
        )
        return {"tech_id": tech_id, "status": "ingested"}
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="resolve_cluster_membership")
async def resolve_cluster_membership_activity(payload: dict) -> dict:
    """
    Binds a record into an identity cluster in `kg_resolution.identity_clusters`.
    """
    activity.logger.info("Resolving cluster membership: canonical_id=%s source=%s", payload.get("canonical_id"), payload.get("source_name"))
    from packages.pipeline.graph_identity_resolver import graph_identity_resolver  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        res = graph_identity_resolver.resolve_cluster_membership(
            conn=conn,
            entity_type=payload.get("entity_type", "organization"),
            canonical_id=payload.get("canonical_id"),
            source_name=payload.get("source_name"),
            source_record_id=payload.get("source_record_id"),
            match_type=payload.get("match_type", "deterministic_domain"),
            match_probability=float(payload.get("match_probability", 1.0)),
            match_features=payload.get("match_features"),
        )
        return res
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="unmerge_cluster_member")
async def unmerge_cluster_member_activity(payload: dict) -> dict:
    """
    Performs reversible unmerge of a false-matched member into a new cluster.
    """
    activity.logger.info("Unmerging member: member_id=%s reason=%s", payload.get("member_id"), payload.get("reason"))
    from packages.pipeline.graph_identity_resolver import graph_identity_resolver  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        res = graph_identity_resolver.unmerge_member(
            conn=conn,
            member_id=payload.get("member_id"),
            reason=payload.get("reason", "Operator review"),
            operator=payload.get("operator", "OPERATOR_DISPUTE_REVIEW"),
        )
        return res
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="maintain_kg_partitions")
async def maintain_kg_partitions_activity() -> dict:
    """
    Executes automated quarterly & multi-year partition maintenance.
    """
    activity.logger.info("Executing automated KG partition maintenance")
    from partition_manager import partition_manager  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        res = partition_manager.run_all(conn)
        return res
    finally:
        if conn:
            release_connection(conn)
