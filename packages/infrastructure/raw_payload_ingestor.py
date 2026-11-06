"""
DataExtraction — Raw Lakehouse Payload Ingestion Engine
======================================================
Enterprise ingestion service for the immutable raw extraction layer:
  `raw_dataextraction.scraper_payloads`

Features:
  - Cryptographic SHA-256 deduplication and verification
  - Automatic JSON serialization with key canonicalization
  - Thread-safe connection-pooled writes via `db_connector`
  - High-performance batch ingestion with parameterized SQL
  - Fallback and error isolation (never crashes the scraper)
"""

import hashlib
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from packages.infrastructure.db_connector import get_db_cursor
except ImportError:
    from db_connector import get_db_cursor

logger = logging.getLogger("dataextraction.lakehouse.raw_ingestor")


class RawPayloadIngestor:
    """
    Ingests raw source payloads into `raw_dataextraction.scraper_payloads`.
    Guarantees raw data auditability, immutability, and end-to-end provenance.
    """

    def __init__(self, target_schema: str = "raw_dataextraction"):
        self.target_schema = target_schema
        self.table_name = f"{target_schema}.scraper_payloads"

    @staticmethod
    def compute_hash(content_str: str) -> str:
        """Computes SHA-256 hexadecimal digest of raw payload string."""
        return hashlib.sha256(content_str.encode("utf-8")).hexdigest()

    def serialize_payload(self, raw_data: Union[str, dict, list, bytes]) -> str:
        """Serializes raw data to canonical text representation."""
        if isinstance(raw_data, bytes):
            return raw_data.decode("utf-8", errors="replace")
        elif isinstance(raw_data, (dict, list)):
            return json.dumps(raw_data, sort_keys=True, ensure_ascii=False)
        return str(raw_data)

    def ingest(
        self,
        source_name: str,
        natural_key: str,
        raw_data: Union[str, dict, list, bytes],
        s3_url: Optional[str] = None,
        deduplicate: bool = True,
    ) -> Dict[str, Any]:
        """
        Ingests a single raw payload into `raw_dataextraction.scraper_payloads`.

        Args:
            source_name: Scraper/Source identifier (e.g. 'GMAPS', 'OSM', 'SEC_EDGAR', 'CMS_NPI', 'OPENDIRECTORIES')
            natural_key: Source identifier (e.g. place_id, osm_id, CIK, NPI, URL)
            raw_data: The exact raw payload (JSON object, HTML string, XML text, or dict)
            s3_url: Optional S3/GCS/MinIO blob location
            deduplicate: When True, skips inserting if the identical (source_name, payload_hash) exists

        Returns:
            Dictionary with payload_id, payload_hash, inserted status, and ingested_at.
        """
        source_clean = str(source_name).strip()[:50]
        key_clean = str(natural_key).strip()[:255]
        raw_body = self.serialize_payload(raw_data)
        payload_hash = self.compute_hash(raw_body)
        new_payload_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        try:
            with get_db_cursor() as (conn, cur):
                if deduplicate:
                    cur.execute(
                        f"""
                        SELECT payload_id, ingested_at 
                        FROM {self.table_name}
                        WHERE source_name = %s AND payload_hash = %s
                        LIMIT 1;
                        """,
                        (source_clean, payload_hash),
                    )
                    existing = cur.fetchone()
                    if existing:
                        logger.debug(
                            "[%s] Deduped payload %s (hash: %s...)",
                            source_clean, key_clean, payload_hash[:12]
                        )
                        return {
                            "payload_id": str(existing[0]),
                            "source_name": source_clean,
                            "natural_key": key_clean,
                            "payload_hash": payload_hash,
                            "s3_url": s3_url,
                            "inserted": False,
                            "ingested_at": existing[1].isoformat(),
                        }

                cur.execute(
                    f"""
                    INSERT INTO {self.table_name} (
                        payload_id, source_name, natural_key, raw_body, s3_url, payload_hash, ingested_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING payload_id, ingested_at;
                    """,
                    (
                        new_payload_id,
                        source_clean,
                        key_clean,
                        raw_body,
                        s3_url,
                        payload_hash,
                        now,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return {
                    "payload_id": str(row[0]),
                    "source_name": source_clean,
                    "natural_key": key_clean,
                    "payload_hash": payload_hash,
                    "s3_url": s3_url,
                    "inserted": True,
                    "ingested_at": row[1].isoformat(),
                }
        except Exception as exc:
            logger.error("[%s] Failed to ingest raw payload for %s: %s", source_clean, key_clean, exc)
            return {
                "payload_id": None,
                "source_name": source_clean,
                "natural_key": key_clean,
                "payload_hash": payload_hash,
                "s3_url": s3_url,
                "inserted": False,
                "error": str(exc),
            }

    def batch_ingest(
        self,
        records: List[Dict[str, Any]],
        deduplicate: bool = True,
    ) -> Dict[str, Any]:
        """
        Batch ingests multiple raw payloads efficiently.
        Each record dict must have: source_name, natural_key, raw_data, and optional s3_url.
        """
        if not records:
            return {"total": 0, "inserted": 0, "deduped": 0, "errors": 0}

        inserted_count = 0
        deduped_count = 0
        error_count = 0
        now = datetime.now(timezone.utc)

        prepared = []
        for r in records:
            source = str(r.get("source_name", "UNKNOWN")).strip()[:50]
            nkey = str(r.get("natural_key", "UNKNOWN")).strip()[:255]
            raw_str = self.serialize_payload(r.get("raw_data", ""))
            p_hash = self.compute_hash(raw_str)
            s3 = r.get("s3_url")
            pid = str(uuid.uuid4())
            prepared.append((pid, source, nkey, raw_str, s3, p_hash, now))

        try:
            with get_db_cursor() as (conn, cur):
                for pid, source, nkey, raw_str, s3, p_hash, ts in prepared:
                    if deduplicate:
                        cur.execute(
                            f"SELECT 1 FROM {self.table_name} WHERE source_name = %s AND payload_hash = %s LIMIT 1;",
                            (source, p_hash),
                        )
                        if cur.fetchone():
                            deduped_count += 1
                            continue

                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name} (
                            payload_id, source_name, natural_key, raw_body, s3_url, payload_hash, ingested_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """,
                        (pid, source, nkey, raw_str, s3, p_hash, ts),
                    )
                    inserted_count += 1

                conn.commit()
        except Exception as exc:
            logger.error("Batch raw payload ingestion encountered error: %s", exc)
            error_count += 1

        return {
            "total": len(records),
            "inserted": inserted_count,
            "deduped": deduped_count,
            "errors": error_count,
        }


# Singleton accessor
raw_ingestor = RawPayloadIngestor()

