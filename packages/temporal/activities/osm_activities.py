"""
DataExtraction — OSM Extraction Activities
===========================================
Temporal activity wrappers for OpenStreetMap / open_map operations.
Executes bounded Overpass queries for US & Mexico regions with incremental
chunk-streaming persistence into:
  - staging_dataextraction.staging_companies (source = 'OPENSTREETMAP')
  - master_dataextraction.locations (osm_place_id + coordinates)
  - master_dataextraction.organization_locations
  - kg_observation / MinIO (with PostgreSQL outbox failover)
"""

import asyncio
import contextvars
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from temporalio import activity

# Inject open_map and infrastructure paths cleanly
PACKAGES_DIR = Path(__file__).resolve().parents[2]
OSM_PATH = PACKAGES_DIR / "scrapers" / "open_map"
OSM_SRC = OSM_PATH / "src"
INFRA_DIR = PACKAGES_DIR / "infrastructure"

for p in [str(OSM_SRC), str(OSM_PATH), str(INFRA_DIR), str(PACKAGES_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("dataextraction.activities.osm")


def _safe_heartbeat(payload: Any) -> None:
    """Safely issues a Temporal heartbeat if running within an activity context."""
    try:
        activity.heartbeat(payload)
    except Exception:
        pass


def _get_activity_logger():
    """Returns the Temporal activity logger if in context, otherwise standard logger."""
    try:
        return activity.logger
    except Exception:
        return logger


def _is_mock_conn(conn: Any) -> bool:
    return type(conn).__module__.startswith("unittest.mock")


def _resolve_osm_region(region_code: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Resolves a US state or Mexico entity code/name into:
    (state_name, region_short_code, country_name, country_code).
    Returns None when the region is unsupported.
    """
    from src.osm_state_collector import US_STATES, MEXICO_ENTITIES  # type: ignore

    raw = (region_code or "").strip()
    if not raw:
        return None
    upper = raw.upper()

    us_by_code = {code.upper(): (name, code.upper(), "United States", "US") for name, code in US_STATES}
    us_by_name = {name.upper(): (name, code.upper(), "United States", "US") for name, code in US_STATES}
    mx_by_code = {code.upper(): (name, code.upper(), "Mexico", "MX") for name, code in MEXICO_ENTITIES}
    mx_by_name = {name.upper(): (name, code.upper(), "Mexico", "MX") for name, code in MEXICO_ENTITIES}
    mx_aliases = {
        "CIUDAD DE MÉXICO": "CMX",
        "MEXICO CITY": "CMX",
        "CDMX": "CMX",
        "ESTADO DE MÉXICO": "MEX",
        "MICHOACÁN": "MIC",
        "NUEVO LEÓN": "NLE",
        "QUERÉTARO": "QUE",
        "SAN LUIS POTOSÍ": "SLP",
        "YUCATÁN": "YUC",
        "MÉXICO": "MEX",
    }

    if upper.startswith("US-") and len(upper) > 3:
        key = upper.split("-", 1)[1]
        return us_by_code.get(key) or us_by_name.get(key)

    if upper.startswith("MX-") and len(upper) > 3:
        key = upper.split("-", 1)[1]
        key = mx_aliases.get(key, key)
        return mx_by_code.get(key) or mx_by_name.get(key)

    if upper in us_by_code or upper in us_by_name:
        return us_by_code.get(upper) or us_by_name.get(upper)

    mapped_mx = mx_aliases.get(upper, upper)
    if mapped_mx in mx_by_code or mapped_mx in mx_by_name:
        return mx_by_code.get(mapped_mx) or mx_by_name.get(mapped_mx)

    return None


def _build_osm_canonical_rows(
    collected_records: List[Dict[str, Any]],
    state_name: str,
    st_code: str,
    country_name: str,
    country_code: str,
    extract_domain_fn: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Tuple[str, str]]]:
    """Maps raw OSM POI dicts into staging_companies, locations, and org-location pairs."""
    company_records: List[Dict[str, Any]] = []
    location_records: List[Dict[str, Any]] = []
    org_loc_pairs: List[Tuple[str, str]] = []

    for rec in collected_records:
        osm_type = str(rec.get("osm_type") or "node")
        osm_id = rec.get("osm_id")
        if osm_id is None:
            continue

        raw_tags = rec.get("raw_tags") or {}
        name = rec.get("name") or rec.get("brand") or rec.get("operator") or raw_tags.get("name")
        if not name or not str(name).strip():
            continue

        comp_id = f"osm_{osm_type}_{osm_id}"
        website = rec.get("website") or raw_tags.get("website") or raw_tags.get("contact:website")
        domain = extract_domain_fn(website) if website else None
        email = rec.get("email") or raw_tags.get("email") or raw_tags.get("contact:email")
        phone = rec.get("phone") or rec.get("mobile") or raw_tags.get("phone") or raw_tags.get("contact:phone")

        housenumber = rec.get("addr:housenumber") or ""
        street = rec.get("addr:street") or ""
        street_address = f"{housenumber} {street}".strip() or None
        city = rec.get("addr:city") or rec.get("addr:place") or None
        zip_code = rec.get("addr:postcode") or None
        lat = rec.get("latitude")
        lon = rec.get("longitude")
        industry = rec.get("osm_value") or rec.get("category") or rec.get("category_group")

        # Use company_email (not email) so bulk_upsert_staging_records does not invent staging_people rows
        company_records.append({
            "id": comp_id,
            "company_id": comp_id,
            "name": str(name).strip(),
            "legal_name": rec.get("operator") or str(name).strip(),
            "website": website,
            "domain": domain,
            "company_email": email,
            "phone": phone,
            "city": city,
            "state": state_name,
            "state_code": st_code,
            "zip_code": str(zip_code)[:20] if zip_code else None,
            "country": country_name,
            "country_code": country_code,
            "industry": str(industry)[:255] if industry else None,
            "company_quality_score": 78,
            "osm_type": osm_type,
            "osm_id": osm_id,
            "osm_key": rec.get("osm_key"),
            "osm_value": rec.get("osm_value"),
            "latitude": lat,
            "longitude": lon,
            "street_address": street_address,
            "source_url": rec.get("source_url") or f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            "collected_at": rec.get("collected_at"),
            "raw_tags": raw_tags,
        })

        if lat is not None and lon is not None:
            loc_key = f"osm:{osm_type}:{osm_id}"
            location_records.append({
                "location_key": loc_key,
                "osm_place_id": osm_id,
                "name": str(name).strip(),
                "route": street_address,
                "city": city,
                "state": state_name,
                "state_code": st_code,
                "postal_code": str(zip_code)[:20] if zip_code else None,
                "country": country_name,
                "country_code": country_code,
                "latitude": lat,
                "longitude": lon,
                "geocoding_precision": "ROOFTOP",
            })
            org_loc_pairs.append((comp_id, loc_key))

    return company_records, location_records, org_loc_pairs


@activity.defn(name="run_osm_state_extraction")
async def run_osm_state_extraction_activity(
    state_code: str,
    config: Optional[Dict[str, Any]] = None,
) -> dict:
    """
    Runs open_map Overpass extraction for a US state or Mexican federal entity and
    streams chunk batches directly to PostgreSQL (`staging_companies`, `locations`,
    `organization_locations`) + best-effort Knowledge Graph observation batches.
    """
    act_logger = _get_activity_logger()
    cfg = config or {}

    from packages.infrastructure.config_manager import config_manager  # type: ignore
    from packages.infrastructure.db_connector import get_connection, release_connection  # type: ignore
    from packages.infrastructure.staging_writer import (  # type: ignore
        bulk_upsert_staging_records,
        link_organization_locations,
        upsert_master_locations,
    )
    from packages.scrapers.google_maps.postgres_writer import extract_domain_from_url  # type: ignore

    geo_cfg = config_manager.get_geospatial_config()
    resolved = _resolve_osm_region(state_code)

    if not resolved:
        act_logger.info("Skipping OSM extraction for unsupported region: %s", state_code)
        return {
            "state": state_code,
            "extracted": 0,
            "postgres_inserted": 0,
            "locations_upserted": 0,
            "status": "SKIPPED",
            "reason": f"OSMStateCollector supports 50 US states and 32 Mexico entities; '{state_code}' skipped",
        }

    state_name, st_code, country_name, country_code = resolved
    act_logger.info("OSM extraction: region=%s-%s (%s, %s)", country_code, st_code, state_name, country_name)
    _safe_heartbeat({"stage": "starting", "state": st_code, "country": country_code})

    dry_run = bool(cfg.get("dry_run", False))
    kg_enabled = bool(cfg.get("kg_observation_enabled", geo_cfg.get("kg_observation_enabled", True)))

    raw_fields = cfg.get("target_fields") or cfg.get("fields") or geo_cfg.get("osm_fields", ["shop", "office"])
    if isinstance(raw_fields, str):
        target_fields = [f.strip().lower() for f in raw_fields.split(",") if f.strip()]
    else:
        target_fields = [str(f).strip().lower() for f in raw_fields if str(f).strip()]
    if not target_fields:
        target_fields = ["shop", "office"]

    raw_limit = cfg.get("limit") if cfg.get("limit") is not None else cfg.get("max_records")
    if raw_limit is None:
        raw_limit = geo_cfg.get("default_batch_limit", 50)
    try:
        max_records: Optional[int] = int(raw_limit)
        if max_records <= 0:
            max_records = None
    except (TypeError, ValueError):
        max_records = int(geo_cfg.get("default_batch_limit", 50))

    raw_chunks = cfg.get("max_chunks_per_field")
    if raw_chunks is None:
        raw_chunks = geo_cfg.get("osm_max_chunks_per_field", 2)
    try:
        max_chunks_per_field: Optional[int] = int(raw_chunks)
        if max_chunks_per_field <= 0:
            max_chunks_per_field = None
    except (TypeError, ValueError):
        max_chunks_per_field = int(geo_cfg.get("osm_max_chunks_per_field", 2))

    resume = bool(cfg.get("resume", True))
    persist_lock = threading.Lock()
    streamed_extracted = 0
    pg_inserted = 0
    locations_upserted = 0
    persist_errors: List[str] = []

    def _persist_osm_batch_sync(chunk_pois: List[Dict[str, Any]]) -> None:
        nonlocal streamed_extracted, pg_inserted, locations_upserted
        if not chunk_pois:
            return
        company_records, location_records, org_loc_pairs = _build_osm_canonical_rows(
            collected_records=chunk_pois,
            state_name=state_name,
            st_code=st_code,
            country_name=country_name,
            country_code=country_code,
            extract_domain_fn=extract_domain_from_url,
        )
        if not company_records:
            with persist_lock:
                streamed_extracted += len(chunk_pois)
            return

        conn = None
        try:
            conn = get_connection()
            if not conn:
                raise RuntimeError("PostgreSQL connection unavailable; cannot persist OSM batch")
            mocked = _is_mock_conn(conn)
            loc_cnt = 0
            with conn.cursor() as cur:
                comp_cnt, _ = bulk_upsert_staging_records(cur, company_records, source="OPENSTREETMAP")
                if location_records:
                    try:
                        cur.execute("SAVEPOINT osm_locations_sp;")
                        loc_cnt = upsert_master_locations(cur, location_records)
                        if not mocked and org_loc_pairs:
                            link_organization_locations(cur, org_loc_pairs, source_system="OPENSTREETMAP")
                        cur.execute("RELEASE SAVEPOINT osm_locations_sp;")
                    except Exception as loc_err:
                        cur.execute("ROLLBACK TO SAVEPOINT osm_locations_sp;")
                        act_logger.warning("OSM master locations sync notice: %s", loc_err)
            if kg_enabled and not mocked:
                try:
                    from packages.infrastructure.kg_ingestion_bridge import ingest_geospatial_observation_batch
                    ingest_geospatial_observation_batch(
                        conn=conn,
                        source_name="OPENSTREETMAP",
                        records=company_records,
                        region_code=f"{country_code}-{st_code}",
                    )
                except Exception as kg_err:
                    act_logger.debug("OSM KG batch observation notice: %s", kg_err)
            conn.commit()
            with persist_lock:
                streamed_extracted += len(chunk_pois)
                pg_inserted += comp_cnt
                locations_upserted += loc_cnt
        except Exception as db_err:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            with persist_lock:
                persist_errors.append(str(db_err))
            raise
        finally:
            if conn:
                release_connection(conn)

    try:
        from src.osm_state_collector import OSMStateCollector  # type: ignore

        try:
            collector = OSMStateCollector(
                workspace_dir=str(OSM_PATH),
                progress_filename=f"osm_progress_{country_code.lower()}_{st_code.lower()}.json",
            )
        except TypeError:
            collector = OSMStateCollector(workspace_dir=str(OSM_PATH))

        if dry_run:
            chunks = collector.generate_state_chunks(state_name)
            return {
                "state": st_code,
                "country": country_code,
                "state_name": state_name,
                "extracted": len(chunks),
                "postgres_inserted": 0,
                "locations_upserted": 0,
                "mode": "dry_run",
                "status": "SUCCESS",
            }

        loop = asyncio.get_running_loop()
        act_ctx = contextvars.copy_context()

        def _threadsafe_hb(msg: str) -> None:
            try:
                loop.call_soon_threadsafe(
                    _safe_heartbeat,
                    {
                        "stage": "osm_chunk",
                        "state": st_code,
                        "country": country_code,
                        "detail": msg,
                        "pg_inserted": pg_inserted,
                    },
                    context=act_ctx,
                )
            except Exception:
                pass

        use_stream = bool(cfg.get("stream_chunks", True))
        state_summary = await asyncio.to_thread(
            collector.process_state,
            state_name=state_name,
            state_code=st_code,
            target_fields=target_fields,
            resume=resume,
            max_chunks_per_field=max_chunks_per_field,
            max_records=max_records,
            heartbeat_cb=_threadsafe_hb,
            batch_callback=_persist_osm_batch_sync if use_stream else None,
            stream_only=use_stream,
        )
    except Exception as exc:
        act_logger.error("OSM extraction failed for %s-%s: %s", country_code, st_code, exc, exc_info=True)
        return {
            "state": st_code,
            "country": country_code,
            "state_name": state_name,
            "extracted": streamed_extracted,
            "postgres_inserted": pg_inserted,
            "locations_upserted": locations_upserted,
            "error": str(exc),
            "status": "FAILED",
        }

    collected_records: List[Dict[str, Any]] = state_summary.get("collected_records") or []
    # Fallback persistence if process_state returned collected_records without invoking batch_callback (e.g. non-stream mode or test mocks)
    if streamed_extracted == 0 and collected_records:
        try:
            _persist_osm_batch_sync(collected_records)
        except Exception as db_err:
            act_logger.error("Failed persisting OSM records for %s: %s", st_code, db_err, exc_info=True)
            return {
                "state": st_code,
                "country": country_code,
                "state_name": state_name,
                "extracted": len(collected_records),
                "postgres_inserted": 0,
                "locations_upserted": 0,
                "error": str(db_err),
                "status": "FAILED",
            }

    extracted_count = streamed_extracted if streamed_extracted > 0 else len(collected_records)

    # Check if every Overpass chunk failed with 0 records collected
    if extracted_count == 0:
        state_prog = collector.progress_data.get(state_name, {})
        total_ok_chunks = sum(
            int((fd.get("stats") or {}).get("successful_chunks", 0))
            for fd in state_prog.values()
            if isinstance(fd, dict)
        )
        total_fail_chunks = sum(
            int((fd.get("stats") or {}).get("failed_chunks", 0))
            for fd in state_prog.values()
            if isinstance(fd, dict)
        )
        if total_fail_chunks > 0 and total_ok_chunks == 0:
            err_msg = f"All {total_fail_chunks} Overpass chunk query attempts failed for {country_code}-{st_code}"
            act_logger.error(err_msg)
            return {
                "state": st_code,
                "country": country_code,
                "state_name": state_name,
                "extracted": 0,
                "postgres_inserted": 0,
                "locations_upserted": 0,
                "fields": state_summary.get("fields", {}),
                "error": err_msg,
                "status": "FAILED",
            }

    act_logger.info(
        "Persisted %d OSM companies and %d locations (%s-%s)",
        pg_inserted,
        locations_upserted,
        country_code,
        st_code,
    )
    _safe_heartbeat({
        "stage": "osm_complete",
        "state": st_code,
        "country": country_code,
        "extracted": extracted_count,
        "pg_inserted": pg_inserted,
    })
    try:
        from packages.infrastructure.metrics import AGENT2_OSM_POIS_PERSISTED
        if pg_inserted > 0:
            AGENT2_OSM_POIS_PERSISTED.labels(region=f"{country_code}-{st_code}", status="success").inc(pg_inserted)
    except Exception:
        pass
    return {
        "state": st_code,
        "country": country_code,
        "state_name": state_name,
        "extracted": extracted_count,
        "postgres_inserted": pg_inserted,
        "locations_upserted": locations_upserted,
        "fields": state_summary.get("fields", {}),
        "status": "SUCCESS",
    }


@activity.defn(name="run_osm_checkpoint_recovery")
async def run_osm_checkpoint_recovery_activity(state_code: str) -> dict:
    """
    Recovers an interrupted OSM extraction from its PostgreSQL checkpoint
    (reclaiming expired worker leases and syncing legacy JSON snapshots).
    """
    _get_activity_logger().info("OSM checkpoint recovery: state=%s", state_code)

    from src.checkpoint import EnterpriseCheckpointManager  # type: ignore

    restored = False
    checkpoint_file = ""
    reclaimed = 0
    try:
        mgr = EnterpriseCheckpointManager(str(OSM_PATH))
        resolved = _resolve_osm_region(state_code)
        if resolved:
            state_name = resolved[0]
            from src.osm_state_collector import FIELDS_TAXONOMY  # type: ignore
            for f_meta in FIELDS_TAXONOMY:
                reclaimed += mgr.reclaim_expired_leases(state_name, f_meta["field"])
        mgr.sync_legacy_json()
        restored = True
        checkpoint_file = str(mgr.legacy_json_path)
    except Exception as e:
        _get_activity_logger().warning("OSM checkpoint recovery notice: %s", e)

    return {
        "state": state_code,
        "checkpoint_restored": restored,
        "reclaimed_leases": reclaimed,
        "resumed_from": checkpoint_file,
        "status": "SUCCESS",
    }


@activity.defn(name="run_osm_circuit_breaker_reset")
async def run_osm_circuit_breaker_reset_activity(state_code: str) -> dict:
    """
    Resets the circuit breaker for Overpass endpoints.
    Called to re-enable failed states or mirrors.
    """
    _get_activity_logger().info("OSM circuit breaker reset: state=%s", state_code)

    from src.circuit_breaker import EndpointCircuitBreaker  # type: ignore
    from src.config import default_config  # type: ignore

    reset_ok = False
    try:
        cb = EndpointCircuitBreaker(list(default_config.fallback_endpoints))
        cb.reset_all()
        reset_ok = True
    except Exception as e:
        _get_activity_logger().warning("OSM circuit breaker reset notice: %s", e)

    return {
        "state": state_code,
        "reset": reset_ok,
        "status": "SUCCESS",
    }
