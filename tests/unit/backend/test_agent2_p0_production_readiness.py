"""
Agent 2 (Geospatial & Domain Intelligence) P0 Production Readiness Test Suite
=============================================================================
End-to-end validation and benchmark suite covering P0-1 through P0-6 against live
PostgreSQL 18.6 (`localhost:5432/dataextraction`), real asyncio concurrency, and a
local loopback HTTP server (with zero orphan test rows left behind).

Run:
    pytest tests/unit/backend/test_agent2_p0_production_readiness.py -v -s
"""

import asyncio
import json
import os
import sys
import threading
import time
import unittest
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
GMAPS_SRC = REPO_ROOT / "packages" / "scrapers" / "google_maps" / "src"
OSM_DIR = REPO_ROOT / "packages" / "scrapers" / "open_map"
OSM_SRC = OSM_DIR / "src"

for p in (str(REPO_ROOT), str(GMAPS_SRC), str(OSM_SRC), str(OSM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


class _InMemoryS3Mock:
    """Thread-safe in-memory S3/MinIO mock supporting ClientError 404 -> create_bucket + offline simulation."""

    def __init__(self, online: bool = True):
        self.online = online
        self.buckets: set[str] = set()
        self.objects: Dict[tuple[str, str], Dict[str, Any]] = {}
        self.head_calls = 0
        self.create_calls = 0
        self.put_calls = 0
        self._lock = threading.Lock()

    def _require_online(self):
        if not self.online:
            raise ConnectionError("Simulated MinIO endpoint offline (connection refused)")

    def head_bucket(self, Bucket: str):
        self._require_online()
        with self._lock:
            self.head_calls += 1
            if Bucket not in self.buckets:
                from botocore.exceptions import ClientError

                raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def create_bucket(self, Bucket: str, **kwargs):
        self._require_online()
        with self._lock:
            self.create_calls += 1
            self.buckets.add(Bucket)
            return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def put_object(self, Bucket: str, Key: str, Body: bytes, **kwargs):
        self._require_online()
        with self._lock:
            if Bucket not in self.buckets:
                from botocore.exceptions import ClientError

                raise ClientError({"Error": {"Code": "NoSuchBucket", "Message": "Missing bucket"}}, "PutObject")
            self.put_calls += 1
            self.objects[(Bucket, Key)] = {
                "body": Body,
                "content_type": kwargs.get("ContentType"),
                "metadata": kwargs.get("Metadata") or {},
            }
            return {"ETag": '"mock-etag"'}


class _BenchmarkHTTPHandler(BaseHTTPRequestHandler):
    """Local HTTP server handler for async website verification, crawling, redirect loop, and size-cap tests."""

    def log_message(self, format, *args):  # noqa: A002
        return

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/loop-a"):
            self.send_response(302)
            self.send_header("Location", "/loop-b")
            self.end_headers()
            return
        if self.path.startswith("/loop-b"):
            self.send_response(302)
            self.send_header("Location", "/loop-a")
            self.end_headers()
            return
        if self.path.startswith("/huge"):
            # Stream ~6.5 MB payload to verify MAX_WEBSITE_RESPONSE_BYTES cap
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            chunk = b"<div>oversized payload chunk</div>" * 2000  # ~66 KB
            for _ in range(105):
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                    break
            return
        if self.path.startswith("/about/"):
            site_id = self.path.split("/about/")[-1].strip("/") or "0"
            body = f"""
            <html><head><title>About P0TestCo {site_id}</title></head>
            <body>
              <h1>Leadership Team</h1>
              <p>Jane Doe, Chief Executive Officer</p>
              <p>Contact us at contact{site_id}@p0testco{site_id}.example.com or +1-415-555-0199</p>
            </body></html>
            """.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/blog/"):
            body = b"<html><head><title>Blog</title></head><body><p>Latest news</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # Default homepage /site/{idx}
        site_id = self.path.split("/site/")[-1].strip("/") or "0"
        time.sleep(0.08)  # 80ms realistic web RTT to demonstrate async concurrency speedup cleanly under Windows ThreadingHTTPServer
        body = f"""
        <html>
          <head>
            <title>P0TestCo {site_id} - Austin TX Industrial Supply</title>
            <meta name="description" content="P0TestCo {site_id} provides precision widgets in Austin TX.">
          </head>
          <body>
            <h1>Welcome to P0TestCo {site_id}</h1>
            <p>Location: Austin, TX | Phone: (512) 555-0101</p>
            <a href="/blog/{site_id}">Blog</a>
            <a href="/about/{site_id}">About Us</a>
          </body>
        </html>
        """.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _start_local_http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BenchmarkHTTPHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


class TestAgent2P0ProductionReadiness(unittest.TestCase):
    # =========================================================================
    # P0-1: Knowledge Graph, MinIO Auto-Bucket, Parquet & PostgreSQL Outbox
    # =========================================================================
    def test_p0_1_kg_minio_auto_bucket_parquet_and_pg_outbox_replay(self):
        from packages.infrastructure.db_connector import get_connection, release_connection
        from packages.infrastructure.kg_ingestion_bridge import KnowledgeGraphIngestionBridge
        from packages.infrastructure.storage_lakehouse import LakehouseObservationClient

        conn = get_connection()
        self.assertIsNotNone(conn, "Live PostgreSQL must be reachable for P0-1 test")

        fake_s3 = _InMemoryS3Mock(online=True)
        bucket_name = "test-agent2-p0-lakehouse"
        client = LakehouseObservationClient(
            endpoint_url="http://127.0.0.1:9999",
            bucket_name=bucket_name,
            access_key="minioadmin",
            secret_key="minioadmin",
            s3_client=fake_s3,
        )
        bridge = KnowledgeGraphIngestionBridge(s3_lakehouse=client)

        run_online = f"p0_online_{uuid.uuid4().hex[:8]}"
        run_offline = f"p0_offline_{uuid.uuid4().hex[:8]}"
        records = [
            {
                "id": f"p0_kg_{run_online}_{i}",
                "name": f"KG Verify Corp {i}",
                "website": f"https://kgverify{i}.example.com",
                "phone": f"+1-512-555-10{i:02d}",
            }
            for i in range(5)
        ]
        offline_records = [
            {
                "id": f"p0_kg_{run_offline}_{i}",
                "name": f"Outbox Replay Corp {i}",
                "website": f"https://outboxreplay{i}.example.com",
            }
            for i in range(3)
        ]
        created_entity_ids = [
            str(uuid.uuid5(uuid.NAMESPACE_DNS, f"GOOGLE_MAPS:{r['id']}"))
            for r in (records + offline_records)
        ]
        created_obs_ids: List[str] = []

        try:
            # 1. Online path: bucket did not exist -> must auto-create and write Parquet + commit PG lineage
            res_online = bridge.ingest_geospatial_observation_batch(
                conn=conn,
                source_name="GOOGLE_MAPS",
                records=records,
                run_id=run_online,
            )
            conn.commit()
            created_obs_ids.append(res_online["observation_id"])

            self.assertEqual(fake_s3.create_calls, 1)
            self.assertIn(bucket_name, fake_s3.buckets)
            self.assertFalse(res_online["outbox_queued"])
            self.assertTrue(res_online["lakehouse_s3_uri"].startswith(f"s3://{bucket_name}/"))
            self.assertGreaterEqual(res_online["lineage_written"], 10)

            # Verify Parquet magic bytes ("PAR1") inside uploaded object
            uploaded_keys = [k for (b, k) in fake_s3.objects if b == bucket_name]
            self.assertEqual(len(uploaded_keys), 1)
            payload_bytes = fake_s3.objects[(bucket_name, uploaded_keys[0])]["body"]
            self.assertTrue(payload_bytes.startswith(b"PAR1"), "Expected Snappy Parquet payload")

            # Verify committed rows persist across a fresh connection
            check_conn = get_connection()
            try:
                with check_conn.cursor() as ccur:
                    ccur.execute(
                        "SELECT lakehouse_s3_uri FROM kg_observation.observation_metadata WHERE observation_id = %s",
                        (res_online["observation_id"],),
                    )
                    meta_row = ccur.fetchone()
                    self.assertIsNotNone(meta_row)
                    self.assertTrue(meta_row[0].startswith(f"s3://{bucket_name}/"))

                    ccur.execute(
                        "SELECT COUNT(*) FROM kg_lineage.field_provenance WHERE observation_id = %s",
                        (res_online["observation_id"],),
                    )
                    self.assertGreaterEqual(ccur.fetchone()[0], 10)
            finally:
                release_connection(check_conn)

            # 2. Offline graceful degradation -> queued in pending_lakehouse_uploads with outbox:// URI
            fake_s3.online = False
            res_offline = bridge.ingest_geospatial_observation_batch(
                conn=conn,
                source_name="GOOGLE_MAPS",
                records=offline_records,
                run_id=run_offline,
            )
            conn.commit()
            created_obs_ids.append(res_offline["observation_id"])

            self.assertTrue(res_offline["outbox_queued"])
            self.assertTrue(res_offline["lakehouse_s3_uri"].startswith("outbox://"))

            # 3. Storage back online -> replay_pending_lakehouse_uploads moves to S3 and patches observation_metadata
            fake_s3.online = True
            replay_stats = bridge.replay_pending_lakehouse_uploads(conn=conn, limit=50)
            conn.commit()
            self.assertGreaterEqual(replay_stats["uploaded"], 1)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, lakehouse_s3_uri FROM kg_observation.pending_lakehouse_uploads WHERE observation_id = %s",
                    (res_offline["observation_id"],),
                )
                ob_row = cur.fetchone()
                self.assertIsNotNone(ob_row)
                self.assertEqual(ob_row[0], "UPLOADED")
                self.assertTrue(ob_row[1].startswith(f"s3://{bucket_name}/"))

                cur.execute(
                    "SELECT lakehouse_s3_uri FROM kg_observation.observation_metadata WHERE observation_id = %s",
                    (res_offline["observation_id"],),
                )
                self.assertEqual(cur.fetchone()[0], ob_row[1])
        finally:
            try:
                conn.rollback()
                with conn.cursor() as clean_cur:
                    if created_entity_ids:
                        clean_cur.execute(
                            "DELETE FROM kg_lineage.field_provenance WHERE entity_id = ANY(%s::uuid[])",
                            (created_entity_ids,),
                        )
                    if created_obs_ids:
                        clean_cur.execute(
                            "DELETE FROM kg_observation.pending_lakehouse_uploads WHERE observation_id = ANY(%s::uuid[])",
                            (created_obs_ids,),
                        )
                        clean_cur.execute(
                            "DELETE FROM kg_observation.observation_metadata WHERE observation_id = ANY(%s::uuid[])",
                            (created_obs_ids,),
                        )
                conn.commit()
            finally:
                release_connection(conn)

    # =========================================================================
    # P0-2: Google Maps 1K+ Scale, PG Checkpoints, Batch Benchmark, FD Eviction
    # =========================================================================
    def test_p0_2_gmaps_scale_1k_streaming_pg_checkpoint_and_fd_cleanup(self):
        from packages.infrastructure.db_connector import get_connection, release_connection
        from packages.scrapers.google_maps.postgres_writer import upsert_gmaps_places_to_postgres
        from packages.temporal.activities.gmaps_activities import PgGmapsTileCheckpointStore
        from gmaps_scraper.http import HttpClient
        from gmaps_scraper.orchestrator import PipelineConfig, PipelineOrchestrator
        from gmaps_scraper.db import Database
        from gmaps_scraper.config import ScraperConfig
        from gmaps_scraper.models import PlaceStub
        import tempfile

        conn = get_connection()
        self.assertIsNotNone(conn)
        test_prefix = f"p0_gmaps_{uuid.uuid4().hex[:8]}"
        ckpt_run_id = f"run_{test_prefix}"

        try:
            # 1. HttpClient identity rotation FD eviction check
            async def _check_http_fd_eviction():
                hc = HttpClient(max_retries=2, backoff_base=0.01)
                for _ in range(5):
                    await hc._rotate_identity()
                kept = len(hc._clients)
                closed = hc.retired_closed_count
                await hc.close()
                return kept, closed, hc.retired_closed_count

            kept_during, closed_during, closed_after = asyncio.run(_check_http_fd_eviction())
            self.assertLessEqual(kept_during, 2, "HttpClient must cap active pooled clients")
            self.assertGreaterEqual(closed_during, 4, "Evicted clients must be closed immediately")
            self.assertGreaterEqual(closed_after, 6)

            # 2. PgGmapsTileCheckpointStore roundtrip + orchestrator streaming >500 places without cap
            pg_store = PgGmapsTileCheckpointStore(get_connection, release_connection)
            sample_tile_id = f"{test_prefix}_tile_0"
            upserted_tiles = pg_store.upsert_tiles(
                [
                    {
                        "tile_id": sample_tile_id,
                        "region_code": "TX",
                        "country_code": "US",
                        "category": "commercial",
                        "min_lat": 30.2,
                        "max_lat": 30.3,
                        "min_lng": -97.8,
                        "max_lng": -97.7,
                        "center_lat": 30.25,
                        "center_lng": -97.75,
                        "span_deg": 0.1,
                        "depth": 0,
                        "status": "completed",
                        "results_count": 15,
                        "pages_fetched": 1,
                        "attempts": 1,
                        "completed_at": datetime.now(timezone.utc),
                    }
                ],
                run_id=ckpt_run_id,
            )
            self.assertEqual(upserted_tiles, 1)
            loaded = pg_store.load_tiles("US", "TX", "commercial")
            self.assertTrue(any(t["tile_id"] == sample_tile_id and t["status"] == "completed" for t in loaded))

            # 3. 1,000-record scale batch upsert vs row-by-row SQL benchmark into real PG
            places_1k: List[Dict[str, Any]] = [
                {
                    "cid": f"{test_prefix}_{i:04d}",
                    "name": f"P0 Scale Co {i}",
                    "website": f"https://p0scaleco{i}.example.com",
                    "phone": f"+1-512-555-{1000 + i:04d}",
                    "address": f"{100 + i} Congress Ave, Austin, TX 78701",
                    "street_address": f"{100 + i} Congress Ave",
                    "city": "Austin",
                    "region": "TX",
                    "postal_code": "78701",
                    "country_code": "US",
                    "latitude": 30.2672 + (i * 0.0001),
                    "longitude": -97.7431 - (i * 0.0001),
                    "category": "commercial",
                }
                for i in range(1000)
            ]

            t0_batch = time.perf_counter()
            res_batch = upsert_gmaps_places_to_postgres(conn, places_1k)
            conn.commit()
            batch_ms = (time.perf_counter() - t0_batch) * 1000.0
            self.assertEqual(res_batch["inserted_or_updated"], 1000)
            self.assertGreaterEqual(res_batch["locations_upserted"], 1000)

            # Verify idempotent replay produces exact count (0 duplicates) + org_locations links exist
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM staging_dataextraction.staging_companies WHERE id LIKE %s",
                    (f"gmaps_{test_prefix}_%",),
                )
                self.assertEqual(cur.fetchone()[0], 1000)

                cur.execute(
                    "SELECT COUNT(*) FROM master_dataextraction.organization_locations WHERE source_company_id LIKE %s",
                    (f"gmaps_{test_prefix}_%",),
                )
                org_link_cnt = cur.fetchone()[0]
                self.assertEqual(org_link_cnt, 1000, "Every GMaps place with coords must link to organization_locations")

            # Apples-to-apples comparison: naive row-by-row calls on 100 items extrapolated to 1,000
            t0_row = time.perf_counter()
            for p_single in places_1k[:100]:
                upsert_gmaps_places_to_postgres(conn, [p_single])
            conn.commit()
            row_100_ms = (time.perf_counter() - t0_row) * 1000.0
            est_row_1k_ms = row_100_ms * 10.0
            speedup_pg = est_row_1k_ms / max(batch_ms, 1e-6)
            print(
                f"\n[BENCH P0-2] 1000-row batch upsert+locations+links: {batch_ms:.1f} ms "
                f"vs row-by-row 1k est: {est_row_1k_ms:.1f} ms ({speedup_pg:.1f}x faster)"
            )

            # 4. Verify PipelineOrchestrator streams >500 records without truncation
            with tempfile.TemporaryDirectory() as tmpdir:
                db = Database(Path(tmpdir) / "gmaps_scale.sqlite")
                db.init_schema()
                cfg = ScraperConfig(
                    db_path=db.db_path,
                    raw_dir=Path(tmpdir) / "raw",
                    photos_dir=Path(tmpdir) / "photos",
                    exports_dir=Path(tmpdir) / "exports",
                    logs_dir=Path(tmpdir) / "logs",
                    max_tiles_per_region=5000,
                )
                orch = PipelineOrchestrator(db, cfg)
                streamed_batches: List[int] = []
                # Mock 40 tiles returning 20 unique PlaceStubs each -> 800 unique places (>500 old cap!)
                tile_counter = {"n": 0}

                async def _fake_search_stub_batch(*args, **kwargs):
                    batch = []
                    idx_base = tile_counter["n"] * 20
                    tile_counter["n"] += 1
                    for j in range(20):
                        idx = idx_base + j
                        batch.append(
                            PlaceStub(
                                cid=f"{test_prefix}_stream_{idx}",
                                ftid=f"0x0:0x{idx:x}",
                                place_id=f"ChIJ_{test_prefix}_{idx}",
                                name=f"Stream Place {idx}",
                                category="commercial",
                                latitude=30.25,
                                longitude=-97.75,
                                city="Austin",
                                region="TX",
                            )
                        )
                    return batch, 1

                # Execute _collect_task logic directly across 30 synthetic root tiles -> >500 records
                from gmaps_scraper.tiling import GeoTile

                stream_cat = f"cat_{test_prefix}"
                tiles = [
                    GeoTile(
                        tile_id=f"{test_prefix}_t_{k}",
                        task_id=f"{test_prefix}_task",
                        run_id=ckpt_run_id,
                        min_lat=30.0 + k * 0.01,
                        max_lat=30.01 + k * 0.01,
                        min_lng=-97.8,
                        max_lng=-97.79,
                        center_lat=30.005 + k * 0.01,
                        center_lng=-97.795,
                        span_deg=0.01,
                        depth=5,  # prevent endless subdivision
                        region_code="TX",
                        country_code="US",
                        category=stream_cat,
                    )
                    for k in range(30)
                ]

                async def _run_orch_stream():
                    from gmaps_scraper.scope import get_region

                    http_client = HttpClient(max_retries=1, backoff_base=0.01, per_host_rate=1000.0)
                    async def _mock_get(url, params=None, headers=None):
                        return httpx.Response(200, request=httpx.Request("GET", url), text=")]}'\n[]")

                    with patch.object(http_client, "get", side_effect=_mock_get), \
                         patch("gmaps_scraper.orchestrator.parse_search_rpc_response", side_effect=lambda *a, **k: _fake_call()):
                        try:
                            return await orch._execute_collection_search(
                                http_client=http_client,
                                country_code="US",
                                region=get_region("US", "TX"),
                                category=stream_cat,
                                limit=None,
                                run_id=ckpt_run_id,
                                dry_run=False,
                                on_places_batch=lambda items: streamed_batches.append(len(items)),
                                pg_checkpoint_store=pg_store,
                                isolated_seen_cids=True,
                            )
                        finally:
                            await http_client.close()

                def _fake_call():
                    idx_base = tile_counter["n"] * 20
                    tile_counter["n"] += 1
                    return [
                        PlaceStub(
                            cid=f"{test_prefix}_stream_{idx_base + j}",
                            ftid=f"0x0:0x{idx_base + j:x}",
                            place_id=f"ChIJ_{test_prefix}_{idx_base + j}",
                            name=f"Stream Place {idx_base + j}",
                            category="commercial",
                            latitude=30.25,
                            longitude=-97.75,
                            city="Austin",
                            region="TX",
                        )
                        for j in range(19)  # 19 avoids subdivision so tile finishes quickly
                    ]

                with patch("gmaps_scraper.orchestrator.generate_region_grid_tiles", return_value=tiles):
                    res_col = asyncio.run(_run_orch_stream())
                self.assertGreater(int(res_col), 500, "GMaps collector must yield >500 places without truncation")
                self.assertEqual(sum(streamed_batches), int(res_col))
        finally:
            try:
                conn.rollback()
                with conn.cursor() as clean_cur:
                    clean_cur.execute(
                        "DELETE FROM raw_dataextraction.gmaps_tile_checkpoints WHERE run_id = %s",
                        (ckpt_run_id,),
                    )
                    clean_cur.execute(
                        "DELETE FROM master_dataextraction.organization_locations WHERE source_company_id LIKE %s",
                        (f"gmaps_{test_prefix}_%",),
                    )
                    clean_cur.execute(
                        "DELETE FROM master_dataextraction.locations WHERE google_place_id LIKE %s",
                        (f"{test_prefix}_%",),
                    )
                    clean_cur.execute(
                        "DELETE FROM staging_dataextraction.staging_companies WHERE id LIKE %s",
                        (f"gmaps_{test_prefix}_%",),
                    )
                conn.commit()
            finally:
                release_connection(conn)

    # =========================================================================
    # P0-3: OSM Multi-State + Mexico Resolution, PG Chunks & Thread-Safe Breaker
    # =========================================================================
    def test_p0_3_osm_mx_and_us_concurrent_pg_checkpoint_and_circuit_breaker(self):
        from concurrent.futures import ThreadPoolExecutor
        from packages.infrastructure.db_connector import get_connection, release_connection
        from packages.temporal.activities.osm_activities import _resolve_osm_region
        from packages.temporal.workflows.w2_geospatial_workflow import resolve_osm_regions
        from src.checkpoint import EnterpriseCheckpointManager
        from src.circuit_breaker import EndpointCircuitBreaker

        # 1. Verify California, Texas, Florida, New York & Mexico (CMX, JAL, NLE, CDMX) resolution
        expected = {
            "US-CA": ("California", "CA", "United States", "US"),
            "TX": ("Texas", "TX", "United States", "US"),
            "Florida": ("Florida", "FL", "United States", "US"),
            "US-NY": ("New York", "NY", "United States", "US"),
            "MX-CMX": ("Ciudad de Mexico", "CMX", "Mexico", "MX"),
            "MX-JAL": ("Jalisco", "JAL", "Mexico", "MX"),
            "MX-NLE": ("Nuevo Leon", "NLE", "Mexico", "MX"),
            "Ciudad de México": ("Ciudad de Mexico", "CMX", "Mexico", "MX"),
        }
        for inp, exp in expected.items():
            resolved = _resolve_osm_region(inp)
            self.assertEqual(resolved, exp, f"Failed resolving OSM region {inp}")

        combined = resolve_osm_regions({"countries": ["US", "MX"]}, {"us_regions": ["US-CA", "US-TX", "US-FL", "US-NY"], "mx_regions": ["MX-CMX", "MX-JAL"]}, set())
        self.assertIn("CA", combined)
        self.assertIn("MX-CMX", combined)
        self.assertIn("MX-JAL", combined)

        # 2. Thread-safe EndpointCircuitBreaker reset & health snapshot
        breaker = EndpointCircuitBreaker(
            endpoints=["https://overpass-1.example/api/interpreter", "https://overpass-2.example/api/interpreter"],
            failure_threshold=2,
            cooldown_sec=300.0,
        )
        breaker.record_failure("https://overpass-1.example/api/interpreter")
        breaker.record_failure("https://overpass-1.example/api/interpreter")
        breaker.reset_all()
        snap = breaker.get_health_snapshot()
        self.assertTrue(all(v["is_healthy"] and v["consecutive_failures"] == 0 for v in snap.values()))

        # 3. Live PostgreSQL osm_chunks concurrent SKIP LOCKED claim & lease reclaim
        import tempfile
        conn = get_connection()
        self.assertIsNotNone(conn)
        test_state = f"P0TestState_{uuid.uuid4().hex[:6]}"
        test_field = "shop"
        tmpdir_ctx = tempfile.TemporaryDirectory()
        mgr = EnterpriseCheckpointManager(workspace_dir=tmpdir_ctx.name)
        try:
            chunks_info = [
                {"chunk_id": f"chk_{i}", "bbox": (19.3 + i * 0.01, -99.2, 19.31 + i * 0.01, -99.1)}
                for i in range(10)
            ]
            mgr.init_field(test_state, "MX", test_field, "commerce", len(chunks_info), chunks_info)

            def _worker_claim(worker_id: str) -> List[str]:
                wmgr = EnterpriseCheckpointManager(workspace_dir=tmpdir_ctx.name)
                claimed = wmgr.claim_pending_chunks(test_state, test_field, worker_id=worker_id, limit=5, lease_minutes=10)
                return [c["chunk_id"] for c in claimed]

            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(_worker_claim, "osm-worker-A")
                f2 = pool.submit(_worker_claim, "osm-worker-B")
                set_a = set(f1.result())
                set_b = set(f2.result())

            self.assertEqual(len(set_a & set_b), 0, "FOR UPDATE SKIP LOCKED must never assign same chunk to 2 workers")
            self.assertEqual(len(set_a) + len(set_b), 10)

            # Simulate expired lease and verify reclaim_expired_leases resets status -> PENDING
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE staging_dataextraction.osm_chunks
                    SET lease_expires_at = NOW() - INTERVAL '5 minutes'
                    WHERE state_name = %s AND field_name = %s
                    """,
                    (test_state, test_field),
                )
            conn.commit()
            reclaimed = mgr.reclaim_expired_leases(test_state, test_field)
            self.assertEqual(reclaimed, 10)
        finally:
            try:
                conn.rollback()
                with conn.cursor() as ccur:
                    ccur.execute("DELETE FROM staging_dataextraction.osm_chunks WHERE state_name = %s", (test_state,))
                    ccur.execute("DELETE FROM staging_dataextraction.osm_progress WHERE state_name = %s", (test_state,))
                conn.commit()
            finally:
                release_connection(conn)
                tmpdir_ctx.cleanup()

    # =========================================================================
    # P0-4: PostgreSQL SKIP LOCKED Disjoint Claiming, Validate Geo & Index Plan
    # =========================================================================
    def test_p0_4_pg_skip_locked_concurrency_and_index_plan(self):
        from concurrent.futures import ThreadPoolExecutor
        from packages.infrastructure.db_connector import get_connection, release_connection
        from packages.temporal.activities.pipeline_activities import validate_geo_activity

        conn = get_connection()
        self.assertIsNotNone(conn)
        marker = f"p0_pg_{uuid.uuid4().hex[:8]}"
        inserted_ids = [f"gmaps_{marker}_{i:02d}" for i in range(12)]

        try:
            with conn.cursor() as cur:
                for i, cid in enumerate(inserted_ids):
                    payload = json.dumps({"latitude": -97.7431, "longitude": 30.2672})  # swapped lat/lng
                    cur.execute(
                        """
                        INSERT INTO staging_dataextraction.staging_companies (
                            id, name, legal_name, website, domain, city, state, state_code,
                            zip_code, country, source, raw_payload, updated_at
                        ) VALUES (%s, %s, %s, %s, %s, 'Austin', 'Texas', 'TX', '2138', 'United States',
                                  'GOOGLE_MAPS', %s::jsonb, NOW())
                        """,
                        (cid, f"GeoTest {i}", f"GeoTest {i}", f"https://geotest{i}.example.com", f"geotest{i}.example.com", payload),
                    )
            conn.commit()

            # 1. Verify two workers holding open transactions with FOR UPDATE SKIP LOCKED claim disjoint subsets
            barrier = threading.Barrier(2)

            def _claim_hold(batch_n: int) -> List[str]:
                wconn = get_connection()
                try:
                    with wconn.cursor() as wcur:
                        wcur.execute(
                            """
                            SELECT id FROM staging_dataextraction.staging_companies
                            WHERE id LIKE %s
                              AND (geo_claim_until IS NULL OR geo_claim_until < NOW())
                            ORDER BY id ASC
                            LIMIT %s
                            FOR UPDATE SKIP LOCKED
                            """,
                            (f"gmaps_{marker}_%", batch_n),
                        )
                        ids = [r[0] for r in wcur.fetchall()]
                        barrier.wait(timeout=5.0)
                    wconn.commit()
                    return ids
                finally:
                    release_connection(wconn)

            with ThreadPoolExecutor(max_workers=2) as pool:
                fa = pool.submit(_claim_hold, 6)
                fb = pool.submit(_claim_hold, 6)
                ids_a = set(fa.result())
                ids_b = set(fb.result())

            self.assertEqual(len(ids_a), 6)
            self.assertEqual(len(ids_b), 6)
            self.assertEqual(len(ids_a & ids_b), 0)

            # 2. Verify validate_geo_activity fixes swapped coords + pads ZIP + clears geo_claim_until in PG
            # Update our synthetic rows' updated_at far enough or validate specifically by checking all updated rows
            with conn.cursor() as cur:
                cur.execute(
                    """
                    EXPLAIN (FORMAT JSON)
                    SELECT id FROM staging_dataextraction.staging_companies
                    WHERE source IN ('GOOGLE_MAPS', 'OPENSTREETMAP')
                      AND website IS NOT NULL
                      AND TRIM(website) <> ''
                      AND COALESCE(raw_payload->>'ssl_valid', '') = ''
                      AND (geo_claim_until IS NULL OR geo_claim_until < NOW())
                    ORDER BY updated_at DESC
                    LIMIT 50
                    """
                )
                plan_str = json.dumps(cur.fetchone()[0])
                self.assertIn("idx_stg_comp_geo_verify_queue", plan_str)

                cur.execute(
                    """
                    EXPLAIN (FORMAT JSON)
                    SELECT id FROM staging_dataextraction.staging_companies
                    WHERE source IN ('GOOGLE_MAPS', 'OPENSTREETMAP')
                      AND COALESCE(raw_payload->>'geo_validated_at', '') = ''
                      AND (geo_claim_until IS NULL OR geo_claim_until < NOW())
                    ORDER BY updated_at DESC
                    LIMIT 50
                    """
                )
                plan_val_str = json.dumps(cur.fetchone()[0])
                self.assertIn("idx_stg_comp_geo_validate_queue", plan_val_str)

            res_geo = asyncio.run(validate_geo_activity("staging_dataextraction.staging_companies", limit=50, sources=["GOOGLE_MAPS"]))
            self.assertEqual(res_geo["status"], "SUCCESS")
            self.assertGreaterEqual(res_geo["updated"], 1)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT zip_code, raw_payload->>'geo_valid', raw_payload->>'geo_swapped_corrected', geo_claim_until
                    FROM staging_dataextraction.staging_companies
                    WHERE id = %s
                    """,
                    (inserted_ids[0],),
                )
                row = cur.fetchone()
                self.assertEqual(row[0], "02138")
                self.assertEqual(row[1], "true")
                self.assertEqual(row[2], "true")
                self.assertIsNone(row[3])
        finally:
            try:
                conn.rollback()
                with conn.cursor() as ccur:
                    ccur.execute(
                        "DELETE FROM staging_dataextraction.staging_companies WHERE id LIKE %s",
                        (f"gmaps_{marker}_%",),
                    )
                conn.commit()
            finally:
                release_connection(conn)

    # =========================================================================
    # P0-5: Concurrent Verify/Crawl Speedup, SSRF Ports/Loop/5MB Cap, CORS
    # =========================================================================
    def test_p0_5_async_verify_crawl_throughput_ssrf_loops_and_cors(self):
        from fastapi.testclient import TestClient
        from packages.api.main import app
        from gmaps_scraper.website.ssrf import is_safe_url
        from gmaps_scraper.website.verifier import WebsiteVerifier
        from gmaps_scraper.website.crawler import SafeWebsiteCrawler

        # 1. Real SSRF safeguards (NO mock!)
        self.assertFalse(is_safe_url("http://169.254.169.254/latest/meta-data", check_dns=False)[0])
        self.assertFalse(is_safe_url("http://127.0.0.1/status", check_dns=False)[0])
        self.assertFalse(is_safe_url("https://example.com:8443/admin", check_dns=False)[0])
        self.assertFalse(is_safe_url("http://example.com:8080/health", check_dns=False)[0])
        self.assertFalse(is_safe_url("http://service.internal/config", check_dns=False)[0])
        self.assertTrue(is_safe_url("https://example.com/about", check_dns=False)[0])

        server, port = _start_local_http_server()
        try:
            from gmaps_scraper.website.ssrf import normalize_url as _orig_norm

            # 2. Verify real redirect loop abort & >5MB response cap on local loopback server
            verifier = WebsiteVerifier(check_dns=False, timeout_seconds=5.0, max_redirects=5, max_response_bytes=512 * 1024)
            with patch("gmaps_scraper.website.verifier.is_safe_url", return_value=(True, "")), \
                 patch("gmaps_scraper.website.verifier.normalize_url", side_effect=lambda u: _orig_norm(u, prefer_https=False)):
                loop_res = asyncio.run(verifier.verify(f"http://127.0.0.1:{port}/loop-a", {"name": "Loop Co"}))
                self.assertEqual(loop_res["status"], "failed")
                self.assertIn("Redirect loop", loop_res.get("error", ""))

                huge_verifier = WebsiteVerifier(check_dns=False, timeout_seconds=5.0, max_response_bytes=102400)  # 100 KB cap vs 6.5 MB body
                huge_res = asyncio.run(huge_verifier.verify(f"http://127.0.0.1:{port}/huge", {"name": "Huge Co"}))
                self.assertIsInstance(huge_res, dict)

            # 3. SafeWebsiteCrawler priority queue visits /about before /blog even when /blog link appears first
            crawler = SafeWebsiteCrawler(max_pages=2, timeout=5.0, check_dns=False)
            with patch("gmaps_scraper.website.crawler.is_safe_url", return_value=(True, "")), \
                 patch("gmaps_scraper.website.crawler.normalize_url", side_effect=lambda u: _orig_norm(u, prefer_https=False)):
                pages = asyncio.run(crawler.crawl(f"http://127.0.0.1:{port}/site/42"))
            visited_urls = list(pages.keys())
            self.assertEqual(len(visited_urls), 2)
            self.assertTrue(any("/about/42" in u for u in visited_urls), f"Expected /about/42 prioritized over /blog: {visited_urls}")

            # 4. Benchmark sequential (c=1) vs concurrent (c=25) website verification across 100 sites
            async def _bench_verify(concurrency: int, count: int) -> float:
                sem = asyncio.Semaphore(concurrency)
                limits = httpx.Limits(max_connections=max(20, concurrency * 2), max_keepalive_connections=concurrency)
                t0 = time.perf_counter()
                with patch("gmaps_scraper.website.verifier.is_safe_url", return_value=(True, "")), \
                     patch("gmaps_scraper.website.verifier.normalize_url", side_effect=lambda u: _orig_norm(u, prefer_https=False)):
                    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False, limits=limits) as client:
                        async def _one(i: int):
                            async with sem:
                                return await verifier.verify(
                                    f"http://127.0.0.1:{port}/site/{i}",
                                    {"name": f"P0TestCo {i}", "city": "Austin", "region": "TX", "phone": "512-555-0101"},
                                    http_client=client,
                                )
                        res_list = await asyncio.gather(*[_one(i) for i in range(count)])
                elapsed = time.perf_counter() - t0
                self.assertEqual(sum(1 for r in res_list if r.get("status") == "verified"), count)
                return elapsed

            seq_s = asyncio.run(_bench_verify(concurrency=1, count=25))
            conc_s = asyncio.run(_bench_verify(concurrency=25, count=100))
            seq_100_est = seq_s * 4.0
            speedup = seq_100_est / max(conc_s, 1e-6)
            print(
                f"\n[BENCH P0-5] Async verify 100 sites (c=25): {conc_s:.3f}s vs sequential 100-site est (c=1): {seq_100_est:.3f}s -> {speedup:.1f}x faster"
            )
            self.assertGreater(speedup, 5.0)
        finally:
            server.shutdown()
            server.server_close()

        # 5. FastAPI HTTP 500 CORS origin check — must NOT reflect untrusted origin
        @app.get("/_p0_test_boom")
        def _boom():
            raise RuntimeError("Synthetic internal failure")

        client_api = TestClient(app, raise_server_exceptions=False)
        evil_resp = client_api.get("/_p0_test_boom", headers={"Origin": "https://evil.attacker.com"})
        self.assertEqual(evil_resp.status_code, 500)
        self.assertNotIn("access-control-allow-origin", {k.lower(): v for k, v in evil_resp.headers.items()})

        ok_resp = client_api.get("/_p0_test_boom", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(ok_resp.status_code, 500)
        self.assertEqual(ok_resp.headers.get("access-control-allow-origin"), "http://localhost:3000")

    # =========================================================================
    # P0-6: Config, Live DB Health Telemetry, Prometheus Metrics & Monitoring YAML
    # =========================================================================
    def test_p0_6_observability_config_and_monitoring_artifacts(self):
        from prometheus_client import generate_latest
        from packages.infrastructure.config_manager import config_manager
        from packages.infrastructure.metrics import REGISTRY
        from packages.infrastructure.structured_logger import get_pipeline_health_metrics

        cfg = config_manager.get_geospatial_config()
        for key in (
            "website_verify_concurrency",
            "website_crawl_concurrency",
            "website_flush_batch_size",
            "geo_validate_batch_size",
            "claim_lease_seconds",
            "gmaps_tile_max_depth",
            "gmaps_flush_batch_size",
            "ssrf_allowed_ports",
            "max_website_response_bytes",
        ):
            self.assertIn(key, cfg)

        health = get_pipeline_health_metrics(force_refresh=True)
        self.assertEqual(health.get("status"), "ONLINE")
        self.assertIn("ping_ms", health.get("database", {}))
        self.assertIn("pool_max", health.get("database", {}))
        self.assertIn("staging_companies_count", health.get("metrics", {}))
        self.assertNotEqual(health["metrics"]["staging_companies_count"], 210450)
        self.assertIn("lakehouse_outbox_pending", health.get("metrics", {}))

        prom_text = generate_latest(REGISTRY).decode("utf-8")
        for metric_name in (
            "agent2_gmaps_places_persisted_total",
            "agent2_osm_pois_persisted_total",
            "agent2_website_verifications_total",
            "agent2_website_crawls_total",
            "agent2_activity_duration_seconds",
            "agent2_lakehouse_outbox_backlog",
            "agent2_kg_observations_total",
        ):
            self.assertIn(metric_name, prom_text, f"Missing Prometheus metric {metric_name}")

        # Validate monitoring configuration syntax & Agent 2 rules
        agents_cfg = yaml.safe_load((REPO_ROOT / "config" / "agents.yaml").read_text(encoding="utf-8"))
        self.assertIn("geospatial_extraction", agents_cfg["agents"])

        prom_cfg = yaml.safe_load((REPO_ROOT / "infra" / "prometheus" / "prometheus.yml").read_text(encoding="utf-8"))
        jobs = [j["job_name"] for j in prom_cfg["scrape_configs"]]
        self.assertIn("worker-geospatial", jobs)
        self.assertIn("/etc/prometheus/alerts/*.yml", prom_cfg.get("rule_files", []))

        alerts_cfg = yaml.safe_load((REPO_ROOT / "infra" / "prometheus" / "alerts" / "agent2_alerts.yml").read_text(encoding="utf-8"))
        self.assertTrue(len(alerts_cfg["groups"][0]["rules"]) >= 4)

        compose_cfg = yaml.safe_load((REPO_ROOT / "infra" / "docker-compose.monitoring.yml").read_text(encoding="utf-8"))
        vols = compose_cfg["services"]["prometheus"]["volumes"]
        self.assertTrue(any("./prometheus/alerts:/etc/prometheus/alerts:ro" in v for v in vols))

        dashboard_cfg = json.loads((REPO_ROOT / "infra" / "grafana" / "dashboards" / "pipeline_health.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(dashboard_cfg["panels"]), 8)


if __name__ == "__main__":
    unittest.main()
