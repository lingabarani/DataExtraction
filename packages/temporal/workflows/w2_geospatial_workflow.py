"""
DataExtraction — Agent 2: Geospatial & Domain Discovery Workflow
================================================================
Queue: geospatial-domain-queue
Worker: packages.temporal.workers.worker_geospatial

Orchestrates multi-channel spatial & domain discovery:
- Google Maps quadrant collection & PostgreSQL staging/locations persistence
- OpenStreetMap Overpass state extraction & PostgreSQL persistence
- Website reachability / SSL verification (with SSRF safety)
- Corporate website contact & executive leadership crawl
- Geographic standardization & coordinate/postal validation
- Best-effort Knowledge Graph observation telemetry
- Signals: pause, resume, cancel_region
- Queries: get_status
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.gmaps_activities import (
        run_gmaps_collection_activity,
        run_gmaps_website_verification_activity,
        run_gmaps_website_crawl_activity,
    )
    from packages.temporal.activities.osm_activities import (
        run_osm_state_extraction_activity,
    )
    from packages.temporal.activities.pipeline_activities import (
        validate_geo_activity,
    )
    from packages.temporal.activities.storage_activities import (
        ingest_kg_observation_activity,
    )
    from packages.temporal.config import QUEUE_GEOSPATIAL, GEOSPATIAL_RETRY_POLICY

TASK_QUEUE = QUEUE_GEOSPATIAL

SUPPORTED_GEOSPATIAL_SOURCES: Sequence[str] = ("google_maps", "openstreetmap")

GEOSPATIAL_SOURCE_ALIASES: Dict[str, str] = {
    "google_maps": "google_maps",
    "gmaps": "google_maps",
    "google_places": "google_maps",
    "maps": "google_maps",
    "openstreetmap": "openstreetmap",
    "osm": "openstreetmap",
    "overpass": "openstreetmap",
}

GEOSPATIAL_GROUP_ALIASES = {"geospatial", "geospatial_sources", "spatial", "both", "all"}


def resolve_geospatial_sources(
    raw_sources: Any,
    all_supported: Sequence[str] = SUPPORTED_GEOSPATIAL_SOURCES,
    configured_defaults: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Resolves UI/API source selections or aliases into canonical Agent 2 channels.
    Ignores unrelated sources (e.g. 'sec_edgar', 'registry_sources').
    When raw_sources is None, uses configured_defaults or all_supported.
    When an explicit list excluding any geospatial source is given, returns [].
    """
    defaults = [s for s in (configured_defaults or all_supported) if s in all_supported]
    if not defaults:
        defaults = list(all_supported)

    if raw_sources is None:
        return list(defaults)

    if isinstance(raw_sources, dict):
        selected = [k for k, v in raw_sources.items() if v]
    elif isinstance(raw_sources, str):
        selected = [s.strip() for s in raw_sources.split(",") if s.strip()]
    elif isinstance(raw_sources, (list, tuple, set)):
        selected = [str(s).strip() for s in raw_sources if str(s).strip()]
    else:
        return list(defaults)

    resolved: List[str] = []
    seen = set()
    for item in selected:
        key = item.lower().replace("-", "_").replace(" ", "_")
        if key in GEOSPATIAL_GROUP_ALIASES:
            for src in defaults:
                if src not in seen:
                    seen.add(src)
                    resolved.append(src)
            continue
        mapped = GEOSPATIAL_SOURCE_ALIASES.get(key)
        if mapped and mapped in all_supported and mapped not in seen:
            seen.add(mapped)
            resolved.append(mapped)

    return resolved


def _resolve_regions_and_states(
    config: Dict[str, Any],
    geo_defaults: Dict[str, Any],
    cancelled_regions: set[str],
) -> tuple[List[str], List[str]]:
    """
    Derives active GMaps regions and OSM two-letter US states from workflow config,
    countries selection, and centralized geospatial_defaults.
    Preserves explicit config['regions'] / config['states'] when supplied.
    """
    us_defaults = list(geo_defaults.get("us_regions") or ["US-CA", "US-TX", "US-NY"])
    mx_defaults = list(geo_defaults.get("mx_regions") or ["MX-CMX", "MX-JAL", "MX-NLE"])

    if "regions" in config and config["regions"] is not None:
        raw_regions = list(config["regions"])
    else:
        raw_countries = config.get("countries") or geo_defaults.get("default_countries") or ["US"]
        raw_regions = []
        for c in raw_countries:
            cu = str(c).strip().upper()
            if cu in ("US", "USA", "UNITED STATES", "GLOBAL"):
                for r in us_defaults:
                    if r not in raw_regions:
                        raw_regions.append(r)
            if cu in ("MX", "MEXICO", "GLOBAL"):
                for r in mx_defaults:
                    if r not in raw_regions:
                        raw_regions.append(r)
        if not raw_regions:
            raw_regions = list(us_defaults)

    active_regions = [r for r in raw_regions if str(r).upper() not in cancelled_regions]

    if "states" in config and config["states"] is not None:
        raw_states = list(config["states"])
    else:
        raw_states = []
        for r in active_regions:
            ru = str(r).strip().upper()
            if ru.startswith("US-") and len(ru) > 3:
                st = ru.split("-", 1)[1]
                if st not in raw_states:
                    raw_states.append(st)

    active_states = [
        s for s in raw_states
        if str(s).upper() not in cancelled_regions and f"US-{str(s).upper()}" not in cancelled_regions
    ]
    return active_regions, active_states


def resolve_osm_regions(
    config: Dict[str, Any],
    geo_defaults: Dict[str, Any],
    cancelled_regions: set[str],
    active_regions: Optional[List[str]] = None,
) -> List[str]:
    """
    Resolves OSM target regions covering BOTH US states (two-letter codes)
    and Mexican federal entities (MX-XXX ISO codes).
    Honors explicit config['states'] or config['osm_regions'] when supplied.
    """
    _, us_states = _resolve_regions_and_states(config, geo_defaults, cancelled_regions)
    osm_targets: List[str] = list(us_states)

    if config.get("osm_regions") is not None:
        raw_osm = list(config["osm_regions"])
        return [
            str(r).strip() for r in raw_osm
            if str(r).strip() and str(r).strip().upper() not in cancelled_regions
        ]

    # Add Mexico entities from explicit regions or countries=['MX', 'GLOBAL']
    region_pool = active_regions if active_regions is not None else _resolve_regions_and_states(config, geo_defaults, cancelled_regions)[0]
    for r in region_pool:
        ru = str(r).strip().upper()
        if ru.startswith("MX-") and ru not in cancelled_regions and ru not in osm_targets:
            osm_targets.append(ru)

    return osm_targets


@workflow.defn(name="Agent2GeospatialWorkflow")
class Agent2GeospatialWorkflow:
    """
    Agent 2 Workflow: Geospatial & Domain Discovery.
    Orchestrates physical storefront collection, domain verification, website crawling,
    coordinate/postal validation, and optional KG observation telemetry.
    """

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._paused: bool = False
        self._cancelled_regions: set[str] = set()
        self._results: Dict[str, Any] = {}

    @staticmethod
    def _safe_now() -> datetime:
        try:
            return workflow.now()
        except Exception:
            return datetime.now(timezone.utc)

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 2] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 2] Resume signal received")
        self._paused = False

    @workflow.signal
    def cancel_region(self, region: str) -> None:
        workflow.logger.warning("[Agent 2] Cancel region signal received: %s", region)
        self._cancelled_regions.add(region.upper())

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 2 - Geospatial & Domain Discovery",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "paused": self._paused,
            "cancelled_regions": list(self._cancelled_regions),
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        started_at = self._safe_now()
        self._status = "RUNNING"
        wf_id = workflow.info().workflow_id
        workflow.logger.info("[Agent 2] Geospatial Discovery started on queue: %s", TASK_QUEUE)

        geo_defaults = config.get("geospatial_defaults") or {}
        configured_sources = geo_defaults.get("enabled_sources")
        active_sources = resolve_geospatial_sources(
            config.get("sources"),
            all_supported=SUPPORTED_GEOSPATIAL_SOURCES,
            configured_defaults=configured_sources,
        )

        active_regions, active_states = _resolve_regions_and_states(
            config, geo_defaults, self._cancelled_regions
        )
        osm_regions = resolve_osm_regions(
            config, geo_defaults, self._cancelled_regions, active_regions=active_regions
        )

        run_gmaps = ("google_maps" in active_sources) and bool(active_regions)
        run_osm = ("openstreetmap" in active_sources) and bool(osm_regions)

        if not run_gmaps and not run_osm:
            self._status = "SKIPPED"
            return {
                "status": "SKIPPED",
                "reason": "No geospatial sources or regions selected",
                "sources": active_sources,
                "regions_processed": 0,
                "states_processed": 0,
                "spatial_standardized": 0,
                "postgres_inserted": 0,
                "osm_extracted": 0,
                "websites_verified": 0,
                "contacts_found": 0,
                "geo_validated": 0,
                "duration_seconds": 0.0,
                "results": {},
            }

        # Derive per-task limit from data_count & central defaults
        default_limit = int(geo_defaults.get("default_batch_limit", 50) or 50)
        raw_data_count = config.get("data_count")
        task_slots = (len(active_regions) if run_gmaps else 0) + (len(osm_regions) if run_osm else 0)
        per_task_limit = default_limit
        if raw_data_count is not None:
            try:
                dc_int = int(raw_data_count)
                if dc_int > 0 and task_slots > 0:
                    per_task_limit = max(1, min(default_limit, (dc_int + task_slots - 1) // task_slots))
            except (TypeError, ValueError):
                pass

        tile_config = dict(config.get("tile_config") or {})
        tile_config.setdefault("limit", per_task_limit)
        if config.get("dry_run") is not None:
            tile_config.setdefault("dry_run", bool(config["dry_run"]))

        osm_config = dict(config.get("osm_config") or {})
        osm_config.setdefault("limit", per_task_limit)
        if "target_fields" not in osm_config and "fields" not in osm_config and geo_defaults.get("osm_fields"):
            osm_config["target_fields"] = geo_defaults["osm_fields"]
        if "max_chunks_per_field" not in osm_config and geo_defaults.get("osm_max_chunks_per_field"):
            osm_config["max_chunks_per_field"] = geo_defaults["osm_max_chunks_per_field"]
        if config.get("dry_run") is not None:
            osm_config.setdefault("dry_run", bool(config["dry_run"]))

        raw_categories = config.get("categories") or geo_defaults.get("gmaps_categories")
        if raw_categories and isinstance(raw_categories, (list, tuple)) and len(raw_categories) > 1:
            gmaps_categories = [str(c).strip() for c in raw_categories if str(c).strip()]
        else:
            gmaps_categories = [str(config.get("category") or geo_defaults.get("gmaps_category") or "commercial")]

        await workflow.wait_condition(lambda: not self._paused)

        # ── Step 1: Parallel Collection (GMaps + OSM) ─────────────────────────
        gmaps_tasks = []
        gmaps_regions_dispatched = active_regions if run_gmaps else []
        for reg in gmaps_regions_dispatched:
            for category in gmaps_categories:
                gmaps_tasks.append(
                    workflow.execute_activity(
                        run_gmaps_collection_activity,
                        args=[reg, category, tile_config],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(hours=2),
                        heartbeat_timeout=timedelta(minutes=5),
                        retry_policy=GEOSPATIAL_RETRY_POLICY,
                    )
                )

        osm_tasks = []
        osm_states_dispatched = osm_regions if run_osm else []
        for st in osm_states_dispatched:
            osm_tasks.append(
                workflow.execute_activity(
                    run_osm_state_extraction_activity,
                    args=[st, osm_config],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=GEOSPATIAL_RETRY_POLICY,
                )
            )

        workflow.logger.info(
            "[Agent 2] Executing GMaps (%d regions) & OSM (%d states) in parallel",
            len(gmaps_regions_dispatched),
            len(osm_states_dispatched),
        )

        all_results = await asyncio.gather(*gmaps_tasks, *osm_tasks, return_exceptions=True)
        gmaps_out = all_results[: len(gmaps_tasks)]
        osm_out = all_results[len(gmaps_tasks) :]

        self._results["gmaps"] = [
            r if not isinstance(r, Exception) else {"status": "FAILED", "error": str(r)}
            for r in gmaps_out
        ]
        self._results["osm"] = [
            r if not isinstance(r, Exception) else {"status": "FAILED", "error": str(r)}
            for r in osm_out
        ]

        # ── Step 2: Domain Verification & Website Contact Crawl ───────────────
        await workflow.wait_condition(lambda: not self._paused)
        if not config.get("skip_website_enrichment", False):
            verify_limit = int(
                config.get("website_verification_limit")
                or geo_defaults.get("website_verification_limit", 50)
            )
            if raw_data_count is not None:
                try:
                    verify_limit = max(1, min(verify_limit, int(raw_data_count)))
                except (TypeError, ValueError):
                    pass

            try:
                ver_res = await workflow.execute_activity(
                    run_gmaps_website_verification_activity,
                    args=[wf_id, verify_limit],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=GEOSPATIAL_RETRY_POLICY,
                )
                self._results["website_verification"] = ver_res
            except Exception as exc:
                self._results["website_verification"] = {"status": "FAILED", "error": str(exc)}

            crawl_limit = int(
                config.get("website_crawl_limit")
                or geo_defaults.get("website_crawl_limit", 25)
            )
            if raw_data_count is not None:
                try:
                    crawl_limit = max(1, min(crawl_limit, int(raw_data_count)))
                except (TypeError, ValueError):
                    pass

            try:
                crawl_res = await workflow.execute_activity(
                    run_gmaps_website_crawl_activity,
                    args=[wf_id, crawl_limit],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=timedelta(minutes=5),
                    retry_policy=GEOSPATIAL_RETRY_POLICY,
                )
                self._results["website_crawl"] = crawl_res
            except Exception as exc:
                self._results["website_crawl"] = {"status": "FAILED", "error": str(exc)}

        # ── Step 3: Geographic Standardization & Validation ───────────────────
        await workflow.wait_condition(lambda: not self._paused)
        geo_validation_table = config.get("target_table", "staging_dataextraction.staging_companies")
        geo_batch_limit = int(
            config.get("geo_batch_limit")
            or geo_defaults.get("geo_validation_limit", 10000)
        )
        try:
            geo_res = await workflow.execute_activity(
                validate_geo_activity,
                args=[geo_validation_table, geo_batch_limit, ["GOOGLE_MAPS", "OPENSTREETMAP"]],
                task_queue=TASK_QUEUE,
                start_to_close_timeout=timedelta(hours=1),
                retry_policy=GEOSPATIAL_RETRY_POLICY,
            )
            if isinstance(geo_res, dict) and str(geo_res.get("status", "")).upper() == "FAILED":
                self._results["geo_validation"] = geo_res
            else:
                self._results["geo_validation"] = {"status": "SUCCESS", **(geo_res if isinstance(geo_res, dict) else {})}
        except Exception as exc:
            self._results["geo_validation"] = {"status": "FAILED", "error": str(exc)}

        # ── Compute Telemetry Metrics ─────────────────────────────────────────
        gmaps_inserted = sum(
            int(r.get("postgres_inserted", 0) or 0)
            for r in self._results["gmaps"]
            if isinstance(r, dict)
        )
        osm_extracted = sum(
            int(r.get("extracted", 0) or 0)
            for r in self._results["osm"]
            if isinstance(r, dict)
        )
        osm_inserted = sum(
            int(r.get("postgres_inserted", 0) or 0)
            for r in self._results["osm"]
            if isinstance(r, dict)
        )
        locations_upserted = sum(
            int(r.get("locations_upserted", 0) or 0)
            for r in (self._results["gmaps"] + self._results["osm"])
            if isinstance(r, dict)
        )
        total_inserted = gmaps_inserted + osm_inserted
        websites_verified = int((self._results.get("website_verification") or {}).get("verified", 0) or 0)
        contacts_found = int((self._results.get("website_crawl") or {}).get("contacts_found", 0) or 0)
        geo_validated = int((self._results.get("geo_validation") or {}).get("validated", 0) or 0)

        # ── Step 4: Best-Effort KG Observation Recording ──────────────────────
        kg_enabled = bool(geo_defaults.get("kg_observation_enabled", True))
        if kg_enabled and not bool(config.get("dry_run", False)) and total_inserted > 0:
            try:
                kg_res = await workflow.execute_activity(
                    ingest_kg_observation_activity,
                    args=[{
                        "source_name": "GEOSPATIAL_AGENT_2",
                        "source_record_id": wf_id,
                        "entity_id": wf_id,
                        "raw_payload": {
                            "workflow_id": wf_id,
                            "sources": active_sources,
                            "gmaps_inserted": gmaps_inserted,
                            "osm_extracted": osm_extracted,
                            "osm_inserted": osm_inserted,
                            "locations_upserted": locations_upserted,
                            "websites_verified": websites_verified,
                            "contacts_found": contacts_found,
                            "geo_validated": geo_validated,
                        },
                    }],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                self._results["kg_observation"] = {"status": "SUCCESS", **(kg_res if isinstance(kg_res, dict) else {})}
            except Exception as kg_exc:
                workflow.logger.warning("[Agent 2] KG observation skipped/unavailable: %s", kg_exc)
                self._results["kg_observation"] = {"status": "SKIPPED_STORAGE_UNAVAILABLE", "error": str(kg_exc)}

        # ── Honest Final Status ───────────────────────────────────────────────
        collection_results = self._results["gmaps"] + self._results["osm"]
        executed_collection = [
            r for r in collection_results
            if isinstance(r, dict) and str(r.get("status", "")).upper() != "SKIPPED"
        ]
        failed_collection = [
            r for r in executed_collection
            if str(r.get("status", "")).upper() in ("FAILED", "ERROR")
        ]
        geo_failed = str((self._results.get("geo_validation") or {}).get("status", "")).upper() == "FAILED"
        ver_failed = str((self._results.get("website_verification") or {}).get("status", "")).upper() == "FAILED"
        crawl_failed = str((self._results.get("website_crawl") or {}).get("status", "")).upper() == "FAILED"

        if executed_collection and len(failed_collection) == len(executed_collection) and total_inserted == 0:
            self._status = "FAILED"
        elif failed_collection or geo_failed or ver_failed or crawl_failed:
            self._status = "COMPLETED_WITH_ERRORS"
        else:
            self._status = "COMPLETED"

        duration_seconds = round(max((self._safe_now() - started_at).total_seconds(), 0.0), 2)

        return {
            "status": self._status,
            "sources": active_sources,
            "regions_processed": len(gmaps_regions_dispatched),
            "states_processed": len(osm_states_dispatched),
            "gmaps_inserted": gmaps_inserted,
            "osm_extracted": osm_extracted,
            "osm_inserted": osm_inserted,
            "postgres_inserted": total_inserted,
            "locations_upserted": locations_upserted,
            "websites_verified": websites_verified,
            "contacts_found": contacts_found,
            "geo_validated": geo_validated,
            "spatial_standardized": total_inserted,
            "duration_seconds": duration_seconds,
            "results": self._results,
        }
