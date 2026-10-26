import asyncio
import json
import logging
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from .config import ScraperConfig, load_config
from .db import Database
from .http import HttpClient
from .scope import (
    ALLOWED_COUNTRIES,
    get_target_countries,
    get_us_states,
    get_mexico_entities,
    get_regions_for_country,
    get_region,
    validate_target_country,
    RegionInfo,
)
from .models import PlaceStub
from .geo.resolve import resolve_location, get_country_bias
from .geo.boundaries import get_region_bounding_boxes
from .search import build_search_pb, parse_search_rpc_response
from .tiling import recursive_tile_search, generate_region_grid_tiles, GeoTile, sanitize_slug
from .export import export_state_category_data, export_state_complete_package, list_all_state_exports
from .taxonomy import enrich_place_dimensions, load_verticals
from .website.service import WebsiteDiscoveryService
from .website.enrichment_service import WebsiteEnrichmentService
from .storage import RegionalStorageManager

logger = logging.getLogger("gmaps_scraper.orchestrator")

DEFAULT_CATEGORIES = [
    "healthcare",
    "hospitality",
    "food",
    "retail",
    "fitness",
    "beauty",
    "automotive",
    "finance",
    "education",
    "real_estate",
]


class PipelineConfig(BaseModel):
    country: str = "US"  # "US", "MX", or "both"
    regions: Optional[List[str]] = None  # None means all configured regions in selected countries
    categories: List[str] = Field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    collection_limit: int = 50  # Max places per region/category task
    batch_size: int = 50  # Safe batch limit for website discovery and enrichment
    max_crawl_pages: int = 5  # Max pages crawled per website during enrichment
    stages: Dict[str, bool] = Field(
        default_factory=lambda: {
            "collection": True,
            "discovery": True,
            "enrichment": True,
        }
    )
    resume_checkpoint: bool = True
    retry_failed: bool = False
    dry_run: bool = False
    max_retries: int = 2
    tile_max_depth: int = 2
    tile_step_deg: float = 0.5
    tile_overlap_pct: float = 10.0



def sanitize_slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower())
    return s.strip("_") or "all"


class PipelineOrchestrator:
    """
    Dedicated Orchestration Service for State-by-State Business Scraping,
    Website Discovery, and Company Profile Enrichment.
    """

    _instance: Optional["PipelineOrchestrator"] = None

    def __init__(self, db: Database, config: Optional[ScraperConfig] = None):
        self.db = db
        self.config = config or load_config()
        self._lock = asyncio.Lock()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused by default
        self._cancel_requested = False
        self._is_running = False
        self._active_run_id: Optional[str] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._subscribers: List[asyncio.Queue] = []
        self._current_run_data: Dict[str, Any] = {}
        self._recent_errors: List[Dict[str, Any]] = []

    @classmethod
    def get_instance(cls, db: Database, config: Optional[ScraperConfig] = None) -> "PipelineOrchestrator":
        if cls._instance is None or cls._instance.db.db_path != db.db_path:
            cls._instance = cls(db, config)
        return cls._instance

    # -------------------------------------------------------------------------
    # Subscription & Event Broadcasting
    # -------------------------------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def emit_event(self, event_type: str, data: Dict[str, Any]):
        message = {"event": event_type, "data": data, "timestamp": datetime.now().isoformat()}
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass

    # -------------------------------------------------------------------------
    # Plan Generation & Scope Resolution
    # -------------------------------------------------------------------------

    def resolve_ordered_scope(
        self,
        country: str,
        regions: Optional[List[str]] = None
    ) -> List[Tuple[str, RegionInfo]]:
        """
        Returns a deterministic, ordered list of (country_code, RegionInfo).
        - USA: 50 states strictly sorted by 2-letter state code.
        - Mexico: 32 federal entities strictly sorted by entity code.
        - If 'both': USA followed deterministically by Mexico.
        - If a region subset is given, respects that exact deterministic ordering.
        """
        c_upper = country.strip().upper()
        countries_to_process: List[str] = []
        if c_upper in ("BOTH", "ALL"):
            countries_to_process = ["US", "MX"]
        else:
            countries_to_process = [validate_target_country(c_upper)]

        selected_regions_filter = {r.strip().upper() for r in (regions or []) if r.strip()}

        ordered_list: List[Tuple[str, RegionInfo]] = []
        for c in countries_to_process:
            c_regions = get_regions_for_country(c)
            # Deterministic sorting by region code
            for code in sorted(c_regions.keys()):
                if not selected_regions_filter or code in selected_regions_filter:
                    ordered_list.append((c, c_regions[code]))

        return ordered_list

    def preview_plan(self, config: PipelineConfig) -> Dict[str, Any]:
        """
        Generates the complete deterministic execution plan without running it.
        Includes ordered tasks for Stage 1, regions for Stage 2 & 3,
        and current task statuses from SQLite.
        """
        scope_pairs = self.resolve_ordered_scope(config.country, config.regions)
        clean_categories = [c.strip() for c in config.categories if c.strip()]
        if not clean_categories:
            clean_categories = list(DEFAULT_CATEGORIES)

        stage1_tasks: List[Dict[str, Any]] = []
        existing_tasks_map: Dict[str, Dict[str, Any]] = {}

        # Fetch existing tasks from DB to show current status in plan preview
        with self.db.get_connection() as conn:
            rows = conn.execute("SELECT * FROM collection_tasks").fetchall()
            for r in rows:
                existing_tasks_map[r["task_id"]] = dict(r)

        for country_code, reg in scope_pairs:
            for cat in clean_categories:
                slug = sanitize_slug(cat)
                task_id = f"col_{country_code.lower()}_{reg.code.lower()}_{slug}"
                existing = existing_tasks_map.get(task_id)
                status = existing["status"] if existing else "pending"
                attempts = existing["attempt_count"] if existing else 0
                last_error = existing.get("last_error") if existing else None
                rec_collected = existing.get("records_collected", 0) if existing else 0

                stage1_tasks.append({
                    "task_id": task_id,
                    "country_code": country_code,
                    "region_code": reg.code,
                    "region_name": reg.name,
                    "category": cat,
                    "status": status,
                    "attempt_count": attempts,
                    "last_error": last_error,
                    "records_collected": rec_collected,
                })

        stage2_regions: List[Dict[str, Any]] = []
        stage3_regions: List[Dict[str, Any]] = []

        for country_code, reg in scope_pairs:
            item = {
                "country_code": country_code,
                "region_code": reg.code,
                "region_name": reg.name,
            }
            if config.stages.get("discovery", True):
                stage2_regions.append(item)
            if config.stages.get("enrichment", True):
                stage3_regions.append(item)

        total_stage1 = len(stage1_tasks) if config.stages.get("collection", True) else 0
        completed_stage1 = sum(1 for t in stage1_tasks if t["status"] == "completed") if config.stages.get("collection", True) else 0
        failed_stage1 = sum(1 for t in stage1_tasks if t["status"] == "failed") if config.stages.get("collection", True) else 0

        return {
            "config": config.model_dump(),
            "scope_summary": {
                "countries": sorted(list({p[0] for p in scope_pairs})),
                "regions_count": len(scope_pairs),
                "categories_count": len(clean_categories),
            },
            "enabled_stages": {
                "collection": config.stages.get("collection", True),
                "discovery": config.stages.get("discovery", True),
                "enrichment": config.stages.get("enrichment", True),
            },
            "counts": {
                "total_stage1_tasks": total_stage1,
                "completed_stage1_tasks": completed_stage1,
                "failed_stage1_tasks": failed_stage1,
                "stage2_regions_count": len(stage2_regions),
                "stage3_regions_count": len(stage3_regions),
            },
            "stage_1_tasks": stage1_tasks,
            "stage_2_regions": stage2_regions,
            "stage_3_regions": stage3_regions,
        }

    # -------------------------------------------------------------------------
    # Execution Lifecycle (Start, Pause, Resume, Cancel, Retry)
    # -------------------------------------------------------------------------

    async def start(self, config: PipelineConfig) -> str:
        """
        Starts automated state-by-state pipeline run.
        Enforces singleton concurrency locking to prevent multiple runs.
        """
        async with self._lock:
            if self._is_running and self._worker_task and self._worker_task.done():
                logger.warning("Resetting stale worker state where task finished but running flag remained set.")
                self._is_running = False
                self._active_run_id = None
                self._cancel_requested = False

            if self._is_running:
                if self._cancel_requested:
                    raise RuntimeError(
                        f"Pipeline run {self._active_run_id} is currently cancelling. "
                        f"Please wait a moment for current tasks to finish stopping before starting a new run."
                    )
                raise RuntimeError(
                    f"A pipeline run is already active (run_id: {self._active_run_id}). "
                    f"Please pause or cancel it before starting a new run."
                )

            # Persist configuration to SQLite
            self.db.save_pipeline_config(config.model_dump())

            run_id = f"pipe_{int(time.time())}"
            self._active_run_id = run_id
            self._is_running = True
            self._cancel_requested = False
            self._pause_event.set()
            self._recent_errors = []

            plan = self.preview_plan(config)
            total_tasks = plan["counts"]["total_stage1_tasks"]

            run_date = datetime.now().strftime("%Y-%m-%d")
            run_data = {
                "run_id": run_id,
                "run_date": run_date,
                "status": "running",
                "config": config.model_dump(),
                "current_stage": "stage_1_collection" if config.stages.get("collection", True) else (
                    "stage_2_discovery" if config.stages.get("discovery", True) else "stage_3_enrichment"
                ),
                "current_country": plan["scope_summary"]["countries"][0] if plan["scope_summary"]["countries"] else None,
                "current_region": None,
                "current_category": None,
                "total_tasks": total_tasks,
                "completed_tasks": 0,
                "failed_tasks": 0,
                "businesses_collected": 0,
                "websites_verified": 0,
                "companies_enriched": 0,
                "dry_run": config.dry_run,
                "error_message": None,
            }
            self._current_run_data = run_data
            self.db.create_pipeline_run(run_data)

            # If retry_failed is specified, reset failed tasks upfront
            if config.retry_failed:
                self.retry_failed()

            loop = asyncio.get_running_loop()
            self._worker_task = loop.create_task(self._orchestrator_loop(run_id, config, plan))
            self.emit_event("started", {"run_id": run_id, "status": "running", "config": config.model_dump()})
            return run_id

    def pause(self) -> bool:
        """Pauses active execution after the current unit completes."""
        if not self._is_running or not self._active_run_id:
            return False
        self._pause_event.clear()
        self._current_run_data["status"] = "paused"
        self.db.update_pipeline_run(self._active_run_id, {"status": "paused"})
        self.emit_event("paused", {"run_id": self._active_run_id, "status": "paused"})
        return True

    def resume(self) -> bool:
        """Resumes a paused pipeline run."""
        if not self._is_running or not self._active_run_id:
            # Check if there is a paused run in database to resume
            latest = self.db.get_latest_pipeline_run()
            if latest and latest["status"] == "paused":
                cfg = PipelineConfig(**latest["config"])
                # Launch new run continuing from paused checkpoint
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.start(cfg))
                    return True
                except RuntimeError:
                    pass
            return False

        self._pause_event.set()
        self._current_run_data["status"] = "running"
        self.db.update_pipeline_run(self._active_run_id, {"status": "running"})
        self.emit_event("resumed", {"run_id": self._active_run_id, "status": "running"})
        return True

    def cancel(self) -> bool:
        """Cooperatively cancels the active pipeline run."""
        if not self._is_running or not self._active_run_id:
            return False
        self._cancel_requested = True
        self._pause_event.set()  # Unpause to let worker exit cleanly
        self._current_run_data["status"] = "cancelled"
        self.db.update_pipeline_run(self._active_run_id, {"status": "cancelled"})
        self.emit_event("cancelled", {"run_id": self._active_run_id, "status": "cancelled"})
        return True

    def retry_failed(self) -> int:
        """Resets failed tasks in collection_tasks and geographic_tiles to 'pending'."""
        count = self.db.reset_failed_collection_tasks()
        tile_count = self.db.reset_failed_tiles()
        self.emit_event("retry_failed", {"reset_count": count, "reset_tiles_count": tile_count})
        return count

    def get_status(self) -> Dict[str, Any]:
        """Returns live orchestrator status and metrics."""
        task_counts = self.db.get_pipeline_task_counts()
        regions_progress = self.db.get_all_regions_progress()
        latest_run = self.db.get_latest_pipeline_run()
        tile_counts = self.db.get_pipeline_tile_counts(run_id=self._active_run_id)
        available_exports = list_all_state_exports(self.config.absolute_exports_dir)

        enrich_stats = self.db.get_enrichment_stats()
        disc_stats = self.db.get_website_discovery_stats()

        active_run = self._current_run_data if self._is_running else latest_run

        status_str = "idle"
        if self._is_running:
            if self._cancel_requested:
                status_str = "cancelling"
            elif not self._pause_event.is_set():
                status_str = "paused"
            else:
                status_str = "running"
        elif active_run:
            status_str = active_run.get("status", "idle")

        return {
            "is_running": self._is_running,
            "status": status_str,
            "active_run_id": self._active_run_id,
            "current_stage": active_run.get("current_stage") if active_run else "idle",
            "current_country": active_run.get("current_country") if active_run else None,
            "current_region": active_run.get("current_region") if active_run else None,
            "current_category": active_run.get("current_category") if active_run else None,
            "current_tile": active_run.get("current_tile") if active_run else None,
            "dry_run": bool(active_run.get("dry_run", False)) if active_run else False,
            "task_counts": task_counts,
            "tile_counts": tile_counts,
            "total_businesses_collected": self.db.get_stats().get("total_places", 0),
            "websites_verified": disc_stats.get("verified_count", 0),
            "companies_enriched": enrich_stats.get("completed", 0),
            "company_profiles_count": enrich_stats.get("company_profiles_count", 0),
            "company_leaders_count": enrich_stats.get("company_leaders_count", 0),
            "company_contacts_count": enrich_stats.get("company_contacts_count", 0),
            "recent_errors": self._recent_errors[-10:],
            "regions_progress": regions_progress,
            "latest_run": latest_run,
            "available_exports": available_exports[:30],
        }

    # -------------------------------------------------------------------------
    # Internal Execution Engine
    # -------------------------------------------------------------------------

    async def _check_pause_and_cancel(self):
        """Awaits if paused; raises asyncio.CancelledError if cancelled."""
        if self._cancel_requested:
            raise asyncio.CancelledError("Pipeline run cancelled by user request.")
        await self._pause_event.wait()
        if self._cancel_requested:
            raise asyncio.CancelledError("Pipeline run cancelled by user request.")

    async def _orchestrator_loop(self, run_id: str, config: PipelineConfig, plan: Dict[str, Any]):
        """
        Master sequential execution loop:
        1. Stage 1: Business Collection (State by state, category by category).
        2. Stage 2: Official Website Discovery & Verification.
        3. Stage 3: Company Crawling & Information Enrichment.
        """
        total_collected = 0
        total_verified = 0
        total_enriched = 0

        http_client: Optional[HttpClient] = None

        try:
            http_client = HttpClient(
                user_agent=self.config.user_agent,
                accept_language=self.config.accept_language,
                hl="en",
                gl="us",
                concurrency=self.config.concurrency,
                per_host_rate=self.config.per_host_rate,
                max_retries=self.config.max_retries,
                backoff_base=self.config.backoff_base,
                proxies=self.config.proxies,
            )

            scope_pairs = self.resolve_ordered_scope(config.country, config.regions)
            categories = [c.strip() for c in config.categories if c.strip()] or list(DEFAULT_CATEGORIES)

            # =================================================================
            # STAGE 1: BUSINESS COLLECTION (STATE BY STATE, CATEGORY BY CATEGORY)
            # =================================================================
            if config.stages.get("collection", True):
                self._current_run_data["current_stage"] = "stage_1_collection"
                self.db.update_pipeline_run(run_id, {"current_stage": "stage_1_collection"})
                self.emit_event("stage_started", {"stage": "stage_1_collection", "run_id": run_id})

                for country_code, reg in scope_pairs:
                    await self._check_pause_and_cancel()
                    self._current_run_data["current_country"] = country_code
                    self._current_run_data["current_region"] = reg.code
                    self.db.update_pipeline_run(run_id, {
                        "current_country": country_code,
                        "current_region": reg.code
                    })

                    # Process each selected category for this region
                    for cat in categories:
                        await self._check_pause_and_cancel()
                        self._current_run_data["current_category"] = cat
                        self.db.update_pipeline_run(run_id, {"current_category": cat})

                        slug = sanitize_slug(cat)
                        task_id = f"col_{country_code.lower()}_{reg.code.lower()}_{slug}"

                        # 1. Idempotently create/fetch task
                        existing_tasks = self.db.get_collection_tasks(
                            country_code=country_code,
                            region_code=reg.code
                        )
                        task_row = next((t for t in existing_tasks if t["task_id"] == task_id), None)

                        if not task_row:
                            self.db.create_collection_task({
                                "task_id": task_id,
                                "country_code": country_code,
                                "region_code": reg.code,
                                "region_name": reg.name,
                                "category": cat,
                                "tile_id": f"tile_{reg.code.lower()}",
                                "status": "pending",
                                "run_id": run_id,
                            })
                            task_row = {"status": "pending", "attempt_count": 0}

                        # 2. Check if already completed and resume is enabled
                        if config.resume_checkpoint and task_row["status"] == "completed":
                            logger.info(f"Task {task_id} already completed. Skipping (resume).")
                            continue

                        # 3. Check if failed and attempts exceeded without retry requested
                        if task_row["status"] == "failed" and not config.retry_failed and task_row.get("attempt_count", 0) >= config.max_retries:
                            logger.info(f"Task {task_id} permanently failed ({task_row.get('attempt_count')} attempts). Skipping.")
                            continue

                        # 4. Execute the collection task with retries
                        success = False
                        collected_for_task = 0

                        for attempt in range(1, config.max_retries + 1):
                            await self._check_pause_and_cancel()
                            self.db.update_collection_task_status(task_id, "in_progress")
                            self.emit_event("task_progress", {
                                "task_id": task_id,
                                "status": "in_progress",
                                "country": country_code,
                                "region": reg.code,
                                "category": cat,
                                "attempt": attempt,
                            })

                            try:
                                collected_for_task = await self._execute_collection_search(
                                    http_client=http_client,
                                    country_code=country_code,
                                    region=reg,
                                    category=cat,
                                    limit=config.collection_limit,
                                    run_id=run_id,
                                    task_id=task_id,
                                    dry_run=config.dry_run
                                )
                                success = True
                                break
                            except asyncio.CancelledError:
                                raise
                            except Exception as e:
                                err_msg = str(e)
                                logger.warning(f"Error on task {task_id} (attempt {attempt}/{config.max_retries}): {err_msg}")
                                self._recent_errors.append({
                                    "task_id": task_id,
                                    "country": country_code,
                                    "region": reg.code,
                                    "category": cat,
                                    "error": err_msg,
                                    "timestamp": datetime.now().isoformat()
                                })
                                self.db.update_collection_task_status(task_id, "failed", error=err_msg)
                                if attempt < config.max_retries:
                                    await asyncio.sleep(1.0 * attempt)

                        if success:
                            self.db.update_collection_task_status(
                                task_id, "completed", records_collected=collected_for_task
                            )
                            total_collected += collected_for_task
                            self._current_run_data["businesses_collected"] = total_collected
                            self.db.update_pipeline_run(run_id, {
                                "businesses_collected": total_collected,
                                "completed_tasks": self._current_run_data.get("completed_tasks", 0) + 1
                            })

                            # Immediate Category-wise export
                            run_date = self._current_run_data.get("run_date") or datetime.now().strftime("%Y-%m-%d")
                            try:
                                export_state_category_data(
                                    db=self.db,
                                    base_exports_dir=self.config.absolute_exports_dir,
                                    run_id=run_id,
                                    run_date=run_date,
                                    country_code=country_code,
                                    region_code=reg.code,
                                    region_name=reg.name,
                                    category=cat
                                )
                            except Exception as ex_err:
                                logger.warning(f"Error exporting category {cat} data: {ex_err}")

                            self.emit_event("task_completed", {
                                "task_id": task_id,
                                "country": country_code,
                                "region": reg.code,
                                "category": cat,
                                "records_collected": collected_for_task,
                                "total_collected": total_collected,
                            })
                        else:
                            self._current_run_data["failed_tasks"] = self._current_run_data.get("failed_tasks", 0) + 1
                            self.db.update_pipeline_run(run_id, {
                                "failed_tasks": self._current_run_data["failed_tasks"]
                            })

                    # Region transition rule:
                    # Move to next region only when this region's tasks are complete or explicitly terminal
                    reg_prog = self.db.get_region_progress(country_code, reg.code)
                    logger.info(f"Region {country_code}-{reg.code} batch complete: {reg_prog}")

                    # Generate or refresh state summary and complete package
                    run_date = self._current_run_data.get("run_date") or datetime.now().strftime("%Y-%m-%d")
                    try:
                        pkg_res = export_state_complete_package(
                            db=self.db,
                            base_exports_dir=self.config.absolute_exports_dir,
                            run_id=run_id,
                            run_date=run_date,
                            country_code=country_code,
                            region_code=reg.code,
                            region_name=reg.name,
                            categories=categories
                        )
                        self.emit_event("state_exported", {
                            "country": country_code,
                            "region": reg.code,
                            "relative_dir": pkg_res["relative_dir"],
                            "all_businesses_count": pkg_res["all_businesses_count"],
                            "summary": pkg_res["summary"]
                        })
                    except Exception as ex_err:
                        logger.warning(f"Error exporting state package for {country_code}-{reg.code}: {ex_err}")

            # =================================================================
            # STAGE 2: WEBSITE DISCOVERY & VERIFICATION
            # =================================================================
            if config.stages.get("discovery", True):
                await self._check_pause_and_cancel()
                self._current_run_data["current_stage"] = "stage_2_discovery"
                self._current_run_data["current_category"] = None
                self.db.update_pipeline_run(run_id, {
                    "current_stage": "stage_2_discovery",
                    "current_category": None
                })
                self.emit_event("stage_started", {"stage": "stage_2_discovery", "run_id": run_id})

                discovery_service = WebsiteDiscoveryService(self.db, user_agent=self.config.user_agent)

                for country_code, reg in scope_pairs:
                    await self._check_pause_and_cancel()
                    self._current_run_data["current_country"] = country_code
                    self._current_run_data["current_region"] = reg.code
                    self.db.update_pipeline_run(run_id, {
                        "current_country": country_code,
                        "current_region": reg.code
                    })

                    disc_res = await discovery_service.run_discovery(
                        country_code=country_code,
                        region_code=reg.code,
                        limit=config.batch_size,
                        retry_failed=config.retry_failed,
                        force=False,
                        dry_run=config.dry_run,
                    )
                    v_count = disc_res.get("counts", {}).get("verified", 0)
                    total_verified += v_count
                    self._current_run_data["websites_verified"] = total_verified
                    self.db.update_pipeline_run(run_id, {"websites_verified": total_verified})
                    self.emit_event("stage2_progress", {
                        "country": country_code,
                        "region": reg.code,
                        "verified_in_region": v_count,
                        "total_verified": total_verified,
                    })

            # =================================================================
            # STAGE 3: WEBSITE CRAWLING & COMPANY ENRICHMENT
            # =================================================================
            if config.stages.get("enrichment", True):
                await self._check_pause_and_cancel()
                self._current_run_data["current_stage"] = "stage_3_enrichment"
                self._current_run_data["current_category"] = None
                self.db.update_pipeline_run(run_id, {
                    "current_stage": "stage_3_enrichment",
                    "current_category": None
                })
                self.emit_event("stage_started", {"stage": "stage_3_enrichment", "run_id": run_id})

                enrichment_service = WebsiteEnrichmentService(
                    self.db,
                    max_pages=config.max_crawl_pages,
                    user_agent=self.config.user_agent
                )

                for country_code, reg in scope_pairs:
                    await self._check_pause_and_cancel()
                    self._current_run_data["current_country"] = country_code
                    self._current_run_data["current_region"] = reg.code
                    self.db.update_pipeline_run(run_id, {
                        "current_country": country_code,
                        "current_region": reg.code
                    })

                    enrich_res = await enrichment_service.run_enrichment(
                        country_code=country_code,
                        region_code=reg.code,
                        limit=config.batch_size,
                        max_pages=config.max_crawl_pages,
                        retry_failed=config.retry_failed,
                        force=False,
                        dry_run=config.dry_run,
                    )
                    c_count = enrich_res.get("counts", {}).get("completed", 0)
                    total_enriched += c_count
                    self._current_run_data["companies_enriched"] = total_enriched
                    self.db.update_pipeline_run(run_id, {"companies_enriched": total_enriched})
                    self.emit_event("stage3_progress", {
                        "country": country_code,
                        "region": reg.code,
                        "completed_in_region": c_count,
                        "total_enriched": total_enriched,
                    })

            # Synchronize affected regional SQLite databases and export packages
            try:
                self._sync_and_export_affected_regions(scope_pairs, run_id, is_failed=False)
            except Exception as se_err:
                logger.error(f"Error during regional sync and exports: {se_err}")

            # Mark completed
            self._current_run_data["status"] = "completed"
            self._current_run_data["current_stage"] = "completed"
            self.db.update_pipeline_run(run_id, {
                "status": "completed",
                "current_stage": "completed"
            })
            self.emit_event("completed", {
                "run_id": run_id,
                "status": "completed",
                "businesses_collected": total_collected,
                "websites_verified": total_verified,
                "companies_enriched": total_enriched,
            })

        except asyncio.CancelledError:
            logger.info(f"Pipeline run {run_id} cancelled.")
            try:
                if 'scope_pairs' in locals() and scope_pairs:
                    self._sync_and_export_affected_regions(scope_pairs, run_id, is_failed=True)
            except Exception as se_err:
                logger.error(f"Error syncing affected regions on cancellation: {se_err}")
            self._current_run_data["status"] = "cancelled"
            self.db.update_pipeline_run(run_id, {"status": "cancelled"})
            self.emit_event("cancelled", {"run_id": run_id, "status": "cancelled"})
        except Exception as e:
            logger.exception(f"Pipeline run {run_id} encountered fatal error: {e}")
            try:
                if 'scope_pairs' in locals() and scope_pairs:
                    self._sync_and_export_affected_regions(scope_pairs, run_id, is_failed=True)
            except Exception as se_err:
                logger.error(f"Error syncing affected regions on failure: {se_err}")
            err_str = str(e)
            self._current_run_data["status"] = "failed"
            self._current_run_data["error_message"] = err_str
            self.db.update_pipeline_run(run_id, {"status": "failed", "error_message": err_str})
            self.emit_event("failed", {"run_id": run_id, "status": "failed", "error": err_str})
        finally:
            if http_client:
                try:
                    await http_client.close()
                except Exception:
                    pass
            self._is_running = False
            self._active_run_id = None
            self._cancel_requested = False

    def _sync_and_export_affected_regions(
        self,
        scope_pairs: List[Tuple[str, RegionInfo]],
        run_id: str,
        is_failed: bool = False
    ) -> Dict[str, Any]:
        """
        Synchronizes affected regional SQLite databases and exports CSV/JSON packages
        from the central SQLite database.
        """
        storage_mgr = RegionalStorageManager(self.db, self.config)
        results: Dict[str, List[Any]] = {"synced": [], "failed": []}
        run_date = self._current_run_data.get("run_date") or datetime.now().strftime("%Y-%m-%d")

        for country_code, reg in scope_pairs:
            try:
                res = storage_mgr.sync_and_export_region(
                    country_code=country_code,
                    region_code=reg.code,
                    region_name=reg.name,
                    run_id=run_id,
                    run_date=run_date
                )
                results["synced"].append(res)
                self.emit_event("region_synced", {
                    "country": country_code,
                    "region": reg.code,
                    "places_synced": res.get("sync", {}).get("places_synced", 0),
                    "db_path": res.get("regional_db_path"),
                    "status": "success",
                    "pipeline_failed": is_failed
                })
            except Exception as e:
                logger.error(f"Failed to sync/export regional database for {country_code}-{reg.code}: {e}")
                results["failed"].append({
                    "country": country_code,
                    "region": reg.code,
                    "error": str(e)
                })
                self.emit_event("region_sync_failed", {
                    "country": country_code,
                    "region": reg.code,
                    "error": str(e),
                    "pipeline_failed": is_failed
                })
        return results

    async def _execute_collection_search(
        self,
        http_client: HttpClient,
        country_code: str,
        region: RegionInfo,
        category: str,
        limit: int,
        run_id: str,
        task_id: Optional[str] = None,
        dry_run: bool = False
    ) -> int:
        """
        Executes Geographic Tile-Based Scraping for a region and category (Section 3).
        Generates/retrieves deterministic tiles, searches Google Maps, deduplicates by CID,
        persists tile metrics, detects saturation, subdivides into quadrants, and handles retries.
        """
        gl, hl = get_country_bias(country_code)
        eff_task_id = task_id or f"col_{country_code.lower()}_{region.code.lower()}_{sanitize_slug(category)}"

        # 1. Retrieve or generate geographic tiles for this task
        existing_tiles = self.db.get_geographic_tiles(
            country_code=country_code,
            region_code=region.code,
            category=category,
            task_id=eff_task_id
        )

        if not existing_tiles:
            step_deg = getattr(self.config, "tile_step_deg", 0.5)
            # Adaptive refinement for small regions
            if region.code in ("CMX", "TLA", "RI", "DE", "DC", "MOR"):
                step_deg = 0.1
            tiles = generate_region_grid_tiles(
                country_code=country_code,
                region_code=region.code,
                category=category,
                task_id=eff_task_id,
                run_id=run_id,
                step_deg=step_deg
            )
            for t in tiles:
                self.db.create_geographic_tile(t.model_dump())
            self.emit_event("tiles_generated", {
                "task_id": eff_task_id,
                "country": country_code,
                "region": region.code,
                "category": category,
                "count": len(tiles)
            })
            existing_tiles = self.db.get_geographic_tiles(
                country_code=country_code,
                region_code=region.code,
                category=category,
                task_id=eff_task_id
            )

        # 2. Build work queue of unfinished tiles
        work_queue: List[GeoTile] = []
        for t_dict in existing_tiles:
            tile_obj = GeoTile(**t_dict)
            if tile_obj.status in ("pending", "running", "retry_pending"):
                work_queue.append(tile_obj)
            elif tile_obj.status == "failed" and self.config.retry_failed:
                tile_obj.status = "pending"
                work_queue.append(tile_obj)

        # 3. Track unique businesses
        seen_cids: Set[str] = set()
        with self.db.get_connection() as conn:
            rows = conn.execute("""
                SELECT cid FROM places
                WHERE country_code = ? AND region = ? AND lower(category) = lower(?)
            """, (country_code.upper(), region.code.upper(), category)).fetchall()
            seen_cids.update(r["cid"] for r in rows if r["cid"])

        max_depth = getattr(self.config, "tile_max_depth", 2)
        overlap_pct = getattr(self.config, "tile_overlap_pct", 10.0)

        # 4. Process tiles in work queue
        while work_queue:
            if limit and len(seen_cids) >= limit:
                break

            tile = work_queue.pop(0)
            await self._check_pause_and_cancel()

            self._current_run_data["current_tile"] = tile.tile_id
            tile.status = "running"
            tile.started_at = datetime.now().isoformat()
            self.db.update_geographic_tile(tile.tile_id, {
                "status": "running",
                "started_at": tile.started_at
            })
            self.emit_event("tile_progress", {
                "tile_id": tile.tile_id,
                "task_id": eff_task_id,
                "status": "running",
                "country": country_code,
                "region": region.code,
                "category": category,
                "depth": tile.depth,
                "center_lat": tile.center_lat,
                "center_lng": tile.center_lng,
                "min_lat": tile.min_lat,
                "max_lat": tile.max_lat,
                "min_lng": tile.min_lng,
                "max_lng": tile.max_lng,
                "span_deg": tile.span_deg,
            })

            stubs = []
            tile_success = False
            last_err = None
            http_status = None

            if dry_run:
                # Dry run simulation: zero external requests
                await asyncio.sleep(0.01)
                tile_success = True
                base_idx = abs(hash(tile.tile_id)) % 100000
                stubs_count = 20 if tile.depth == 0 and len(work_queue) < 4 else 5
                for i in range(stubs_count):
                    cid_val = f"dry_{country_code.lower()}_{region.code.lower()}_{base_idx + i}"
                    stubs.append(PlaceStub(
                        cid=cid_val,
                        ftid=f"0x0:0x{base_idx + i:x}",
                        place_id=f"PID_{cid_val}",
                        name=f"{category.title()} Business {base_idx + i}",
                        address=f"{region.name}, {country_code}",
                        latitude=tile.center_lat,
                        longitude=tile.center_lng,
                        category=category,
                        status="pending"
                    ))
            else:
                for attempt in range(1, self.config.max_retries + 1):
                    await self._check_pause_and_cancel()
                    tile.attempts += 1
                    pb = build_search_pb(tile.center_lat, tile.center_lng, span_meters=tile.span_meters, num_results=20)
                    url = f"https://www.google.com/search?tbm=map&authuser=0&hl={hl}&gl={gl}&pb={pb}&q={urllib.parse.quote(category)}"
                    try:
                        resp = await http_client.get(url)
                        http_status = resp.status_code
                        stubs = parse_search_rpc_response(resp.text)
                        tile_success = True
                        break
                    except Exception as e:
                        last_err = str(e)
                        tile.retry_count += 1
                        if attempt < self.config.max_retries:
                            self.db.update_geographic_tile(tile.tile_id, {
                                "status": "retry_pending",
                                "attempts": tile.attempts,
                                "retry_count": tile.retry_count,
                                "last_error": last_err
                            })
                            await asyncio.sleep(1.0 * attempt)

            if not tile_success:
                tile.status = "failed"
                tile.last_error = last_err
                self.db.update_geographic_tile(tile.tile_id, {
                    "status": "failed",
                    "attempts": tile.attempts,
                    "retry_count": tile.retry_count,
                    "last_error": last_err,
                    "http_status": http_status
                })
                self.emit_event("tile_failed", {
                    "tile_id": tile.tile_id,
                    "task_id": eff_task_id,
                    "error": last_err
                })
                continue

            # Process places
            new_in_tile = 0
            dup_in_tile = 0
            for stub in stubs:
                if stub.cid in seen_cids:
                    dup_in_tile += 1
                    continue
                if limit and len(seen_cids) >= limit:
                    break
                seen_cids.add(stub.cid)
                stub_dict = stub.model_dump()
                stub_dict["country_code"] = country_code.upper()
                stub_dict["region"] = region.code.upper()
                stub_dict["first_seen_job_id"] = run_id
                stub_dict["tile_id"] = tile.tile_id
                if not dry_run:
                    if self.db.upsert_place_stub(stub_dict):
                        new_in_tile += 1
                    enrich_place_dimensions({"category": stub.category, "address": stub.address})
                else:
                    new_in_tile += 1

            # Check saturation (20 results hard cap)
            if len(stubs) >= 20 and tile.depth < max_depth and tile.span_deg > 0.02:
                tile.status = "subdivided"
                tile.subdivision_status = "subdivided_into_4"
                children = tile.subdivide(overlap_pct=overlap_pct, max_depth=max_depth)
                for child in children:
                    self.db.create_geographic_tile(child.model_dump())
                    work_queue.append(child)
                self.db.update_geographic_tile(tile.tile_id, {
                    "status": "subdivided",
                    "results_count": len(stubs),
                    "new_records": new_in_tile,
                    "duplicate_cids": dup_in_tile,
                    "subdivision_status": "subdivided_into_4",
                    "completed_at": datetime.now().isoformat(),
                    "last_checkpoint": datetime.now().isoformat()
                })
                self.emit_event("tile_subdivided", {
                    "tile_id": tile.tile_id,
                    "task_id": eff_task_id,
                    "children_count": len(children),
                    "depth": tile.depth
                })
            else:
                if len(stubs) >= 20:
                    tile.status = "limit_reached"
                else:
                    tile.status = "completed"
                self.db.update_geographic_tile(tile.tile_id, {
                    "status": tile.status,
                    "results_count": len(stubs),
                    "new_records": new_in_tile,
                    "duplicate_cids": dup_in_tile,
                    "completed_at": datetime.now().isoformat(),
                    "last_checkpoint": datetime.now().isoformat()
                })
                self.emit_event("tile_completed", {
                    "tile_id": tile.tile_id,
                    "task_id": eff_task_id,
                    "status": tile.status,
                    "results_count": len(stubs),
                    "new_records": new_in_tile,
                    "duplicate_cids": dup_in_tile
                })

        return len(seen_cids)
