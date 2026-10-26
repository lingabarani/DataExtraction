"""
OpenStreetMap / Overpass Open Map Extraction Connector.
Bridges Open Map Extraction Engine into OneExtraction's canonical US B2B database pipeline.

Provides:
- High-level interface to query Overpass API using circuit breaker and quadtree bisection.
- Loading and normalization of exported OSM POI data into USCanonicalCompany models.
- Enterprise deduplication against PostgreSQL/SQLite via OneExtraction Deduplicator.
- Batch ingestion with atomic transactions, quality scoring, and provenance logging.
- Checkpoint reconciliation against disk files.
"""

import csv
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_CURRENT_DIR = Path(__file__).resolve().parent
_BOTASAURUS_DIR = _CURRENT_DIR.parent
_REPO_ROOT = _BOTASAURUS_DIR.parent
_ENGINE_DIR = _REPO_ROOT / "Open Map Extraction Engine"

# Ensure path resolution
if str(_BOTASAURUS_DIR) not in sys.path:
    sys.path.insert(0, str(_BOTASAURUS_DIR))

from normalizer import normalize_company
from deduplicator import Deduplicator
from db_connector import (
    get_connection,
    release_connection,
    upsert_company,
    update_company_fields,
    log_data_source,
)

from .config import OverpassConfig, default_config
from .circuit_breaker import EndpointCircuitBreaker
from .quadtree import AdaptiveQuadtree
from .checkpoint import EnterpriseCheckpointManager
from .taxonomy import US_STATES, STATE_BOUNDING_BOXES, FIELDS_TAXONOMY, slugify

logger = logging.getLogger("oneextraction.openmap_connector")


class OpenMapConnector:
    """
    Enterprise connector linking Open Map Extraction Engine to OneExtraction.
    """

    SOURCE_KEY = "OPEN_MAP"
    SOURCE_NAME = "OpenStreetMap Overpass Engine"

    def __init__(
        self,
        config: Optional[OverpassConfig] = None,
        workspace_dir: Optional[str] = None
    ):
        self.workspace_dir = Path(workspace_dir) if workspace_dir else _ENGINE_DIR
        if not self.workspace_dir.exists():
            # Fallback to local botasaurus directory if separate engine dir not present
            self.workspace_dir = _BOTASAURUS_DIR

        self.config = config or default_config
        self.checkpoint_manager = EnterpriseCheckpointManager(str(self.workspace_dir))
        self.quadtree = AdaptiveQuadtree(
            max_depth=self.config.max_quadtree_depth,
            min_chunk_deg=self.config.min_chunk_deg
        )
        self.circuit_breaker = EndpointCircuitBreaker(
            endpoints=self.config.fallback_endpoints,
            failure_threshold=2,
            cooldown_sec=self.config.circuit_breaker_cooldown_sec
        )

    def load_exported_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Loads records from an exported JSON or CSV file."""
        p = Path(file_path)
        if not p.is_absolute():
            p = self.workspace_dir / p

        if not p.exists():
            raise FileNotFoundError(f"Export file not found: {file_path}")

        if p.suffix.lower() == ".json":
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else [data]
        elif p.suffix.lower() == ".csv":
            records = []
            with open(p, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(row)
            return records
        else:
            raise ValueError(f"Unsupported file format: {p.suffix}. Expected .json or .csv")

    def load_state_field_export(self, state_name: str, field_name: str) -> List[Dict[str, Any]]:
        """Loads canonical exported records for a state and field from disk."""
        state_slug = slugify(state_name)
        export_dir = self.workspace_dir / "data" / "export" / state_slug

        json_path = export_dir / f"{field_name}.json"
        if json_path.exists():
            return self.load_exported_file(str(json_path))

        csv_path = export_dir / f"{field_name}.csv"
        if csv_path.exists():
            return self.load_exported_file(str(csv_path))

        # Check raw / processed if export not generated yet
        proc_file = self.workspace_dir / "data" / "processed" / state_slug / f"{field_name}_complete.json"
        if proc_file.exists():
            return self.load_exported_file(str(proc_file))

        raise FileNotFoundError(
            f"No exported data found for state '{state_name}' field '{field_name}' in {export_dir}"
        )

    def normalize_records(self, raw_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Transforms raw OSM POI records into unified company schema."""
        normalized = []
        for r in raw_records:
            try:
                norm = normalize_company(r, source="OPEN_MAP")
                # Ensure valid name exists
                if norm.get("name"):
                    normalized.append(norm)
            except Exception as e:
                logger.debug("Failed to normalize record %s: %s", r.get("osm_id") or r.get("name"), e)
        return normalized

    def ingest_records(
        self,
        records: List[Dict[str, Any]],
        run_id: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Deduplicates and ingests normalized records into OneExtraction database.
        Returns execution summary statistics.
        """
        active_run_id = run_id or f"osm_{uuid.uuid4().hex[:8]}"
        normalized_list = self.normalize_records(records)

        stats = {
            "run_id": active_run_id,
            "total_raw": len(records),
            "total_normalized": len(normalized_list),
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "dry_run": dry_run
        }

        if dry_run:
            logger.info("Dry run requested; validated %d normalized records without DB write.", len(normalized_list))
            stats["inserted"] = len(normalized_list)
            return stats

        conn = get_connection()
        try:
            dedup = Deduplicator(conn, run_id=active_run_id)

            for comp in normalized_list:
                try:
                    result = dedup.check_company(comp)
                    if result.action == "insert":
                        comp["id"] = result.id
                        upsert_company(conn, comp)
                        stats["inserted"] += 1
                    elif result.action == "update":
                        if result.updates:
                            update_company_fields(conn, result.id, result.updates)
                            stats["updated"] += 1
                        else:
                            stats["skipped"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as row_err:
                    stats["errors"] += 1
                    logger.warning("Error ingesting company %s: %s", comp.get("name"), row_err)

            # Flush buffered deduplication audit logs
            dedup.flush_logs()

            # Record source provenance
            log_data_source(
                conn,
                source_name=self.SOURCE_NAME,
                record_count=stats["inserted"] + stats["updated"],
                status="COMPLETED"
            )

            conn.commit()
            logger.info(
                "Ingestion completed [%s]: %d inserted, %d updated, %d skipped, %d errors",
                active_run_id, stats["inserted"], stats["updated"], stats["skipped"], stats["errors"]
            )
            return stats

        except Exception as e:
            if conn:
                conn.rollback()
            logger.exception("Ingestion failed: %s", e)
            raise
        finally:
            release_connection(conn)

    def reconcile_checkpoints(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Reconciles checkpoint database with files on disk.
        Audits completed states and exports, updating checkpoint records if needed.
        """
        export_base = self.workspace_dir / "data" / "export"
        reconciled = {
            "states_inspected": 0,
            "exports_found": 0,
            "updated_records": 0,
            "dry_run": dry_run
        }

        if not export_base.exists():
            return reconciled

        for state_dir in export_base.iterdir():
            if not state_dir.is_dir():
                continue
            reconciled["states_inspected"] += 1
            state_slug = state_dir.name

            for export_file in state_dir.glob("*.json"):
                field_name = export_file.stem
                reconciled["exports_found"] += 1

                try:
                    with open(export_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        count = len(data) if isinstance(data, list) else 1
                except Exception:
                    continue

                if not dry_run:
                    # Update field status in SQLite checkpoint
                    state_title = state_slug.replace("_", " ").title()
                    status_row = self.checkpoint_manager.get_field_status(state_title, field_name)
                    if not status_row or status_row.get("status") != "COMPLETED":
                        self.checkpoint_manager.set_field_status(
                            state_name=state_title,
                            field_name=field_name,
                            status="COMPLETED",
                            records_collected=count
                        )
                        reconciled["updated_records"] += 1

        if not dry_run:
            self.checkpoint_manager.sync_to_legacy_json()

        return reconciled
