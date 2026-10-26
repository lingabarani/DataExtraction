"""
DataExtraction — Pipeline Activities
=====================================
Temporal activity wrappers for all data transformation steps.
These call the pipeline modules (normalizer, deduplicator, etc.) via
sys.path injection — source files are never modified.
"""

import logging
import sys
from pathlib import Path

from temporalio import activity

# Inject pipeline package path
PIPELINE_PATH = Path(__file__).resolve().parents[3] / "pipeline"
if str(PIPELINE_PATH.parent) not in sys.path:
    sys.path.insert(0, str(PIPELINE_PATH.parent))

logger = logging.getLogger("dataextraction.activities.pipeline")


@activity.defn(name="normalize_batch")
async def normalize_batch_activity(source: str, table: str, batch_size: int = 5000) -> dict:
    """
    Normalizes raw records from a scraper source table.
    Applies field mapping, phone formatting, address standardization.

    Args:
        source: Source identifier (e.g., "CMS_NPI", "GMAPS", "OSM")
        table: Target PostgreSQL table name
        batch_size: Number of records to normalize per batch

    Returns:
        {"normalized": int, "source": str, "table": str, "status": str}
    """
    activity.logger.info("Normalizing: source=%s table=%s batch=%d", source, table, batch_size)
    activity.heartbeat(f"Normalizing {source} → {table}")

    from pipeline.normalizer import normalize_records  # type: ignore

    result = normalize_records(source=source, table=table, batch_size=batch_size)
    return {
        "normalized": result.count,
        "source": source,
        "table": table,
        "status": "SUCCESS",
    }


@activity.defn(name="deduplicate_batch")
async def deduplicate_batch_activity(table: str, batch_size: int = 1000) -> dict:
    """
    Deduplicates records in the given table using multi-field fuzzy matching.
    Merges duplicates, removes redundant rows.

    Args:
        table: PostgreSQL table to deduplicate
        batch_size: Records per deduplication batch

    Returns:
        {"merged": int, "removed": int, "table": str, "status": str}
    """
    activity.logger.info("Deduplicating: table=%s batch=%d", table, batch_size)
    activity.heartbeat(f"Deduplicating {table}")

    from pipeline.deduplicator import deduplicate_pending  # type: ignore

    result = deduplicate_pending(table=table, batch_size=batch_size)
    return {
        "merged": result.merged_count,
        "removed": result.removed_count,
        "table": table,
        "status": "SUCCESS",
    }


@activity.defn(name="validate_contacts")
async def validate_contacts_activity(table: str, limit: int = 5000) -> dict:
    """
    Validates phone numbers and emails for records in the given table.
    Updates validation_status and validation_score fields.

    Args:
        table: PostgreSQL table containing records to validate
        limit: Max records to validate per run

    Returns:
        {"validated": int, "failed": int, "table": str, "status": str}
    """
    activity.logger.info("Validating contacts: table=%s limit=%d", table, limit)
    activity.heartbeat(f"Validating contacts in {table}")

    from pipeline.contact_validator import validate_batch  # type: ignore

    result = validate_batch(table=table, limit=limit)
    return {
        "validated": result.count,
        "failed": result.failed_count,
        "table": table,
        "status": "SUCCESS",
    }


@activity.defn(name="build_leads")
async def build_leads_activity(source_table: str, target_table: str) -> dict:
    """
    Builds enriched lead records from validated contacts.
    Combines federal + gmaps + OSM data for each entity.

    Args:
        source_table: Source table (validated contacts)
        target_table: Destination table (enriched leads)

    Returns:
        {"built": int, "source_table": str, "target_table": str, "status": str}
    """
    activity.logger.info("Building leads: %s → %s", source_table, target_table)
    activity.heartbeat(f"Building leads {source_table} → {target_table}")

    from pipeline.lead_builder import build_leads  # type: ignore

    result = build_leads(source_table=source_table, target_table=target_table)
    return {
        "built": result.count,
        "source_table": source_table,
        "target_table": target_table,
        "status": "SUCCESS",
    }


@activity.defn(name="validate_tax_ids")
async def validate_tax_ids_activity(table: str, limit: int = 10000) -> dict:
    """
    Validates EIN/TIN tax identifiers in the given table.

    Args:
        table: PostgreSQL table containing records with tax ID fields
        limit: Max records to validate per run

    Returns:
        {"validated": int, "failed": int, "table": str, "status": str}
    """
    activity.logger.info("Validating tax IDs: table=%s limit=%d", table, limit)

    from pipeline.tax_validator import validate_batch as validate_tax  # type: ignore

    result = validate_tax(table=table, limit=limit)
    return {
        "validated": result.count,
        "failed": result.failed_count,
        "table": table,
        "status": "SUCCESS",
    }


@activity.defn(name="validate_geo")
async def validate_geo_activity(table: str, limit: int = 10000) -> dict:
    """
    Validates and enriches geographic fields (lat/lng, state, ZIP code).

    Args:
        table: PostgreSQL table containing records with address fields
        limit: Max records to validate per run

    Returns:
        {"validated": int, "failed": int, "table": str, "status": str}
    """
    activity.logger.info("Validating geo: table=%s limit=%d", table, limit)

    from pipeline.geo_validator import validate_batch as validate_geo  # type: ignore

    result = validate_geo(table=table, limit=limit)
    return {
        "validated": result.count,
        "failed": result.failed_count,
        "table": table,
        "status": "SUCCESS",
    }
