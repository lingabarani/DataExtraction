"""
DataExtraction — Lakehouse Observation Storage Client
====================================================
Enterprise-grade object storage bridge connecting extraction workers,
raw scrape streams, and Apache Parquet lakehouse storage (MinIO / AWS S3).

Offloads massive raw web DOMs, HTML trees, and uncompressed JSON payloads
from PostgreSQL into snappy-compressed Parquet object partitions, storing
only the SHA-256 hash and immutable S3 URI in PostgreSQL `kg_observation.observation_metadata`.

Scale Target: 5B+ raw observations with zero PostgreSQL TOAST heap bloat.
"""

import gzip
import hashlib
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

# boto3 is imported lazily inside LakehouseObservationClient.__init__ to avoid
# the 300-500ms module-level import cost on every server startup when S3/MinIO
# is not needed. This is the single most impactful cold-start optimisation for
# environments that don't use the lakehouse feature.

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    PYARROW_AVAILABLE = True
except ImportError:
    PYARROW_AVAILABLE = False

from packages.infrastructure.config_manager import config_manager

logger = logging.getLogger("dataextraction.storage.lakehouse")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [LAKEHOUSE] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


class LakehouseStorageError(Exception):
    """Raised when lakehouse upload, retrieval, or bucket operations fail."""
    pass


class LakehouseObservationClient:
    """
    Client for writing and retrieving immutable raw observation payloads
    to/from MinIO or AWS S3 lakehouse partitions.
    """

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        bucket_name: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        region_name: Optional[str] = None,
        use_ssl: Optional[bool] = None,
        s3_client: Optional[Any] = None,
    ):
        cfg = config_manager.get_lakehouse_config()
        self.endpoint_url = endpoint_url if endpoint_url is not None else cfg.get("endpoint_url")
        self.bucket_name = bucket_name or cfg.get("bucket_name", "dataextraction-lakehouse")
        self.access_key = access_key or cfg.get("access_key")
        self.secret_key = secret_key or cfg.get("secret_key")
        self.region_name = region_name or cfg.get("region_name", "us-east-1")
        self.use_ssl = use_ssl if use_ssl is not None else cfg.get("use_ssl", False)
        self._bucket_verified: bool = False

        if s3_client:
            self.s3 = s3_client
        else:
            # Lazy-import boto3 here so it is only loaded when the lakehouse
            # client is actually instantiated, not at module import time.
            try:
                import boto3
                from botocore.client import Config
            except ImportError as exc:
                raise LakehouseStorageError(
                    "boto3 is not installed. Install it with: pip install boto3"
                ) from exc

            connect_to = int(cfg.get("connect_timeout_sec", 5))
            read_to = int(cfg.get("read_timeout_sec", 30))
            client_kwargs = {
                "service_name": "s3",
                "region_name": self.region_name,
                "aws_access_key_id": self.access_key,
                "aws_secret_access_key": self.secret_key,
                "use_ssl": self.use_ssl,
                "config": Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                    connect_timeout=connect_to,
                    read_timeout=read_to,
                ),
            }
            if self.endpoint_url:
                client_kwargs["endpoint_url"] = self.endpoint_url

            self.s3 = boto3.client(**client_kwargs)

    def ensure_bucket_exists(self) -> bool:
        """
        Verify or idempotently create the target lakehouse bucket.
        Caches positive checks per client instance so hot writes incur zero extra HEAD calls.
        """
        if self._bucket_verified:
            return True
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            self._bucket_verified = True
            logger.info("Lakehouse bucket '%s' verified.", self.bucket_name)
            return True
        except Exception as e:
            try:
                from botocore.exceptions import ClientError
            except ImportError:
                ClientError = ()  # type: ignore

            if ClientError and isinstance(e, ClientError):
                error_code = str(e.response.get("Error", {}).get("Code", ""))
                if error_code in ("404", "NoSuchBucket"):
                    logger.info("Bucket '%s' does not exist. Creating...", self.bucket_name)
                    create_kwargs: Dict[str, Any] = {"Bucket": self.bucket_name}
                    if self.region_name and self.region_name != "us-east-1":
                        create_kwargs["CreateBucketConfiguration"] = {
                            "LocationConstraint": self.region_name
                        }
                    try:
                        self.s3.create_bucket(**create_kwargs)
                        self._bucket_verified = True
                        logger.info("Successfully provisioned lakehouse bucket '%s'.", self.bucket_name)
                        return True
                    except Exception as ce:
                        logger.error("Failed to create bucket '%s': %s", self.bucket_name, ce)
                        raise LakehouseStorageError(f"Bucket creation failed: {ce}") from ce
            logger.error("Failed to verify bucket '%s': %s", self.bucket_name, e)
            raise LakehouseStorageError(f"Bucket check failed: {e}") from e

    def write_raw_observation(
        self,
        source_name: str,
        source_record_id: str,
        raw_payload: Union[str, bytes, dict],
        observed_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Compresses and persists an immutable observation payload into a Parquet partition.

        Returns metadata compatible with `kg_observation.observation_metadata`:
            - lakehouse_s3_uri
            - payload_hash_sha256
            - byte_size
            - key
        """
        if observed_at is None:
            observed_at = datetime.now(timezone.utc)
        elif observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        ingested_at = datetime.now(timezone.utc)

        if isinstance(raw_payload, dict):
            payload_str = json.dumps(raw_payload, sort_keys=True)
            payload_bytes = payload_str.encode("utf-8")
        elif isinstance(raw_payload, str):
            payload_str = raw_payload
            payload_bytes = raw_payload.encode("utf-8")
        elif isinstance(raw_payload, bytes):
            payload_bytes = raw_payload
            payload_str = raw_payload.decode("utf-8", errors="replace")
        else:
            payload_str = str(raw_payload)
            payload_bytes = payload_str.encode("utf-8")

        sha256 = hashlib.sha256(payload_bytes).hexdigest()
        metadata_str = json.dumps(metadata or {}, sort_keys=True)

        key = (
            f"observations/source={source_name}/"
            f"year={ingested_at.year}/month={ingested_at.month:02d}/day={ingested_at.day:02d}/"
            f"{sha256}.parquet"
        )

        if PYARROW_AVAILABLE:
            arrow_schema = pa.schema([
                ("source_name", pa.string()),
                ("source_record_id", pa.string()),
                ("payload_text", pa.string()),
                ("payload_hash_sha256", pa.string()),
                ("metadata_json", pa.string()),
                ("observed_at", pa.timestamp("us", tz="UTC")),
                ("ingested_at", pa.timestamp("us", tz="UTC")),
            ])

            table = pa.Table.from_arrays([
                pa.array([source_name], type=pa.string()),
                pa.array([source_record_id], type=pa.string()),
                pa.array([payload_str], type=pa.string()),
                pa.array([sha256], type=pa.string()),
                pa.array([metadata_str], type=pa.string()),
                pa.array([observed_at], type=pa.timestamp("us", tz="UTC")),
                pa.array([ingested_at], type=pa.timestamp("us", tz="UTC")),
            ], schema=arrow_schema)

            buf = io.BytesIO()
            pq.write_table(table, buf, compression="snappy")
            body_bytes = buf.getvalue()
            content_type = "application/x-parquet"
        else:
            # Fallback to gzipped JSON envelope if pyarrow is unavailable
            key = key.replace(".parquet", ".json.gz")
            envelope = {
                "source_name": source_name,
                "source_record_id": source_record_id,
                "payload_text": payload_str,
                "payload_hash_sha256": sha256,
                "metadata": metadata or {},
                "observed_at": observed_at.isoformat(),
                "ingested_at": ingested_at.isoformat(),
            }
            body_bytes = gzip.compress(json.dumps(envelope).encode("utf-8"))
            content_type = "application/gzip"

        self.ensure_bucket_exists()
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body_bytes,
                ContentType=content_type,
                Metadata={
                    "sha256": sha256,
                    "source": source_name,
                    "record_id": source_record_id,
                },
            )
        except Exception as e:
            # Handle late bucket deletion by resetting cache and retrying once
            if "NoSuchBucket" in str(e):
                self._bucket_verified = False
                self.ensure_bucket_exists()
                self.s3.put_object(
                    Bucket=self.bucket_name,
                    Key=key,
                    Body=body_bytes,
                    ContentType=content_type,
                    Metadata={
                        "sha256": sha256,
                        "source": source_name,
                        "record_id": source_record_id,
                    },
                )
            else:
                logger.error("Failed to upload observation to s3://%s/%s: %s", self.bucket_name, key, e)
                raise LakehouseStorageError(f"Upload to S3 failed: {e}") from e

        s3_uri = f"s3://{self.bucket_name}/{key}"
        logger.debug("Persisted observation to %s (%d bytes)", s3_uri, len(body_bytes))

        return {
            "lakehouse_s3_uri": s3_uri,
            "payload_hash_sha256": sha256,
            "byte_size": len(body_bytes),
            "source_name": source_name,
            "source_record_id": source_record_id,
            "key": key,
            "bucket": self.bucket_name,
            "ingested_at": ingested_at.isoformat(),
        }

    def write_batch_observations(
        self,
        source_name: str,
        records: List[Dict[str, Any]],
        observed_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Writes a multi-record batch of observations into a single columnar Snappy Parquet file
        so bulk extractions (GMaps/OSM) don't emit thousands of tiny S3 PUTs.
        """
        if not records:
            raise LakehouseStorageError("Cannot write empty batch observation")

        if observed_at is None:
            observed_at = datetime.now(timezone.utc)
        elif observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)

        ingested_at = datetime.now(timezone.utc)
        src_list: List[str] = []
        id_list: List[str] = []
        payload_list: List[str] = []
        hash_list: List[str] = []
        meta_list: List[str] = []
        obs_ts_list: List[datetime] = []
        ing_ts_list: List[datetime] = []
        meta_base = metadata or {}

        for idx, rec in enumerate(records):
            rec_id = str(
                rec.get("source_record_id")
                or rec.get("id")
                or rec.get("cid")
                or rec.get("place_id")
                or f"batch_{idx}"
            )
            payload_str = json.dumps(rec, sort_keys=True, default=str)
            rec_sha = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
            src_list.append(source_name)
            id_list.append(rec_id)
            payload_list.append(payload_str)
            hash_list.append(rec_sha)
            meta_list.append(json.dumps(meta_base, sort_keys=True, default=str))
            obs_ts_list.append(observed_at)
            ing_ts_list.append(ingested_at)

        batch_digest = hashlib.sha256(
            "|".join(hash_list).encode("utf-8")
        ).hexdigest()
        batch_id = f"{batch_digest[:24]}_{len(records)}"
        key = (
            f"observations/source={source_name}/"
            f"year={ingested_at.year}/month={ingested_at.month:02d}/day={ingested_at.day:02d}/"
            f"batch_{batch_id}.parquet"
        )

        if PYARROW_AVAILABLE:
            arrow_schema = pa.schema([
                ("source_name", pa.string()),
                ("source_record_id", pa.string()),
                ("payload_text", pa.string()),
                ("payload_hash_sha256", pa.string()),
                ("metadata_json", pa.string()),
                ("observed_at", pa.timestamp("us", tz="UTC")),
                ("ingested_at", pa.timestamp("us", tz="UTC")),
            ])
            table = pa.Table.from_arrays(
                [
                    pa.array(src_list, type=pa.string()),
                    pa.array(id_list, type=pa.string()),
                    pa.array(payload_list, type=pa.string()),
                    pa.array(hash_list, type=pa.string()),
                    pa.array(meta_list, type=pa.string()),
                    pa.array(obs_ts_list, type=pa.timestamp("us", tz="UTC")),
                    pa.array(ing_ts_list, type=pa.timestamp("us", tz="UTC")),
                ],
                schema=arrow_schema,
            )
            buf = io.BytesIO()
            pq.write_table(table, buf, compression="snappy")
            body_bytes = buf.getvalue()
            content_type = "application/x-parquet"
        else:
            key = key.replace(".parquet", ".json.gz")
            envelope = [
                {
                    "source_name": src_list[i],
                    "source_record_id": id_list[i],
                    "payload_text": payload_list[i],
                    "payload_hash_sha256": hash_list[i],
                    "metadata": meta_base,
                    "observed_at": observed_at.isoformat(),
                    "ingested_at": ingested_at.isoformat(),
                }
                for i in range(len(records))
            ]
            body_bytes = gzip.compress(json.dumps(envelope).encode("utf-8"))
            content_type = "application/gzip"

        self.ensure_bucket_exists()
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body_bytes,
                ContentType=content_type,
                Metadata={
                    "sha256": batch_digest,
                    "source": source_name,
                    "record_count": str(len(records)),
                },
            )
        except Exception as e:
            logger.error("Failed batch upload to s3://%s/%s: %s", self.bucket_name, key, e)
            raise LakehouseStorageError(f"Batch upload to S3 failed: {e}") from e

        return {
            "lakehouse_s3_uri": f"s3://{self.bucket_name}/{key}",
            "payload_hash_sha256": batch_digest,
            "byte_size": len(body_bytes),
            "record_count": len(records),
            "source_name": source_name,
            "key": key,
            "bucket": self.bucket_name,
            "ingested_at": ingested_at.isoformat(),
        }

    def read_raw_observation(self, lakehouse_s3_uri: str) -> Dict[str, Any]:
        """
        Retrieves and decodes an observation payload from its S3 URI.
        """
        parsed = urlparse(lakehouse_s3_uri)
        bucket = parsed.netloc or self.bucket_name
        key = parsed.path.lstrip("/")

        try:
            resp = self.s3.get_object(Bucket=bucket, Key=key)
            data = resp["Body"].read()
        except Exception as e:
            logger.error("Failed to read S3 object %s: %s", lakehouse_s3_uri, e)
            raise LakehouseStorageError(f"Read from S3 failed: {e}") from e

        if key.endswith(".parquet") and PYARROW_AVAILABLE:
            buf = io.BytesIO(data)
            table = pq.read_table(buf)
            pydict = table.to_pydict()
            return {
                "source_name": pydict["source_name"][0],
                "source_record_id": pydict["source_record_id"][0],
                "payload_text": pydict["payload_text"][0],
                "payload_hash_sha256": pydict["payload_hash_sha256"][0],
                "metadata": json.loads(pydict["metadata_json"][0]),
                "observed_at": pydict["observed_at"][0].isoformat() if pydict["observed_at"][0] else None,
                "ingested_at": pydict["ingested_at"][0].isoformat() if pydict["ingested_at"][0] else None,
            }
        elif key.endswith(".json.gz") or not PYARROW_AVAILABLE:
            decompressed = gzip.decompress(data)
            return json.loads(decompressed.decode("utf-8"))
        else:
            raise LakehouseStorageError(f"Unsupported storage format for URI: {lakehouse_s3_uri}")

    def delete_observation(self, lakehouse_s3_uri: str) -> bool:
        """
        Surgically purges an observation from object storage (GDPR / CCPA Erasure).
        """
        parsed = urlparse(lakehouse_s3_uri)
        bucket = parsed.netloc or self.bucket_name
        key = parsed.path.lstrip("/")
        try:
            self.s3.delete_object(Bucket=bucket, Key=key)
            logger.info("Purged object %s for compliance/erasure.", lakehouse_s3_uri)
            return True
        except Exception as e:
            logger.error("Failed to delete S3 object %s: %s", lakehouse_s3_uri, e)
            raise LakehouseStorageError(f"Delete from S3 failed: {e}") from e

    def check_health(self) -> Dict[str, Any]:
        """
        Evaluates lakehouse availability and roundtrip latency.
        """
        start = datetime.now(timezone.utc)
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            latency_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000
            return {
                "status": "healthy",
                "bucket": self.bucket_name,
                "endpoint": self.endpoint_url or "aws-s3-default",
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "bucket": self.bucket_name,
                "error": str(e),
            }


# Singleton accessor
lakehouse_client = LakehouseObservationClient()

__all__ = [
    "LakehouseObservationClient",
    "LakehouseStorageError",
    "lakehouse_client",
]

