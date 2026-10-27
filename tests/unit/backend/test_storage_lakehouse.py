"""
Unit Tests for Lakehouse Observation Storage Client
===================================================
Tests Parquet serialization, SHA-256 hashing, partition hierarchy,
S3/MinIO upload/download roundtrips, and compliance erasure operations.
"""

import gzip
import hashlib
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError
import pyarrow.parquet as pq

from packages.infrastructure.storage_lakehouse import (
    LakehouseObservationClient,
    LakehouseStorageError,
)


class TestLakehouseObservationClient(unittest.TestCase):

    def setUp(self):
        self.mock_s3 = MagicMock()
        self.client = LakehouseObservationClient(
            bucket_name="test-lakehouse-bucket",
            endpoint_url="http://mock-minio:9000",
            access_key="test-key",
            secret_key="test-secret",
            s3_client=self.mock_s3,
        )

    def test_ensure_bucket_exists_when_present(self):
        self.mock_s3.head_bucket.return_value = {}
        result = self.client.ensure_bucket_exists()
        self.assertTrue(result)
        self.mock_s3.head_bucket.assert_called_once_with(Bucket="test-lakehouse-bucket")
        self.mock_s3.create_bucket.assert_not_called()

    def test_ensure_bucket_exists_creates_when_missing(self):
        error_response = {"Error": {"Code": "404", "Message": "Not Found"}}
        self.mock_s3.head_bucket.side_effect = ClientError(error_response, "HeadBucket")

        result = self.client.ensure_bucket_exists()
        self.assertTrue(result)
        self.mock_s3.create_bucket.assert_called_once_with(Bucket="test-lakehouse-bucket")

    def test_write_raw_observation_dict_payload(self):
        payload = {"name": "Acme Corp", "ein": "12-3456789", "state": "TX"}
        expected_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

        res = self.client.write_raw_observation(
            source_name="sec_edgar",
            source_record_id="SEC-998877",
            raw_payload=payload,
            observed_at=datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc),
            metadata={"collector_version": "2.4.0"},
        )

        self.assertEqual(res["source_name"], "sec_edgar")
        self.assertEqual(res["source_record_id"], "SEC-998877")
        self.assertEqual(res["payload_hash_sha256"], expected_hash)
        self.assertTrue(res["lakehouse_s3_uri"].startswith("s3://test-lakehouse-bucket/observations/source=sec_edgar/"))
        self.assertTrue(res["key"].endswith(f"{expected_hash}.parquet"))

        self.mock_s3.put_object.assert_called_once()
        call_kwargs = self.mock_s3.put_object.call_args.kwargs
        self.assertEqual(call_kwargs["Bucket"], "test-lakehouse-bucket")
        self.assertEqual(call_kwargs["ContentType"], "application/x-parquet")
        self.assertEqual(call_kwargs["Metadata"]["sha256"], expected_hash)

        # Verify Parquet table contents
        buf = io.BytesIO(call_kwargs["Body"])
        table = pq.read_table(buf)
        pydict = table.to_pydict()
        self.assertEqual(pydict["source_name"][0], "sec_edgar")
        self.assertEqual(pydict["source_record_id"][0], "SEC-998877")
        self.assertEqual(json.loads(pydict["payload_text"][0]), payload)

    def test_write_raw_observation_string_payload(self):
        html_payload = "<html><body><h1>Acme Corporation</h1></body></html>"
        expected_hash = hashlib.sha256(html_payload.encode("utf-8")).hexdigest()

        res = self.client.write_raw_observation(
            source_name="manta_crawler",
            source_record_id="MANTA-1234",
            raw_payload=html_payload,
        )

        self.assertEqual(res["payload_hash_sha256"], expected_hash)
        self.mock_s3.put_object.assert_called_once()

    def test_read_raw_observation_parquet(self):
        import pyarrow as pa
        table = pa.Table.from_pydict({
            "source_name": ["denue_api"],
            "source_record_id": ["DENUE-5544"],
            "payload_text": ['{"company": "Industrias Monterrey", "rfc": "IMO900101XYZ"}'],
            "payload_hash_sha256": ["dummyhash123"],
            "metadata_json": ['{"tier": 1}'],
            "observed_at": [datetime(2026, 10, 27, 10, 0, tzinfo=timezone.utc)],
            "ingested_at": [datetime(2026, 10, 27, 10, 5, tzinfo=timezone.utc)],
        })
        buf = io.BytesIO()
        pq.write_table(table, buf, compression="snappy")

        mock_body = MagicMock()
        mock_body.read.return_value = buf.getvalue()
        self.mock_s3.get_object.return_value = {"Body": mock_body}

        data = self.client.read_raw_observation("s3://test-lakehouse-bucket/path/to/file.parquet")
        self.assertEqual(data["source_name"], "denue_api")
        self.assertEqual(data["source_record_id"], "DENUE-5544")
        self.assertIn("Industrias Monterrey", data["payload_text"])
        self.assertEqual(data["metadata"]["tier"], 1)

    def test_delete_observation_compliance_erasure(self):
        self.mock_s3.delete_object.return_value = {}
        result = self.client.delete_observation("s3://test-lakehouse-bucket/observations/source=sec/2026/file.parquet")
        self.assertTrue(result)
        self.mock_s3.delete_object.assert_called_once_with(
            Bucket="test-lakehouse-bucket",
            Key="observations/source=sec/2026/file.parquet",
        )

    def test_check_health(self):
        self.mock_s3.head_bucket.return_value = {}
        health = self.client.check_health()
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["bucket"], "test-lakehouse-bucket")
        self.assertIn("latency_ms", health)

    def test_upload_failure_raises_lakehouse_error(self):
        self.mock_s3.put_object.side_effect = Exception("Connection reset by peer")
        with self.assertRaises(LakehouseStorageError):
            self.client.write_raw_observation("sec", "rec1", "data")


if __name__ == "__main__":
    unittest.main()

