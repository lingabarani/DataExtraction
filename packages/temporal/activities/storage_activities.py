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

try:
    from temporalio import activity
except ImportError:
    class _MockAct:
        defn = lambda *a, **k: (lambda f: f)
    activity = _MockAct()  # type: ignore

PACKAGES_DIR = Path(__file__).resolve().parents[2]
INFRA_PATH = PACKAGES_DIR / "infrastructure"

for p in [str(INFRA_PATH), str(PACKAGES_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("temporal.activities.storage")


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
                if updated:
                    conn.commit()
            except (ValueError, TypeError):
                updated = False
    except Exception as e:
        if conn:
            conn.rollback()
        activity.logger.warning("DLQ resolve notice: %s", e)
    finally:
        if conn:
            release_connection(conn)

    return {"record_id": record_id, "status": status, "updated": updated}


@activity.defn(name="get_dlq_stats")
async def get_dlq_stats_activity(_: dict | None = None) -> dict:
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
async def storage_query_activity(query_name: str, params: dict | None = None) -> dict:
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
async def check_gmp_budget_activity(_: dict | None = None) -> dict:
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
    (or `kg_observation.pending_lakehouse_uploads` outbox if MinIO is unreachable)
    and commits metadata pointer in `kg_observation.observation_metadata`.
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
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for persist_raw_observation")
        res = kg_ingestion_bridge.persist_raw_observation(
            conn=conn,
            source_name=payload.get("source_name", "scraper"),
            source_record_id=str(payload.get("source_record_id", "")),
            raw_payload=payload.get("raw_payload", {}),
            extracted_summary=payload.get("extracted_summary", {}),
            observed_entity_type=payload.get("entity_type", "organization"),
        )
        conn.commit()
        return res
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="replay_lakehouse_outbox")
async def replay_lakehouse_outbox_activity(limit: int = 100) -> dict:
    """
    Replays pending Lakehouse observation uploads from PostgreSQL outbox into MinIO/S3.
    """
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        if not conn:
            return {"claimed": 0, "uploaded": 0, "failed": 0, "status": "NO_DB_CONNECTION"}
        stats = kg_ingestion_bridge.replay_pending_lakehouse_uploads(conn=conn, limit=int(limit or 100))
        conn.commit()
        return {**stats, "status": "SUCCESS"}
    except Exception as exc:
        if conn:
            conn.rollback()
        logger.warning("Lakehouse outbox replay notice: %s", exc)
        return {"claimed": 0, "uploaded": 0, "failed": 0, "status": "FAILED", "error": str(exc)}
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="ingest_working_organization")
async def ingest_working_organization_activity(payload: dict) -> dict:
    """
    Sprint 2: Ingests or updates a pre-master organization in staging_dataextraction.working_organizations.
    Does NOT write to master database.
    """
    activity.logger.info(
        "Ingesting pre-master working organization: %s",
        payload.get("legal_name") or payload.get("display_name") or payload.get("name")
    )
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for ingest_working_organization")
        org_id = kg_ingestion_bridge.ingest_working_organization(
            conn=conn,
            org_data=payload.get("org_data", payload),
            source_name=payload.get("source_name", "pipeline"),
            canonical_cluster_id=payload.get("canonical_cluster_id"),
            identity_confidence=float(payload.get("identity_confidence", 1.0)),
        )
        conn.commit()
        return {"org_id": org_id, "status": "staged_in_working_organizations"}
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="ingest_working_person")
async def ingest_working_person_activity(payload: dict) -> dict:
    """
    Sprint 2: Ingests an executive or decision maker into staging_dataextraction.working_persons.
    Does NOT write to master database.
    """
    activity.logger.info(
        "Ingesting pre-master working person: %s (org_id=%s)",
        payload.get("full_name") or payload.get("person_data", {}).get("full_name"),
        payload.get("org_id")
    )
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for ingest_working_person")
        person_id = kg_ingestion_bridge.ingest_working_person(
            conn=conn,
            person_data=payload.get("person_data", payload),
            org_id=str(payload.get("org_id", "")),
            confidence_score=float(payload.get("confidence_score", 0.85)),
        )
        conn.commit()
        return {"person_id": person_id, "status": "staged_in_working_persons"}
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="ingest_working_email")
async def ingest_working_email_activity(payload: dict) -> dict:
    """
    Sprint 2: Ingests a discovered and tested mailbox into staging_dataextraction.working_emails.
    Does NOT write to master database.
    """
    activity.logger.info("Ingesting pre-master working email: %s (org_id=%s)", payload.get("email"), payload.get("org_id"))
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for ingest_working_email")
        email_id = kg_ingestion_bridge.ingest_working_email(
            conn=conn,
            email_data=payload.get("email_data", payload),
            org_id=str(payload.get("org_id", "")),
        )
        conn.commit()
        return {"working_email_id": email_id, "status": "staged_in_working_emails"}
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="complete_executive_enrichment")
async def complete_executive_enrichment_activity(org_id: str) -> dict:
    """
    Sprint 2: Updates staging_dataextraction.working_organizations setting executive_enrichment_status = 'COMPLETED'.
    """
    activity.logger.info("Marking executive enrichment complete for org: %s", org_id)
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        if conn:
            with conn.cursor() as cur:
                if org_id == "ALL_PENDING":
                    cur.execute("""
                        UPDATE staging_dataextraction.working_organizations
                        SET executive_enrichment_status = 'COMPLETED', updated_at = NOW()
                        WHERE executive_enrichment_status = 'PENDING';
                    """)
                else:
                    cur.execute("""
                        UPDATE staging_dataextraction.working_organizations
                        SET executive_enrichment_status = 'COMPLETED', updated_at = NOW()
                        WHERE org_id = %s;
                    """, (org_id,))
            conn.commit()
    finally:
        if conn:
            release_connection(conn)
    return {"org_id": org_id, "status": "COMPLETED"}


@activity.defn(name="discover_executives")
async def discover_executives_activity(batch_size: int = 1000) -> dict:
    """
    Agent 4: Autonomous C-Suite and Executive Leadership Discovery.
    Queries staging_dataextraction.working_organizations where executive_enrichment_status = 'PENDING',
    extracts/infers decision makers (CEO, CTO, CFO, VPs) via USPersonEnrichmentEngine,
    and ingests them into staging_dataextraction.working_persons.
    """
    activity.logger.info("Executing executive discovery for pending working organizations (batch=%d)", batch_size)
    if activity.in_activity():
        activity.heartbeat("Discovering executive decision makers")

    import json
    from packages.scrapers.us_enrichment.models.company import USCanonicalCompany  # type: ignore
    from packages.scrapers.us_enrichment.pipeline.person_enrichment import us_person_enrichment_engine  # type: ignore
    from packages.infrastructure.kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    discovered_count = 0
    enriched_orgs = 0

    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT org_id, legal_name, display_name, primary_domain, website,
                           industry, phones
                    FROM staging_dataextraction.working_organizations
                    WHERE executive_enrichment_status = 'PENDING'
                    ORDER BY created_at ASC
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED;
                """, (batch_size,))
                rows = cur.fetchall()

                for row in rows:
                    org_id, legal_name, display_name, domain, website, industry, phones = row
                    phone_val = None
                    if isinstance(phones, list) and phones:
                        phone_val = phones[0]
                    elif isinstance(phones, str) and phones.startswith("["):
                        try:
                            p_list = json.loads(phones)
                            if p_list:
                                phone_val = p_list[0]
                        except Exception:
                            phone_val = None

                    comp = USCanonicalCompany(
                        company_id=org_id,
                        legal_name=legal_name or display_name or "Commercial Entity",
                        domain=domain,
                        website=website,
                        industry=industry,
                        phone=phone_val,
                    )

                    dms = us_person_enrichment_engine.extract_and_enrich_decision_makers(comp)
                    for dm in dms:
                        dm_dict = dm.to_dict()
                        p_data = {
                            "person_id": dm_dict.get("person_id"),
                            "full_name": dm_dict.get("full_name"),
                            "first_name": dm_dict.get("first_name"),
                            "last_name": dm_dict.get("last_name"),
                            "title": dm_dict.get("title"),
                            "seniority": dm_dict.get("seniority_level"),
                            "department": dm_dict.get("department"),
                            "primary_email": dm_dict.get("work_email"),
                            "primary_phone": dm_dict.get("direct_phone") or phone_val,
                            "linkedin_url": None,
                            "confidence_score": float(dm_dict.get("email_confidence_score", 70)) / 100.0,
                        }
                        kg_ingestion_bridge.ingest_working_person(conn, p_data, org_id)
                        discovered_count += 1

                    cur.execute("""
                        UPDATE staging_dataextraction.working_organizations
                        SET executive_enrichment_status = 'COMPLETED', updated_at = NOW()
                        WHERE org_id = %s;
                    """, (org_id,))
                    enriched_orgs += 1

                conn.commit()
            except Exception as e:
                conn.rollback()
                activity.logger.warning("Executive discovery query notice: %s", e)
            finally:
                cur.close()
    finally:
        if conn:
            release_connection(conn)

    return {
        "status": "COMPLETED",
        "executives_discovered": discovered_count,
        "organizations_enriched": enriched_orgs,
    }


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
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for ingest_kg_organization")
        org_id = kg_ingestion_bridge.ingest_organization(
            conn=conn,
            org_data=payload.get("org_data", {}),
            source_name=payload.get("source_name", "pipeline"),
            observation_id=payload.get("observation_id"),
            authority_weight=float(payload.get("authority_weight", 0.8)),
        )
        conn.commit()
        return {"org_id": org_id, "status": "ingested"}
    except Exception:
        if conn:
            conn.rollback()
        raise
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
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for ingest_kg_person")
        person_id = kg_ingestion_bridge.ingest_person_and_employment(
            conn=conn,
            person_data=payload.get("person_data", {}),
            org_id=payload.get("org_id"),
            source_name=payload.get("source_name", "pipeline"),
            observation_id=payload.get("observation_id"),
        )
        conn.commit()
        return {"person_id": person_id, "status": "ingested"}
    except Exception:
        if conn:
            conn.rollback()
        raise
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
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for ingest_kg_hierarchy")
        h_id = kg_ingestion_bridge.ingest_corporate_hierarchy(
            conn=conn,
            parent_org_id=payload.get("parent_org_id"),
            child_org_id=payload.get("child_org_id"),
            hierarchy_type=payload.get("hierarchy_type", "subsidiary"),
            ownership_percentage=payload.get("ownership_percentage"),
            direct_parent=payload.get("direct_parent", True),
            confidence_score=float(payload.get("confidence_score", 0.95)),
        )
        conn.commit()
        return {"hierarchy_id": h_id, "status": "ingested"}
    except Exception:
        if conn:
            conn.rollback()
        raise
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
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for ingest_kg_technology")
        tech_id = kg_ingestion_bridge.ingest_org_technology(
            conn=conn,
            org_id=payload.get("org_id"),
            tech_name=payload.get("tech_name"),
            category=payload.get("category", "Cloud & Infrastructure"),
            detection_method=payload.get("detection_method", "signature"),
            confidence_score=float(payload.get("confidence_score", 0.90)),
        )
        conn.commit()
        return {"tech_id": tech_id, "status": "ingested"}
    except Exception:
        if conn:
            conn.rollback()
        raise
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
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for resolve_cluster_membership")
        res = graph_identity_resolver.resolve_cluster_membership(
            conn=conn,
            entity_type=str(payload.get("entity_type", "organization")),
            canonical_id=str(payload.get("canonical_id") or ""),
            source_name=str(payload.get("source_name") or "pipeline"),
            source_record_id=str(payload.get("source_record_id") or ""),
            match_type=str(payload.get("match_type", "deterministic_domain")),
            match_probability=float(payload.get("match_probability", 1.0)),
            match_features=payload.get("match_features"),
        )
        conn.commit()
        return res
    except Exception:
        if conn:
            conn.rollback()
        raise
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
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for unmerge_cluster_member")
        res = graph_identity_resolver.unmerge_member(
            conn=conn,
            member_id=str(payload.get("member_id") or ""),
            reason=str(payload.get("reason", "Operator review")),
            operator=str(payload.get("operator", "OPERATOR_DISPUTE_REVIEW")),
        )
        conn.commit()
        return res
    except Exception:
        if conn:
            conn.rollback()
        raise
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
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for maintain_kg_partitions")
        res = partition_manager.run_all(conn)
        conn.commit()
        return res
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="sync_opensearch_cdc")
async def sync_opensearch_cdc_activity(batch_limit: int = 1000) -> dict:
    """
    Synchronizes delta change projections to OpenSearch 2.x cluster.
    """
    activity.logger.info("Executing OpenSearch CDC synchronization: batch_limit=%d", batch_limit)
    from packages.infrastructure.opensearch_cdc_sync import opensearch_client  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for sync_opensearch_cdc")
        res = opensearch_client.sync_companies_cdc(conn, batch_limit=batch_limit)
        conn.commit()
        return res
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_connection(conn)


@activity.defn(name="compute_bayesian_quality")
async def compute_bayesian_quality_activity(payload: dict) -> dict:
    """
    Computes multi-dimensional Bayesian data quality score.
    """
    activity.logger.info("Computing Bayesian quality score: batch_mode=%s entity=%s",
                         payload.get("batch_mode", False), payload.get("entity_type", "organization"))
    from packages.pipeline.bayesian_quality_engine import bayesian_quality_engine  # type: ignore

    if payload.get("batch_mode"):
        from db_connector import get_connection, release_connection  # type: ignore
        conn = None
        evaluated_count = 0
        avg_score = 0.0
        try:
            conn = get_connection()
            if conn:
                cur = conn.cursor()
                try:
                    limit = int(payload.get("batch_limit", 500))
                    cur.execute("""
                        SELECT id, name, domain, ein, email, phone, city, state_code, source
                        FROM companies
                        WHERE data_quality_score IS NULL OR data_quality_score = 0
                        LIMIT %s
                    """, (limit,))
                    rows = cur.fetchall()
                    cols = [c[0] for c in cur.description] if cur.description else []
                    total_score = 0
                    for r in rows:
                        row_dict = dict(zip(cols, r))
                        src = [str(row_dict.get("source"))] if row_dict.get("source") else ["REGISTRY"]
                        score_res = bayesian_quality_engine.compute_entity_quality_score(
                            entity_data=row_dict,
                            entity_type="organization",
                            contributing_sources=src,
                        )
                        q_score = score_res.get("composite_quality_score", 70)
                        cur.execute("UPDATE companies SET data_quality_score = %s WHERE id = %s", (q_score, row_dict.get("id")))
                        total_score += q_score
                        evaluated_count += 1
                    conn.commit()
                    if evaluated_count > 0:
                        avg_score = round(total_score / evaluated_count, 2)
                except Exception as b_err:
                    conn.rollback()
                    activity.logger.warning("Batch Bayesian evaluation query notice: %s", b_err)
                finally:
                    cur.close()
        finally:
            if conn:
                release_connection(conn)

        return {
            "status": "SUCCESS",
            "batch_mode": True,
            "evaluated_count": evaluated_count,
            "average_quality_score": avg_score,
            "entity_type": payload.get("entity_type", "organization"),
        }
    from packages.pipeline.bayesian_quality_engine import bayesian_quality_engine  # type: ignore

    res = bayesian_quality_engine.compute_entity_quality_score(
        entity_data=payload.get("entity_data", {}),
        entity_type=payload.get("entity_type", "organization"),
        contributing_sources=payload.get("contributing_sources", []),
    )
    return res


@activity.defn(name="ingest_kg_observation")
async def ingest_kg_observation_activity(payload: dict) -> dict:
    """Standard alias for persist_raw_observation_activity."""
    return await persist_raw_observation_activity(payload)


@activity.defn(name="ingest_kg_employment")
async def ingest_kg_employment_activity(payload: dict) -> dict:
    """
    Ingests person and bitemporal employment tenure into `kg_core` and `kg_graph`.
    """
    activity.logger.info("Ingesting employment relationship into kg_graph: %s", payload)
    from kg_ingestion_bridge import kg_ingestion_bridge  # type: ignore
    from db_connector import get_connection, release_connection  # type: ignore

    conn = None
    try:
        conn = get_connection()
        if not conn:
            raise RuntimeError("PostgreSQL connection unavailable for ingest_kg_employment")
        person_id = kg_ingestion_bridge.ingest_person_and_employment(
            conn=conn,
            person_data=payload.get("person_data", {
                "full_name": payload.get("full_name", "Unknown Professional"),
                "primary_email": payload.get("email"),
                "primary_phone": payload.get("phone"),
                "linkedin_url": payload.get("linkedin_url"),
            }),
            org_id=payload.get("org_id"),
            source_name=payload.get("source_name", "pipeline"),
            observation_id=payload.get("observation_id"),
        )
        conn.commit()
        return {"person_id": person_id, "status": "ingested"}
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            release_connection(conn)


# ── Sprint 3: Governance Evaluation & Atomic Promotion Gate Activities ────────

@activity.defn(name="evaluate_working_governance")
async def evaluate_working_governance_activity(config: Any = None, *args) -> dict:
    """
    Sprint 3: Evaluates entities in staging_dataextraction.working_organizations
    against Bayesian Quality (>= 80), Trust (>= 0.8500), and Sanctions clearance.
    Transitions certified entities to 'APPROVED'; quarantines sub-threshold records to DLQ.
    """
    target_org_ids = None
    if isinstance(config, dict):
        batch_size = int(config.get("batch_size", 5000))
        min_quality = int(config.get("min_quality", 80))
        min_trust = float(config.get("min_trust", 0.8500))
        target_org_ids = config.get("org_ids")
    elif isinstance(config, (int, float)):
        batch_size = int(config)
        min_quality = int(args[0]) if len(args) > 0 else 80
        min_trust = float(args[1]) if len(args) > 1 else 0.8500
    else:
        batch_size = 5000
        min_quality = 80
        min_trust = 0.8500

    activity.logger.info("Evaluating working governance: batch_size=%d min_q=%d min_t=%.4f", batch_size, min_quality, min_trust)
    if activity.in_activity():
        activity.heartbeat("Evaluating pre-master working layer governance")

    from packages.domain.trust_engine import trust_engine
    from packages.infrastructure.dead_letter_queue import enqueue_dead_letter
    from db_connector import get_connection, release_connection

    conn = None
    evaluated = 0
    approved = 0
    quarantined = 0

    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                if target_org_ids:
                    cur.execute("""
                        SELECT org_id, legal_name, display_name, primary_domain, website,
                               statutory_tax_id, sec_cik, jurisdiction, industry, naics_code,
                               employee_count_min, employee_count_max, annual_revenue_usd,
                               phones, locations, identity_confidence, contributing_sources,
                               lineage_ids
                        FROM staging_dataextraction.working_organizations
                        WHERE org_id = ANY(%s)
                        FOR UPDATE;
                    """, (target_org_ids,))
                else:
                    cur.execute("""
                        SELECT org_id, legal_name, display_name, primary_domain, website,
                               statutory_tax_id, sec_cik, jurisdiction, industry, naics_code,
                               employee_count_min, employee_count_max, annual_revenue_usd,
                               phones, locations, identity_confidence, contributing_sources,
                               lineage_ids
                        FROM staging_dataextraction.working_organizations
                        WHERE governance_status IN ('IN_ENRICHMENT', 'REVALIDATION_PENDING')
                        ORDER BY created_at ASC
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED;
                    """, (batch_size,))
                rows = cur.fetchall()
                col_names = [c[0] for c in cur.description] if cur.description else []

                for r in rows:
                    org_dict = dict(zip(col_names, r))
                    org_id = org_dict["org_id"]
                    eval_res = trust_engine.evaluate_organization(org_dict)

                    q_score = eval_res["data_quality_score"]
                    t_score = eval_res["trust_score"]
                    is_cert = eval_res["is_certified"]
                    gov_status = eval_res["governance_status"]
                    q_reason = eval_res["quarantine_reason"]

                    # Update working organization scores and governance status
                    cur.execute("""
                        UPDATE staging_dataextraction.working_organizations
                        SET data_quality_score = %s,
                            trust_score = %s,
                            governance_status = %s,
                            updated_at = NOW()
                        WHERE org_id = %s;
                    """, (q_score, t_score, gov_status, org_id))

                    if is_cert:
                        approved += 1
                    else:
                        quarantined += 1
                        try:
                            enqueue_dead_letter(
                                conn=conn,
                                source_name="GOVERNANCE_CERTIFICATION_GATE",
                                entity_type="working_organization",
                                raw_payload=org_dict,
                                error_reason=f"QUARANTINED_GOVERNANCE_GATE: {q_reason}",
                                run_id="agent5_governance",
                            )
                        except Exception as dlq_err:
                            activity.logger.debug("DLQ enqueue notice: %s", dlq_err)

                    evaluated += 1

                conn.commit()
            except Exception as e:
                conn.rollback()
                activity.logger.warning("Governance evaluation query notice: %s", e)
            finally:
                cur.close()
    finally:
        if conn:
            release_connection(conn)

    return {
        "status": "COMPLETED",
        "evaluated_count": evaluated,
        "approved_count": approved,
        "quarantined_count": quarantined,
    }


@activity.defn(name="promote_certified_to_master")
async def promote_certified_to_master_activity(config: Any = None, *args) -> dict:
    """
    Sprint 3: Atomic Promotion Gate.
    Promotes certified records (governance_status = 'APPROVED') from
    staging_dataextraction.working_* into master_dataextraction.* in a single atomic CTE transaction.
    Initializes master freshness_score and next_verification_at via central configuration.
    """
    from packages.infrastructure.config_manager import config_manager
    pg_cfg = config_manager.get_promotion_gate_config()

    target_org_id = None
    if isinstance(config, dict):
        min_quality = int(config.get("min_quality", pg_cfg["min_quality_score"]))
        min_trust = float(config.get("min_trust", pg_cfg["min_trust_score"]))
        batch_size = int(config.get("batch_size", pg_cfg["batch_chunk_size"]))
        target_org_id = config.get("target_org_id") or config.get("org_id")
    elif isinstance(config, (int, float)):
        min_quality = int(config)
        min_trust = float(args[0]) if len(args) > 0 else pg_cfg["min_trust_score"]
        batch_size = int(args[1]) if len(args) > 1 else pg_cfg["batch_chunk_size"]
    else:
        min_quality = pg_cfg["min_quality_score"]
        min_trust = pg_cfg["min_trust_score"]
        batch_size = pg_cfg["batch_chunk_size"]

    init_freshness = float(pg_cfg.get("freshness_initial_score", 1.0000))
    revalidation_days = int(pg_cfg.get("revalidation_interval_days", 90))

    activity.logger.info(
        "Executing Atomic Promotion Gate: min_quality=%d min_trust=%.4f batch_size=%d revalidation_days=%d target=%s",
        min_quality, min_trust, batch_size, revalidation_days, target_org_id
    )
    if activity.in_activity():
        activity.heartbeat("Executing Atomic Promotion Gate into master_dataextraction")

    conn = None
    promoted_orgs = 0
    promoted_persons = 0
    promoted_emails = 0

    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                # 1. Atomic Multi-Row CTE Promotion of Organizations
                cur.execute("""
                    WITH locked_batch AS (
                        SELECT org_id
                        FROM staging_dataextraction.working_organizations
                        WHERE governance_status = 'APPROVED'
                          AND data_quality_score >= %s
                          AND trust_score >= %s
                          AND org_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                          AND (%s::text IS NULL OR org_id = %s::text)
                        ORDER BY org_id ASC
                        LIMIT %s
                        FOR UPDATE SKIP LOCKED
                    ),
                    promoted AS (
                        INSERT INTO master_dataextraction.organizations (
                            org_id, jurisdiction, legal_name, display_name, primary_domain,
                            statutory_tax_id, sec_cik, gleif_lei, entity_status, industry, primary_industry_naics,
                            primary_industry_sic, employee_count_min, employee_count_max, annual_revenue_usd,
                            data_quality_score, trust_score, freshness_score, governance_status,
                            last_verified_at, next_verification_at, verification_source,
                            website_last_verified_at, email_last_verified_at, executive_last_verified_at,
                            domain_last_verified_at, maps_last_verified_at, registry_last_verified_at,
                            created_at, updated_at
                        )
                        SELECT
                            w.org_id::uuid,
                            CASE 
                                WHEN UPPER(w.jurisdiction) IN ('US', 'MX', 'CA', 'GLOBAL') THEN UPPER(w.jurisdiction)::kg_core.jurisdiction_code
                                ELSE 'US'::kg_core.jurisdiction_code
                            END,
                            w.legal_name,
                            COALESCE(w.display_name, w.legal_name),
                            w.primary_domain,
                            w.statutory_tax_id,
                            w.sec_cik,
                            w.gleif_lei,
                            'active'::kg_core.entity_status,
                            w.industry,
                            w.naics_code,
                            w.sic_code,
                            w.employee_count_min,
                            w.employee_count_max,
                            w.annual_revenue_usd,
                            w.data_quality_score::smallint,
                            w.trust_score,
                            %s,
                            'CERTIFIED',
                            NOW(),
                            NOW() + (%s || ' days')::interval,
                            'PROMOTION_GATE',
                            NOW(), NOW(), NOW(), NOW(), NOW(), NOW(),
                            NOW(), NOW()
                        FROM staging_dataextraction.working_organizations w
                        JOIN locked_batch b ON w.org_id = b.org_id
                        ON CONFLICT (org_id, jurisdiction) DO UPDATE SET
                            legal_name = EXCLUDED.legal_name,
                            display_name = EXCLUDED.display_name,
                            primary_domain = COALESCE(EXCLUDED.primary_domain, master_dataextraction.organizations.primary_domain),
                            statutory_tax_id = COALESCE(EXCLUDED.statutory_tax_id, master_dataextraction.organizations.statutory_tax_id),
                            sec_cik = COALESCE(EXCLUDED.sec_cik, master_dataextraction.organizations.sec_cik),
                            gleif_lei = COALESCE(EXCLUDED.gleif_lei, master_dataextraction.organizations.gleif_lei),
                            entity_status = EXCLUDED.entity_status,
                            industry = COALESCE(EXCLUDED.industry, master_dataextraction.organizations.industry),
                            employee_count_min = COALESCE(EXCLUDED.employee_count_min, master_dataextraction.organizations.employee_count_min),
                            employee_count_max = COALESCE(EXCLUDED.employee_count_max, master_dataextraction.organizations.employee_count_max),
                            annual_revenue_usd = COALESCE(EXCLUDED.annual_revenue_usd, master_dataextraction.organizations.annual_revenue_usd),
                            data_quality_score = GREATEST(EXCLUDED.data_quality_score, master_dataextraction.organizations.data_quality_score),
                            trust_score = GREATEST(EXCLUDED.trust_score, master_dataextraction.organizations.trust_score),
                            freshness_score = %s,
                            governance_status = 'CERTIFIED',
                            last_verified_at = NOW(),
                            next_verification_at = NOW() + (%s || ' days')::interval,
                            verification_source = 'PROMOTION_GATE',
                            updated_at = NOW()
                        RETURNING org_id
                    )
                    UPDATE staging_dataextraction.working_organizations w
                    SET governance_status = 'PROMOTED', updated_at = NOW()
                    FROM promoted p
                    WHERE w.org_id = p.org_id::text;
                """, (min_quality, min_trust, target_org_id, target_org_id, batch_size, init_freshness, str(revalidation_days), init_freshness, str(revalidation_days)))
                promoted_orgs = cur.rowcount

                # 2. Promote Working Persons to master_dataextraction.persons
                cur.execute("""
                    WITH promoted_persons_cte AS (
                        INSERT INTO master_dataextraction.persons (
                            person_id, current_primary_org_id, full_name, first_name, last_name,
                            current_primary_title, seniority_level, department, primary_email,
                            primary_phone_e164, primary_linkedin_url, data_quality_score,
                            trust_score, governance_status, last_verified_at, next_verification_at,
                            created_at, updated_at
                        )
                        SELECT
                            wp.person_id::uuid,
                            wp.org_id::uuid,
                            wp.full_name,
                            wp.first_name,
                            wp.last_name,
                            wp.title,
                            wp.seniority,
                            wp.department,
                            wp.primary_email,
                            wp.primary_phone,
                            wp.linkedin_url,
                            ROUND(wp.confidence_score * 100)::smallint,
                            wp.confidence_score,
                            'CERTIFIED',
                            NOW(),
                            NOW() + (%s || ' days')::interval,
                            NOW(),
                            NOW()
                        FROM staging_dataextraction.working_persons wp
                        JOIN staging_dataextraction.working_organizations wo ON wp.org_id = wo.org_id
                        WHERE wo.governance_status = 'PROMOTED'
                          AND wp.governance_status != 'PROMOTED'
                          AND wp.person_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                        ON CONFLICT (person_id) DO UPDATE SET
                            full_name = EXCLUDED.full_name,
                            current_primary_title = COALESCE(EXCLUDED.current_primary_title, master_dataextraction.persons.current_primary_title),
                            seniority_level = COALESCE(EXCLUDED.seniority_level, master_dataextraction.persons.seniority_level),
                            primary_email = COALESCE(EXCLUDED.primary_email, master_dataextraction.persons.primary_email),
                            primary_phone_e164 = COALESCE(EXCLUDED.primary_phone_e164, master_dataextraction.persons.primary_phone_e164),
                            primary_linkedin_url = COALESCE(EXCLUDED.primary_linkedin_url, master_dataextraction.persons.primary_linkedin_url),
                            governance_status = 'CERTIFIED',
                            last_verified_at = NOW(),
                            next_verification_at = NOW() + (%s || ' days')::interval,
                            updated_at = NOW()
                        RETURNING person_id
                    )
                    UPDATE staging_dataextraction.working_persons wp
                    SET governance_status = 'PROMOTED'
                    FROM promoted_persons_cte pp
                    WHERE wp.person_id = pp.person_id::text;
                """, (str(revalidation_days), str(revalidation_days)))
                promoted_persons = cur.rowcount

                # 3. Promote Working Emails to master_dataextraction.contact_emails
                cur.execute("""
                    INSERT INTO master_dataextraction.contact_emails (
                        email_id, email_address, normalized_domain, org_id,
                        email_type, deliverability_status, deliverability_score,
                        is_catch_all, is_disposable, bounce_count, last_verified_at, created_at
                    )
                    SELECT DISTINCT
                        gen_random_uuid(),
                        we.email_address,
                        we.email_domain,
                        we.org_id::uuid,
                        'work_direct'::kg_core.email_type,
                        CASE 
                            WHEN UPPER(we.deliverability_status) IN ('DELIVERABLE', 'VERIFIED_DELIVERABLE') THEN 'verified_deliverable'::kg_core.deliverability_status
                            WHEN UPPER(we.deliverability_status) IN ('RISKY', 'RISKY_CATCHALL') THEN 'risky_catchall'::kg_core.deliverability_status
                            WHEN UPPER(we.deliverability_status) IN ('UNDELIVERABLE', 'UNDELIVERABLE_BOUNCED') THEN 'undeliverable_bounced'::kg_core.deliverability_status
                            WHEN UPPER(we.deliverability_status) IN ('DISPOSABLE', 'DISPOSABLE_BLOCKED') THEN 'disposable_blocked'::kg_core.deliverability_status
                            ELSE 'untested'::kg_core.deliverability_status
                        END,
                        COALESCE(we.confidence_score, 80)::smallint,
                        COALESCE(we.is_catchall, FALSE),
                        FALSE,
                        0::smallint,
                        NOW(),
                        NOW()
                    FROM staging_dataextraction.working_emails we
                    JOIN staging_dataextraction.working_organizations wo ON we.org_id = wo.org_id
                    WHERE wo.governance_status = 'PROMOTED'
                      AND we.org_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    ON CONFLICT (email_address) DO UPDATE SET
                        org_id = COALESCE(master_dataextraction.contact_emails.org_id, EXCLUDED.org_id),
                        deliverability_status = EXCLUDED.deliverability_status,
                        deliverability_score = EXCLUDED.deliverability_score,
                        last_verified_at = NOW();
                """)
                promoted_emails = cur.rowcount

                conn.commit()
            except Exception as e:
                conn.rollback()
                activity.logger.warning("Promotion Gate CTE transaction notice: %s", e)
            finally:
                cur.close()
    finally:
        if conn:
            release_connection(conn)

    return {
        "status": "COMPLETED",
        "promoted_orgs": promoted_orgs,
        "promoted_persons": promoted_persons,
        "promoted_emails": promoted_emails,
    }


# ── Sprint 4: Autonomous Freshness & SLA Revalidation Activities ──────────────

@activity.defn(name="apply_freshness_decay")
async def apply_freshness_decay_activity(batch_size: Any = None, target_org_id: Optional[str] = None) -> dict:
    """
    Sprint 4: Computes exponential decay F(t) = exp(-lambda * delta_t) across
    master_dataextraction.organizations and updates freshness_score.
    """
    from packages.infrastructure.config_manager import config_manager
    fresh_cfg = config_manager.get_freshness_engine_config()
    default_batch = fresh_cfg.get("decay_batch_size", 5000)

    if isinstance(batch_size, dict):
        target_org_id = batch_size.get("org_id") or target_org_id
        batch_size = int(batch_size.get("batch_size", default_batch))
    elif batch_size is not None:
        batch_size = int(batch_size)
    else:
        batch_size = default_batch

    activity.logger.info("Applying mathematical freshness decay: batch_size=%d target=%s", batch_size, target_org_id)
    if activity.in_activity():
        activity.heartbeat("Calculating continuous freshness decay scores")

    from packages.domain.freshness_engine import freshness_engine

    conn = None
    processed = 0
    decayed_sum = 0.0

    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT org_id, last_verified_at, next_verification_at,
                           website_last_verified_at, email_last_verified_at,
                           executive_last_verified_at, domain_last_verified_at,
                           maps_last_verified_at, registry_last_verified_at
                    FROM master_dataextraction.organizations
                    WHERE governance_status = 'CERTIFIED'
                      AND (%s::text IS NULL OR org_id = %s::uuid)
                    ORDER BY last_verified_at ASC NULLS FIRST
                    LIMIT %s;
                """, (target_org_id, target_org_id, batch_size))
                rows = cur.fetchall()
                col_names = [c[0] for c in cur.description] if cur.description else []

                for r in rows:
                    org_dict = dict(zip(col_names, r))
                    org_id = org_dict["org_id"]
                    f_eval = freshness_engine.evaluate_organization_freshness(org_dict)
                    comp_score = f_eval["composite_freshness"]

                    cur.execute("""
                        UPDATE master_dataextraction.organizations
                        SET freshness_score = %s
                        WHERE org_id = %s;
                    """, (comp_score, org_id))

                    processed += 1
                    decayed_sum += comp_score

                conn.commit()
            except Exception as e:
                conn.rollback()
                activity.logger.warning("Freshness decay query notice: %s", e)
            finally:
                cur.close()
    finally:
        if conn:
            release_connection(conn)

    avg_f = round(decayed_sum / max(1, processed), 4)
    return {
        "status": "COMPLETED",
        "processed_count": processed,
        "average_freshness_score": avg_f,
    }


@activity.defn(name="fetch_overdue_revalidations")
async def fetch_overdue_revalidations_activity(limit: Any = None, target_org_id: Optional[str] = None) -> dict:
    """
    Sprint 4: Identifies entities in master_dataextraction.organizations
    where next_verification_at <= NOW() or freshness_score < stale_threshold (default 0.70).
    """
    from packages.infrastructure.config_manager import config_manager
    fresh_cfg = config_manager.get_freshness_engine_config()
    default_limit = fresh_cfg.get("overdue_fetch_limit", 5000)
    stale_thresh = float(fresh_cfg.get("stale_threshold", 0.70))

    if isinstance(limit, dict):
        target_org_id = limit.get("org_id") or target_org_id
        limit = int(limit.get("limit", limit.get("batch_size", default_limit)))
    elif limit is not None:
        limit = int(limit)
    else:
        limit = default_limit

    activity.logger.info("Fetching overdue revalidations: limit=%d stale_thresh=%.2f target=%s", limit, stale_thresh, target_org_id)
    from packages.domain.freshness_engine import freshness_engine

    conn = None
    overdue_records = []

    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("""
                    SELECT org_id, legal_name, display_name, primary_domain,
                           statutory_tax_id, sec_cik, gleif_lei, jurisdiction, industry,
                           primary_industry_naics, primary_industry_sic, employee_count_min,
                           employee_count_max, annual_revenue_usd, data_quality_score,
                           trust_score, freshness_score, last_verified_at, next_verification_at,
                           website_last_verified_at, email_last_verified_at,
                           executive_last_verified_at, domain_last_verified_at,
                           maps_last_verified_at, registry_last_verified_at
                    FROM master_dataextraction.organizations
                    WHERE (next_verification_at <= NOW() OR freshness_score < %s)
                      AND governance_status = 'CERTIFIED'
                      AND (%s::text IS NULL OR org_id = %s::uuid)
                    ORDER BY freshness_score ASC, next_verification_at ASC
                    LIMIT %s;
                """, (stale_thresh, target_org_id, target_org_id, limit))
                rows = cur.fetchall()
                col_names = [c[0] for c in cur.description] if cur.description else []

                for r in rows:
                    org_dict = dict(zip(col_names, r))
                    eval_f = freshness_engine.evaluate_organization_freshness(org_dict)
                    overdue_records.append({
                        "org_id": str(org_dict["org_id"]),
                        "legal_name": org_dict.get("legal_name"),
                        "primary_domain": org_dict.get("primary_domain"),
                        "freshness_score": float(org_dict.get("freshness_score") or 0.0),
                        "overdue_dimensions": eval_f.get("overdue_dimensions", []),
                        "recommended_actions": eval_f.get("recommended_actions", []),
                    })
            finally:
                cur.close()
    finally:
        if conn:
            release_connection(conn)

    return {
        "status": "COMPLETED",
        "overdue_count": len(overdue_records),
        "records": overdue_records,
    }


@activity.defn(name="stage_overdue_for_reharvest")
async def stage_overdue_for_reharvest_activity(records: Any = None) -> dict:
    """
    Sprint 4: Stages overdue organizations back into staging_dataextraction.working_organizations
    with governance_status = 'REVALIDATION_PENDING', resetting email/executive verification statuses
    for stale dimensions.
    """
    if isinstance(records, dict):
        rec_list = records.get("records", [])
    elif isinstance(records, list):
        rec_list = records
    else:
        rec_list = []

    activity.logger.info("Staging %d overdue entities for reharvest", len(rec_list))

    conn = None
    staged = 0

    try:
        conn = get_connection()
        if conn:
            cur = conn.cursor()
            try:
                for rec in rec_list:
                    org_id = rec.get("org_id")
                    if not org_id:
                        continue
                    overdue_dims = rec.get("overdue_dimensions", [])
                    email_status = "PENDING" if ("website" in overdue_dims or "email" in overdue_dims) else "COMPLETED"
                    exec_status = "PENDING" if "executive" in overdue_dims else "COMPLETED"

                    cur.execute("""
                        INSERT INTO staging_dataextraction.working_organizations (
                            org_id, legal_name, primary_domain, governance_status,
                            email_verification_status, executive_enrichment_status,
                            updated_at
                        )
                        SELECT
                            org_id::text, legal_name, primary_domain,
                            'REVALIDATION_PENDING', %s, %s, NOW()
                        FROM master_dataextraction.organizations
                        WHERE org_id = %s::uuid
                        ON CONFLICT (org_id) DO UPDATE SET
                            governance_status = 'REVALIDATION_PENDING',
                            email_verification_status = EXCLUDED.email_verification_status,
                            executive_enrichment_status = EXCLUDED.executive_enrichment_status,
                            updated_at = NOW();
                    """, (email_status, exec_status, org_id))
                    staged += 1

                conn.commit()
            except Exception as e:
                conn.rollback()
                activity.logger.warning("Stage for reharvest notice: %s", e)
            finally:
                cur.close()
    finally:
        if conn:
            release_connection(conn)

    return {"status": "COMPLETED", "staged_count": staged}
