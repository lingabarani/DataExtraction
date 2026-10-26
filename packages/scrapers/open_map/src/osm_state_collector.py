#!/usr/bin/env python3
"""
US OSM Complete State-Wise Business/POI Data Collector Engine.

Adheres strictly to:
- Free public OpenStreetMap Overpass API only
- Pure data extraction: NO validation, NO enrichment, NO paid providers
- Sequential State -> Field -> Chunk workflow
- No artificial record limits (collects all available OSM objects)
- Incremental chunk-by-chunk persistence (data/raw/, data/processed/, data/export/)
- Deterministic deduplication by (osm_type + osm_id)
- Raw tags preservation in raw_tags
- Checkpoint persistence and resume support in data/progress/osm_progress.json
"""

import csv
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import OverpassConfig, default_config
from src.checkpoint import EnterpriseCheckpointManager
from src.quadtree import AdaptiveQuadtree, split_bounding_box
from src.sources.osm_overpass import (
    OpenStreetMapSource,
    OverpassTimeoutError,
    CSV_EXPORT_FIELDS,
    DEFAULT_OVERPASS_ENDPOINT,
    validate_overpass_response
)

# Set up logging
logger = logging.getLogger("OSMStateCollector")

# ==============================================================================
# 50 US STATES DEFINITION (EXACT SPECIFIED ORDER)
# ==============================================================================
US_STATES: List[Tuple[str, str]] = [
    ("Alabama", "AL"),
    ("Alaska", "AK"),
    ("Arizona", "AZ"),
    ("Arkansas", "AR"),
    ("California", "CA"),
    ("Colorado", "CO"),
    ("Connecticut", "CT"),
    ("Delaware", "DE"),
    ("Florida", "FL"),
    ("Georgia", "GA"),
    ("Hawaii", "HI"),
    ("Idaho", "ID"),
    ("Illinois", "IL"),
    ("Indiana", "IN"),
    ("Iowa", "IA"),
    ("Kansas", "KS"),
    ("Kentucky", "KY"),
    ("Louisiana", "LA"),
    ("Maine", "ME"),
    ("Maryland", "MD"),
    ("Massachusetts", "MA"),
    ("Michigan", "MI"),
    ("Minnesota", "MN"),
    ("Mississippi", "MS"),
    ("Missouri", "MO"),
    ("Montana", "MT"),
    ("Nebraska", "NE"),
    ("Nevada", "NV"),
    ("New Hampshire", "NH"),
    ("New Jersey", "NJ"),
    ("New Mexico", "NM"),
    ("New York", "NY"),
    ("North Carolina", "NC"),
    ("North Dakota", "ND"),
    ("Ohio", "OH"),
    ("Oklahoma", "OK"),
    ("Oregon", "OR"),
    ("Pennsylvania", "PA"),
    ("Rhode Island", "RI"),
    ("South Carolina", "SC"),
    ("South Dakota", "SD"),
    ("Tennessee", "TN"),
    ("Texas", "TX"),
    ("Utah", "UT"),
    ("Vermont", "VT"),
    ("Virginia", "VA"),
    ("Washington", "WA"),
    ("West Virginia", "WV"),
    ("Wisconsin", "WI"),
    ("Wyoming", "WY")
]

# State Bounding Boxes: (min_lat, min_lon, max_lat, max_lon)
STATE_BOUNDING_BOXES: Dict[str, Tuple[float, float, float, float]] = {
    "Alabama": (30.14, -88.47, 35.01, -84.89),
    "Alaska": (51.20, -179.15, 71.39, -129.98),
    "Arizona": (31.33, -114.82, 37.00, -109.04),
    "Arkansas": (33.00, -94.62, 36.50, -89.64),
    "California": (32.53, -124.41, 42.01, -114.13),
    "Colorado": (36.99, -109.06, 41.00, -102.04),
    "Connecticut": (40.98, -73.73, 42.05, -71.79),
    "Delaware": (38.45, -75.79, 39.84, -75.05),
    "Florida": (24.52, -87.63, 31.00, -80.03),
    "Georgia": (30.36, -85.61, 35.00, -80.84),
    "Hawaii": (18.91, -160.25, 22.24, -154.81),
    "Idaho": (41.99, -117.24, 49.00, -111.04),
    "Illinois": (36.97, -91.51, 42.51, -87.50),
    "Indiana": (37.77, -88.10, 41.76, -84.78),
    "Iowa": (40.38, -96.64, 43.50, -90.14),
    "Kansas": (36.99, -102.05, 40.00, -94.59),
    "Kentucky": (36.50, -89.57, 39.15, -81.96),
    "Louisiana": (28.92, -94.04, 33.02, -88.82),
    "Maine": (43.06, -71.08, 47.46, -66.95),
    "Maryland": (37.91, -79.49, 39.72, -75.05),
    "Massachusetts": (41.24, -73.51, 42.89, -69.93),
    "Michigan": (41.70, -90.42, 48.31, -82.41),
    "Minnesota": (43.50, -97.24, 49.38, -89.49),
    "Mississippi": (30.17, -91.66, 35.00, -88.10),
    "Missouri": (35.99, -95.77, 40.61, -89.10),
    "Montana": (44.36, -116.05, 49.00, -104.04),
    "Nebraska": (40.00, -104.05, 43.00, -95.31),
    "Nevada": (35.00, -120.01, 42.00, -114.04),
    "New Hampshire": (42.70, -72.56, 45.31, -70.70),
    "New Jersey": (38.93, -75.56, 41.36, -73.89),
    "New Mexico": (31.33, -109.05, 37.00, -103.00),
    "New York": (40.50, -79.76, 45.02, -71.86),
    "North Carolina": (33.84, -84.32, 36.59, -75.46),
    "North Dakota": (45.93, -104.05, 49.00, -96.55),
    "Ohio": (38.40, -84.82, 41.98, -80.52),
    "Oklahoma": (33.62, -103.00, 37.00, -94.43),
    "Oregon": (41.99, -124.57, 46.29, -116.46),
    "Pennsylvania": (39.72, -80.52, 42.27, -74.69),
    "Rhode Island": (41.15, -71.86, 42.02, -71.12),
    "South Carolina": (32.03, -83.35, 35.22, -78.54),
    "South Dakota": (42.48, -104.06, 45.95, -96.44),
    "Tennessee": (34.98, -90.31, 36.68, -81.65),
    "Texas": (25.84, -106.65, 36.50, -93.51),
    "Utah": (36.99, -114.05, 42.00, -109.04),
    "Vermont": (42.73, -73.44, 45.02, -71.50),
    "Virginia": (36.54, -83.68, 39.47, -75.24),
    "Washington": (45.54, -124.76, 49.00, -116.92),
    "West Virginia": (37.20, -82.64, 40.64, -77.72),
    "Wisconsin": (42.49, -92.89, 47.08, -86.81),
    "Wyoming": (40.99, -111.06, 45.01, -104.05)
}

# ==============================================================================
# TAXONOMY & FIELD MAPPING (SECTIONS 4, 5, 25)
# ==============================================================================
FIELDS_TAXONOMY: List[Dict[str, Any]] = [
    {
        "field": "shop",
        "category_group": "COMMERCIAL",
        "query_template": 'nwr["shop"]({s},{w},{n},{e});'
    },
    {
        "field": "office",
        "category_group": "COMMERCIAL",
        "query_template": 'nwr["office"]({s},{w},{n},{e});'
    },
    {
        "field": "amenity",
        "category_group": "SERVICES",
        "query_template": 'nwr["amenity"]({s},{w},{n},{e});'
    },
    {
        "field": "craft",
        "category_group": "SERVICES",
        "query_template": 'nwr["craft"]({s},{w},{n},{e});'
    },
    {
        "field": "industrial",
        "category_group": "INDUSTRIAL",
        "query_template": (
            'nwr["industrial"]({s},{w},{n},{e});\n'
            '  nwr["landuse"="industrial"]({s},{w},{n},{e});\n'
            '  nwr["building"="industrial"]({s},{w},{n},{e});\n'
            '  nwr["building"="warehouse"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "healthcare",
        "category_group": "HEALTHCARE",
        "query_template": (
            'nwr["healthcare"]({s},{w},{n},{e});\n'
            '  nwr["amenity"~"^(hospital|clinic|doctors|dentist|pharmacy|veterinary|nursing_home)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "education",
        "category_group": "EDUCATION",
        "query_template": (
            'nwr["amenity"~"^(school|college|university|kindergarten|training|language_school|research_institute)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "tourism",
        "category_group": "TOURISM",
        "query_template": 'nwr["tourism"]({s},{w},{n},{e});'
    },
    {
        "field": "food",
        "category_group": "FOOD",
        "query_template": (
            'nwr["amenity"~"^(restaurant|cafe|fast_food|bar|pub|food_court)$"]({s},{w},{n},{e});\n'
            '  nwr["shop"~"^(bakery|butcher)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "leisure",
        "category_group": "LEISURE",
        "query_template": (
            'nwr["leisure"]({s},{w},{n},{e});\n'
            '  nwr["amenity"~"^(cinema|theatre)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "transport",
        "category_group": "TRANSPORT",
        "query_template": (
            'nwr["aeroway"]({s},{w},{n},{e});\n'
            '  nwr["railway"="station"]({s},{w},{n},{e});\n'
            '  nwr["public_transport"]({s},{w},{n},{e});\n'
            '  nwr["amenity"~"^(parking|charging_station|fuel|bus_station|taxi|bicycle_rental)$"]({s},{w},{n},{e});'
        )
    },
    {
        "field": "man_made",
        "category_group": "MAN_MADE",
        "query_template": 'nwr["man_made"]({s},{w},{n},{e});'
    },
    {
        "field": "organizations",
        "category_group": "ORGANIZATIONS",
        "query_template": (
            'nwr["club"]({s},{w},{n},{e});\n'
            '  nwr["amenity"~"^(community_centre|social_centre|place_of_worship)$"]({s},{w},{n},{e});\n'
            '  nwr["office"~"^(association|foundation|ngo)$"]({s},{w},{n},{e});'
        )
    }
]

# Default full US workflow: resume from the checkpoint and continue from the next unfinished state/field.
ENABLED_STATES: List[Tuple[str, str]] = list(US_STATES)


def slugify(text: str) -> str:
    """Return filesystem-safe lowercase slug."""
    return "".join(c if c.isalnum() else "_" for c in text.strip().lower()).strip("_")


class OSMStateCollector:
    """
    Controller for sequential state-by-state, field-by-field, chunk-by-chunk
    OSM business and POI data collection.
    """

    def __init__(
        self,
        workspace_dir: Optional[str] = None,
        chunk_size_deg: Optional[float] = None,
        endpoint_url: Optional[str] = None,
        config: Optional[OverpassConfig] = None
    ):
        if workspace_dir is None:
            self.workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        else:
            self.workspace_dir = os.path.abspath(workspace_dir)

        self.config = config or default_config
        self.chunk_size_deg = chunk_size_deg if chunk_size_deg is not None else self.config.chunk_size_deg
        
        target_endpoint = endpoint_url or self.config.primary_endpoint
        self.osm_source = OpenStreetMapSource(endpoint_url=target_endpoint, config=self.config)

        # Output directory structures
        self.raw_base_dir = os.path.join(self.workspace_dir, "data", "raw")
        self.processed_base_dir = os.path.join(self.workspace_dir, "data", "processed")
        self.export_base_dir = os.path.join(self.workspace_dir, "data", "export")
        self.progress_dir = os.path.join(self.workspace_dir, "data", "progress")
        self.logs_dir = os.path.join(self.workspace_dir, "logs")

        for d in [self.raw_base_dir, self.processed_base_dir, self.export_base_dir, self.progress_dir, self.logs_dir]:
            os.makedirs(d, exist_ok=True)

        # Enterprise ACID Checkpoint Manager (SQLite WAL mode + JSON sync)
        self.checkpoint_manager = EnterpriseCheckpointManager(self.workspace_dir)

        # Adaptive Quadtree Spatial Subdivision Engine
        self.quadtree = AdaptiveQuadtree(
            max_depth=self.config.max_quadtree_depth,
            min_chunk_deg=self.config.min_chunk_deg
        )

        self.progress_file = os.path.join(self.progress_dir, "osm_progress.json")
        self._backup_progress()
        self.progress_data: Dict[str, Any] = self._load_progress()
        self._reconcile_existing_progress()

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Formats seconds into HH:MM:SS."""
        if seconds < 0:
            return "00:00:00"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _backup_progress(self) -> None:
        """Backs up progress file before any modification."""
        if not os.path.exists(self.progress_file):
            return
        try:
            bak_path = f"{self.progress_file}.bak"
            shutil.copyfile(self.progress_file, bak_path)
            date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
            hist_backup = os.path.join(self.progress_dir, f"osm_progress_backup_{date_str}.json")
            if not os.path.exists(hist_backup):
                shutil.copyfile(self.progress_file, hist_backup)
        except Exception as e:
            logger.warning(f"Could not backup progress file: {e}")

    def _load_progress(self) -> Dict[str, Any]:
        """Loads persistent progress tracker JSON."""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load existing progress file {self.progress_file}: {e}")
        return {}

    def _save_progress(self) -> None:
        """Saves current state and chunk progress atomically."""
        self._backup_progress()
        tmp_file = f"{self.progress_file}.tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.progress_data, f, indent=2)
            os.replace(tmp_file, self.progress_file)
        except Exception as e:
            logger.error(f"Failed to save progress file {self.progress_file}: {e}")

    def _reconcile_existing_progress(self) -> None:
        """
        Reconciles progress data across all states and fields:
        - Prevents 81/80: guarantees completed count cannot exceed chunks_total.
        - Removes completed chunks from failed_chunk_ids list.
        - Synchronizes stats dictionary.
        """
        changed = False
        for state_name, state_fields in self.progress_data.items():
            if not isinstance(state_fields, dict):
                continue
            for field_name, field_progress in state_fields.items():
                if not isinstance(field_progress, dict):
                    continue

                chunks_total = field_progress.get("chunks_total", 80)
                completed_ids = set(field_progress.get("completed_chunk_ids", []))
                failed_ids = field_progress.get("failed_chunk_ids", [])

                # Clean failed list: chunk cannot be both completed and failed
                clean_failed = [cid for cid in failed_ids if cid not in completed_ids]
                if clean_failed != failed_ids:
                    field_progress["failed_chunk_ids"] = clean_failed
                    changed = True

                # Bound completed chunk ids
                clean_completed = sorted(completed_ids)
                if len(clean_completed) > chunks_total:
                    clean_completed = clean_completed[:chunks_total]
                    changed = True

                if field_progress.get("completed_chunk_ids") != clean_completed:
                    field_progress["completed_chunk_ids"] = clean_completed
                    changed = True

                if field_progress.get("chunks_completed") != len(clean_completed):
                    field_progress["chunks_completed"] = len(clean_completed)
                    changed = True

                # Synchronize stats
                stats = field_progress.setdefault("stats", {})
                if stats is not None and isinstance(stats, dict):
                    stats["total_chunks"] = chunks_total
                    stats["successful_chunks"] = len(clean_completed)
                    stats["failed_chunks"] = len(clean_failed)

        if changed:
            self._save_progress()

    def identify_affected_chunks(self, state_name: str, field_name: str) -> List[str]:
        """
        Identifies chunks marked complete after empty responses from the incorrect
        regional endpoint (e.g., timestamp_osm_base == '117166').
        """
        state_progress = self.progress_data.get(state_name, {})
        field_progress = state_progress.get(field_name, {})
        completed_ids = field_progress.get("completed_chunk_ids", [])
        if not completed_ids:
            return []

        state_slug = slugify(state_name)
        raw_dir = os.path.join(self.raw_base_dir, state_slug, field_name)
        artifact_map = field_progress.get("chunk_artifacts", {})

        affected = []
        for cid in completed_ids:
            artifact = artifact_map.get(cid, {})
            raw_name = artifact.get("raw", f"{cid}.json")
            raw_path = os.path.join(raw_dir, raw_name)
            if not os.path.exists(raw_path):
                raw_path = os.path.join(raw_dir, f"{cid}.json")

            if os.path.exists(raw_path):
                try:
                    with open(raw_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                    ts = raw_data.get("osm3s", {}).get("timestamp_osm_base", "")
                    elems = raw_data.get("elements", [])
                    if ts == "117166":
                        affected.append(cid)
                    elif len(elems) == 0 and "osm.ch" in str(raw_data.get("osm3s", {})):
                        affected.append(cid)
                except Exception:
                    pass

        # If entire field reported 0 records and was completed with 117166, all are affected
        if not affected and field_progress.get("status") == "completed" and field_progress.get("records_collected", 0) == 0:
            sample_path = os.path.join(raw_dir, "chunk_0001.json")
            if os.path.exists(sample_path):
                try:
                    with open(sample_path, "r", encoding="utf-8") as f:
                        if json.load(f).get("osm3s", {}).get("timestamp_osm_base") == "117166":
                            affected = list(completed_ids)
                except Exception:
                    pass

        return sorted(affected)

    def prepare_affected_chunks_recovery(self, state_name: str, field_name: str) -> List[str]:
        """
        Prepares affected chunks for recovery retry:
        - Removes affected chunk IDs from completed_chunk_ids.
        - Sets field status to 'in_progress'.
        - Preserves unaffected chunks and existing files.
        """
        affected = self.identify_affected_chunks(state_name, field_name)
        if not affected:
            return []

        self._backup_progress()
        field_progress = self.progress_data.setdefault(state_name, {}).setdefault(field_name, {})
        completed_set = set(field_progress.get("completed_chunk_ids", []))
        for aid in affected:
            completed_set.discard(aid)

        field_progress["completed_chunk_ids"] = sorted(completed_set)
        field_progress["chunks_completed"] = len(completed_set)
        field_progress["status"] = "in_progress"
        field_progress["completed_at"] = None

        # Clean from failed list so they retry cleanly
        field_progress["failed_chunk_ids"] = [
            cid for cid in field_progress.get("failed_chunk_ids", [])
            if cid not in affected and cid not in completed_set
        ]

        print(
            f"[RESUME] State={state_name} Field={field_name}: Identified {len(affected)} affected chunks from incorrect endpoint. "
            f"Reset for recovery retry ({len(completed_set)} remaining confirmed complete).",
            flush=True
        )
        self._save_progress()
        return affected

    @staticmethod
    def _collision_safe_path(directory: str, filename: str) -> str:
        """Returns a non-colliding filename preserving any existing file."""
        base, extension = os.path.splitext(filename)
        candidate = os.path.join(directory, filename)
        suffix = 1
        while os.path.exists(candidate):
            candidate = os.path.join(directory, f"{base}.retry_{suffix:03d}{extension}")
            suffix += 1
        return candidate

    def _chunk_output_paths(
        self,
        chunk_dir_raw: str,
        chunk_dir_proc: str,
        field_progress: Dict[str, Any],
        chunk_id: str,
    ) -> Tuple[str, str]:
        """
        Returns separate, non-colliding paths for chunk files to ensure
        previously collected files are NEVER overwritten or deleted during recovery.
        """
        artifact_map = field_progress.setdefault("chunk_artifacts", {})
        if chunk_id in artifact_map:
            artifact = artifact_map[chunk_id]
            return (
                os.path.join(chunk_dir_raw, artifact["raw"]),
                os.path.join(chunk_dir_proc, artifact["processed"]),
            )

        raw_name = f"{chunk_id}.json"
        processed_name = f"{chunk_id}.json"
        if os.path.exists(os.path.join(chunk_dir_raw, raw_name)) or os.path.exists(os.path.join(chunk_dir_proc, processed_name)):
            suffix = 1
            while (
                os.path.exists(os.path.join(chunk_dir_raw, f"{chunk_id}.retry_{suffix:03d}.json"))
                or os.path.exists(os.path.join(chunk_dir_proc, f"{chunk_id}.retry_{suffix:03d}.json"))
            ):
                suffix += 1
            raw_name = f"{chunk_id}.retry_{suffix:03d}.json"
            processed_name = raw_name

        artifact_map[chunk_id] = {"raw": raw_name, "processed": processed_name}
        return (
            os.path.join(chunk_dir_raw, raw_name),
            os.path.join(chunk_dir_proc, processed_name),
        )

    def generate_state_chunks(
        self,
        state_name: str,
        chunk_step: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Divides a state bounding box into a grid of manageable geographic chunks (default 0.5 degrees).
        """
        step = chunk_step or self.chunk_size_deg
        if state_name not in STATE_BOUNDING_BOXES:
            raise ValueError(f"State '{state_name}' not found in bounding box registry")

        min_lat, min_lon, max_lat, max_lon = STATE_BOUNDING_BOXES[state_name]
        chunks: List[Dict[str, Any]] = []
        chunk_num = 1

        curr_lat = min_lat
        while curr_lat < max_lat:
            next_lat = min(curr_lat + step, max_lat)
            curr_lon = min_lon
            while curr_lon < max_lon:
                next_lon = min(curr_lon + step, max_lon)
                chunk_id = f"chunk_{chunk_num:04d}"
                chunks.append({
                    "chunk_id": chunk_id,
                    "index": chunk_num,
                    "bbox": (
                        round(curr_lat, 4),
                        round(curr_lon, 4),
                        round(next_lat, 4),
                        round(next_lon, 4)
                    )
                })
                chunk_num += 1
                curr_lon = next_lon
            curr_lat = next_lat

        return chunks

    def _setup_state_logger(self, state_name: str) -> logging.Logger:
        """Sets up a state-specific file logger: logs/osm_<state_slug>_YYYYMMDD.log."""
        state_slug = slugify(state_name)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_filename = f"osm_{state_slug}_{date_str}.log"
        log_path = os.path.join(self.logs_dir, log_filename)

        state_logger = logging.getLogger(f"OSMCollector_{state_slug}")
        state_logger.setLevel(logging.INFO)
        state_logger.propagate = False

        if not any(isinstance(h, logging.FileHandler) and h.baseFilename == os.path.abspath(log_path) for h in state_logger.handlers):
            handler = logging.FileHandler(log_path, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            handler.setFormatter(formatter)
            state_logger.addHandler(handler)

        return state_logger

    def run_chunk_query(
        self,
        query_template: str,
        bbox: Tuple[float, float, float, float],
        timeout: Optional[int] = None,
        counters: Optional[Dict[str, int]] = None
    ) -> Dict[str, Any]:
        """
        Builds and executes an Overpass QL query targeting node/way/relation with center tags.
        """
        query_timeout = timeout if timeout is not None else self.config.query_server_timeout_sec
        s, w, n, e = bbox
        statement = query_template.format(s=s, w=w, n=n, e=e)
        ql_query = f"""[out:json][timeout:{query_timeout}];
(
  {statement}
);
out center tags;"""

        return self.osm_source.query_overpass(ql_query, timeout=query_timeout, counters=counters)

    def _process_single_chunk(
        self,
        query_template: str,
        chunk_info: Dict[str, Any],
        field_meta: Dict[str, Any],
        state_name: str,
        state_slug: str,
        field_name: str,
        field_progress: Dict[str, Any],
        completed_chunk_ids: Set[str],
        field_records_map: Dict[str, Dict[str, Any]],
        state_logger: logging.Logger,
        chunk_dir_raw: str,
        chunk_dir_proc: str,
        counters: Dict[str, int],
        chunk_size_deg: float,
        depth: int = 0,
        parent_id: Optional[str] = None,
        total_chunks: int = 0,
        state_idx: int = 1,
        total_states: int = 50,
        field_idx: int = 1,
        total_fields: int = 13,
        session_start_ts: float = 0.0,
        chunks_done_session: int = 0,
    ) -> Tuple[str, int]:
        """
        Process a single geographic chunk with live console logging,
        response validation, ACID checkpointing, and adaptive quadtree subdivision on timeout.
        """
        cid = chunk_info["chunk_id"]
        c_idx = chunk_info["index"]
        bbox = chunk_info["bbox"]

        if cid in completed_chunk_ids:
            return "skipped", 0

        raw_chunk_path, proc_chunk_path = self._chunk_output_paths(
            chunk_dir_raw=chunk_dir_raw,
            chunk_dir_proc=chunk_dir_proc,
            field_progress=field_progress,
            chunk_id=cid,
        )

        print(
            f"[START] State={state_name} ({state_idx}/{total_states}) "
            f"Field={field_name} ({field_idx}/{total_fields}) "
            f"Chunk={cid} ({c_idx}/{total_chunks})",
            flush=True
        )

        try:
            # Mark in progress in SQLite
            self.checkpoint_manager.mark_chunk_in_progress(
                state_name=state_name,
                field_name=field_name,
                chunk_id=cid,
                bbox=bbox,
                depth=depth,
                parent_id=parent_id
            )

            raw_data = self.run_chunk_query(query_template, bbox, counters=counters)

            # Validate response
            is_valid, val_err, elem_count = validate_overpass_response(raw_data)
            if not is_valid:
                if val_err and "timed out" in val_err.lower():
                    raise OverpassTimeoutError(val_err)
                raise ValueError(f"Invalid Overpass response: {val_err}")

            elements = raw_data.get("elements", [])
            now_utc_iso = datetime.now(timezone.utc).isoformat()

            os.makedirs(chunk_dir_raw, exist_ok=True)
            with open(raw_chunk_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2)

            chunk_records: List[Dict[str, Any]] = []
            for elem in elements:
                rec = self.osm_source.extract_poi_record(
                    element=elem,
                    collected_at=now_utc_iso,
                    category_group=field_meta["category_group"],
                    target_field=field_name,
                )
                chunk_records.append(rec)
                dedupe_key = f"{rec['osm_type']}_{rec['osm_id']}"
                field_records_map[dedupe_key] = rec

            os.makedirs(chunk_dir_proc, exist_ok=True)
            with open(proc_chunk_path, "w", encoding="utf-8") as f:
                json.dump(chunk_records, f, indent=2)

            # Mark completed in SQLite ACID checkpoint manager
            self.checkpoint_manager.mark_chunk_completed(
                state_name=state_name,
                field_name=field_name,
                chunk_id=cid,
                records_count=len(chunk_records),
                raw_path=raw_chunk_path,
                proc_path=proc_chunk_path
            )

            # Mark chunk complete & clean up failed list in memory/JSON
            completed_chunk_ids.add(cid)
            if "failed_chunk_ids" in field_progress and cid in field_progress["failed_chunk_ids"]:
                field_progress["failed_chunk_ids"].remove(cid)

            field_progress["completed_chunk_ids"] = sorted(completed_chunk_ids)
            field_progress["chunks_completed"] = min(len(completed_chunk_ids), total_chunks)
            field_progress["records_collected"] = len(field_records_map)
            self._save_progress()

            completed_cnt = len(completed_chunk_ids)
            failed_cnt = len(field_progress.get("failed_chunk_ids", []))
            pending_cnt = max(0, total_chunks - completed_cnt)

            elapsed_sec = time.time() - session_start_ts if session_start_ts else 0.0
            elapsed_str = self._format_duration(elapsed_sec)
            chunks_total_session = chunks_done_session + 1
            if chunks_total_session > 0 and elapsed_sec > 0:
                avg_sec = elapsed_sec / chunks_total_session
                eta_str = self._format_duration(avg_sec * pending_cnt)
            else:
                eta_str = "calculating..."

            print(f"[PARSE] Extracted={len(chunk_records)} Unique={len(field_records_map)}", flush=True)
            print(f"[SAVE] Raw={raw_chunk_path} Processed={proc_chunk_path}", flush=True)
            print(
                f"[CHECKPOINT] Completed={completed_cnt} Failed={failed_cnt} Pending={pending_cnt} "
                f"Elapsed={elapsed_str} ETA={eta_str}",
                flush=True
            )

            state_logger.info(
                f"State: {state_name} | Field: {field_name} | Chunk: {cid} | Status: SUCCESS | "
                f"Elements: {elem_count} | Records: {len(chunk_records)} | UniqueTotal: {len(field_records_map)}"
            )

            return "completed", len(chunk_records)

        except OverpassTimeoutError as timeout_err:
            # ADAPTIVE QUADTREE SUBDIVISION: Automatically bisect dense / overloaded chunks into 4 sub-quadrants
            if self.config.enable_adaptive_subdivision and self.quadtree.can_subdivide(bbox, depth):
                print(
                    f"\n[QUADTREE] >>> Chunk {cid} encountered HTTP 504 / timeout! "
                    f"Subdividing spatial bbox at depth {depth} -> {depth + 1}... <<<",
                    flush=True
                )
                state_logger.warning(
                    f"State: {state_name} | Field: {field_name} | Chunk: {cid} timed out. "
                    f"Triggering Quadtree subdivision (depth={depth} -> {depth + 1})"
                )

                children = self.quadtree.create_child_chunks(cid, bbox, depth)
                self.checkpoint_manager.mark_chunk_split(state_name, field_name, cid, children)

                all_sub_success = True
                total_quadrant_records = 0

                for child in children:
                    child_id = child["chunk_id"]
                    child_bbox = child["bbox"]
                    child_info = {
                        "chunk_id": child_id,
                        "index": c_idx,
                        "bbox": child_bbox
                    }
                    sub_status, sub_count = self._process_single_chunk(
                        query_template=query_template,
                        chunk_info=child_info,
                        field_meta=field_meta,
                        state_name=state_name,
                        state_slug=state_slug,
                        field_name=field_name,
                        field_progress=field_progress,
                        completed_chunk_ids=completed_chunk_ids,
                        field_records_map=field_records_map,
                        state_logger=state_logger,
                        chunk_dir_raw=chunk_dir_raw,
                        chunk_dir_proc=chunk_dir_proc,
                        counters=counters,
                        chunk_size_deg=chunk_size_deg / 2.0,
                        depth=depth + 1,
                        parent_id=cid,
                        total_chunks=total_chunks,
                        state_idx=state_idx,
                        total_states=total_states,
                        field_idx=field_idx,
                        total_fields=total_fields,
                        session_start_ts=session_start_ts,
                        chunks_done_session=chunks_done_session,
                    )
                    if sub_status != "completed" and sub_status != "skipped":
                        all_sub_success = False
                    total_quadrant_records += sub_count

                if all_sub_success:
                    # Mark parent chunk completed in memory and checkpoint
                    completed_chunk_ids.add(cid)
                    if "failed_chunk_ids" in field_progress and cid in field_progress["failed_chunk_ids"]:
                        field_progress["failed_chunk_ids"].remove(cid)
                    field_progress["completed_chunk_ids"] = sorted(completed_chunk_ids)
                    field_progress["chunks_completed"] = min(len(completed_chunk_ids), total_chunks)
                    self._save_progress()
                    print(f"[QUADTREE] Completed all 4 quadrants for {cid} successfully!", flush=True)
                    return "completed", total_quadrant_records

            # Fall through if subdivision reached maximum depth or is disabled
            err_msg = str(timeout_err)
            state_logger.error(
                f"State: {state_name} | Field: {field_name} | "
                f"Chunk: {cid} | Status: FAILED | Error: {err_msg}"
            )
            self.checkpoint_manager.mark_chunk_failed(state_name, field_name, cid, err_msg)
            if cid not in field_progress.get("failed_chunk_ids", []) and cid not in completed_chunk_ids:
                field_progress.setdefault("failed_chunk_ids", []).append(cid)
            field_progress.setdefault("errors", []).append({
                "chunk_id": cid,
                "bbox": bbox,
                "error": err_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self._save_progress()

            completed_cnt = len(completed_chunk_ids)
            failed_cnt = len(field_progress.get("failed_chunk_ids", []))
            pending_cnt = max(0, total_chunks - completed_cnt - failed_cnt)

            print(f"[ERROR] Chunk {c_idx}/{total_chunks} [{cid}] -> FAILED ({err_msg})", flush=True)
            print(f"[CHECKPOINT] Completed={completed_cnt} Failed={failed_cnt} Pending={pending_cnt}", flush=True)
            return "failed", 0

        except Exception as e:
            err_msg = str(e)
            state_logger.error(
                f"State: {state_name} | Field: {field_name} | "
                f"Chunk: {cid} | Status: FAILED | Error: {err_msg}"
            )
            self.checkpoint_manager.mark_chunk_failed(state_name, field_name, cid, err_msg)
            if cid not in field_progress.get("failed_chunk_ids", []) and cid not in completed_chunk_ids:
                field_progress.setdefault("failed_chunk_ids", []).append(cid)
            field_progress.setdefault("errors", []).append({
                "chunk_id": cid,
                "bbox": bbox,
                "error": err_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self._save_progress()

            completed_cnt = len(completed_chunk_ids)
            failed_cnt = len(field_progress.get("failed_chunk_ids", []))
            pending_cnt = max(0, total_chunks - completed_cnt - failed_cnt)

            print(f"[ERROR] Chunk {c_idx}/{total_chunks} [{cid}] -> FAILED ({err_msg})", flush=True)
            print(f"[CHECKPOINT] Completed={completed_cnt} Failed={failed_cnt} Pending={pending_cnt}", flush=True)
            return "failed", 0

    def process_state(
        self,
        state_name: str,
        state_code: str,
        target_fields: Optional[List[str]] = None,
        resume: bool = True,
        retry_affected: bool = False,
        state_idx: int = 1,
        total_states: int = 50,
    ) -> Dict[str, Any]:
        """
        Collects ALL data for a state, field-by-field, chunk-by-chunk.
        """
        state_slug = slugify(state_name)
        state_logger = self._setup_state_logger(state_name)
        start_time_iso = datetime.now(timezone.utc).isoformat()
        state_start_ts = time.time()

        print("\n" + "=" * 60, flush=True)
        print(f"STATE {state_idx}/{total_states}: {state_name} ({state_code})", flush=True)
        print("=" * 60, flush=True)
        state_logger.info(f"Starting state collection for {state_name} ({state_code}) at {start_time_iso}")

        if state_name not in self.progress_data:
            self.progress_data[state_name] = {}

        chunks = self.generate_state_chunks(state_name)
        total_chunks = len(chunks)

        fields_to_run = [f for f in FIELDS_TAXONOMY if not target_fields or f["field"] in target_fields]
        state_total_records = 0
        state_fields_summary: Dict[str, int] = {}

        for field_idx, field_meta in enumerate(fields_to_run, 1):
            field_name = field_meta["field"]
            cat_group = field_meta["category_group"]
            query_template = field_meta["query_template"]

            print(f"\n------------------------------------------------------------", flush=True)
            print(f"FIELD {field_idx}/{len(fields_to_run)}: {field_name} (Group: {cat_group})", flush=True)
            print(f"------------------------------------------------------------", flush=True)
            state_logger.info(f"Starting field {field_name} ({cat_group}) for {state_name}")

            # Check for affected chunks from incorrect endpoint
            affected_chunk_ids = self.identify_affected_chunks(state_name, field_name)
            if affected_chunk_ids and (resume or retry_affected):
                self.prepare_affected_chunks_recovery(state_name, field_name)

            field_progress = self.progress_data[state_name].get(field_name, {})

            # If field already completed and no affected chunks, skip
            if resume and field_progress.get("status") == "completed" and not affected_chunk_ids:
                records_count = field_progress.get("records_collected", 0)
                state_total_records += records_count
                state_fields_summary[field_name] = records_count
                print(f"[OK] {field_name} already COMPLETED in previous run ({records_count} records). Skipping.", flush=True)
                state_logger.info(f"Field {field_name} already completed with {records_count} records. Skipping.")
                continue

            raw_field_dir = os.path.join(self.raw_base_dir, state_slug, field_name)
            proc_field_dir = os.path.join(self.processed_base_dir, state_slug, field_name)
            export_state_dir = os.path.join(self.export_base_dir, state_slug)
            for d in [raw_field_dir, proc_field_dir, export_state_dir]:
                os.makedirs(d, exist_ok=True)

            # Initialize field in Enterprise ACID Checkpoint Manager
            self.checkpoint_manager.init_field(
                state_name=state_name,
                state_code=state_code,
                field_name=field_name,
                field_group=cat_group,
                total_chunks=total_chunks,
                chunks_info=chunks
            )
            # Reconcile disk state against SQLite DB
            self.checkpoint_manager.reconcile_disk_state(
                state_name=state_name,
                field_name=field_name,
                proc_field_dir=proc_field_dir
            )
            db_completed = self.checkpoint_manager.get_completed_chunk_ids(state_name, field_name)

            completed_chunk_ids: Set[str] = set()
            if resume and field_progress.get("status") in ("in_progress", "completed"):
                json_completed = set(field_progress.get("completed_chunk_ids", []))
                merged_completed = db_completed.union(json_completed)
                # Verify that files actually exist on disk and are not 0-byte corrupted
                verified_completed = set()
                for cid in merged_completed:
                    p_path = os.path.join(proc_field_dir, f"{cid}.json")
                    if os.path.exists(p_path) and os.path.getsize(p_path) > 2:
                        verified_completed.add(cid)
                completed_chunk_ids = verified_completed
                print(
                    f"[RESUME] Resuming {field_name}: {len(completed_chunk_ids)}/{total_chunks} completed, "
                    f"{total_chunks - len(completed_chunk_ids)} pending...",
                    flush=True
                )

            field_records_map: Dict[str, Dict[str, Any]] = {}
            # Pre-load existing records from valid completed chunks for deduplication
            for cid in completed_chunk_ids:
                artifact = field_progress.get("chunk_artifacts", {}).get(cid, {})
                proc_filename = artifact.get("processed", f"{cid}.json")
                proc_chunk_path = os.path.join(proc_field_dir, proc_filename)
                if os.path.exists(proc_chunk_path):
                    try:
                        with open(proc_chunk_path, "r", encoding="utf-8") as f:
                            c_records = json.load(f)
                            for rec in c_records:
                                dedupe_key = f"{rec['osm_type']}_{rec['osm_id']}"
                                field_records_map[dedupe_key] = rec
                    except Exception as e:
                        state_logger.warning(f"Could not load pre-existing chunk {proc_chunk_path}: {e}")

            clean_failed_ids = [cid for cid in field_progress.get("failed_chunk_ids", []) if cid not in completed_chunk_ids]
            field_progress.update({
                "state": state_name,
                "state_code": state_code,
                "field_group": cat_group,
                "field": field_name,
                "status": "in_progress",
                "started_at": field_progress.get("started_at", datetime.now(timezone.utc).isoformat()),
                "completed_at": None,
                "chunks_total": total_chunks,
                "chunks_completed": min(len(completed_chunk_ids), total_chunks),
                "completed_chunk_ids": sorted(completed_chunk_ids),
                "failed_chunk_ids": clean_failed_ids,
                "records_collected": len(field_records_map),
                "errors": field_progress.get("errors", [])
            })
            self.progress_data[state_name][field_name] = field_progress
            self._save_progress()

            field_progress["stats"] = {
                "total_chunks": total_chunks,
                "successful_chunks": len(completed_chunk_ids),
                "failed_chunks": len(clean_failed_ids),
                "split_chunks": 0,
                "records_collected": len(field_records_map),
                "retry_count": 0,
                "count_429": 0,
                "count_504": 0,
                "count_timeout": 0,
                "elapsed_time": 0.0,
            }
            self._save_progress()

            field_start_ts = time.time()
            chunks_done_this_field = 0

            # Prioritize affected chunks first, then remaining pending chunks
            if affected_chunk_ids:
                affected_set = set(affected_chunk_ids)
                pending_affected = [c for c in chunks if c["chunk_id"] in affected_set and c["chunk_id"] not in completed_chunk_ids]
                pending_others = [c for c in chunks if c["chunk_id"] not in affected_set and c["chunk_id"] not in completed_chunk_ids]
                chunks_to_process = pending_affected + pending_others
            else:
                chunks_to_process = [c for c in chunks if c["chunk_id"] not in completed_chunk_ids]

            for chunk_info in chunks_to_process:
                cid = chunk_info["chunk_id"]
                if cid in completed_chunk_ids:
                    continue

                counters: Dict[str, int] = {}
                status, records_returned = self._process_single_chunk(
                    query_template=query_template,
                    chunk_info=chunk_info,
                    field_meta=field_meta,
                    state_name=state_name,
                    state_slug=state_slug,
                    field_name=field_name,
                    field_progress=field_progress,
                    completed_chunk_ids=completed_chunk_ids,
                    field_records_map=field_records_map,
                    state_logger=state_logger,
                    chunk_dir_raw=raw_field_dir,
                    chunk_dir_proc=proc_field_dir,
                    counters=counters,
                    chunk_size_deg=self.chunk_size_deg,
                    depth=0,
                    parent_id=None,
                    total_chunks=total_chunks,
                    state_idx=state_idx,
                    total_states=total_states,
                    field_idx=field_idx,
                    total_fields=len(fields_to_run),
                    session_start_ts=field_start_ts,
                    chunks_done_session=chunks_done_this_field,
                )
                if status == "completed":
                    chunks_done_this_field += 1

            # Export aggregated deduplicated records
            all_field_records = list(field_records_map.values())
            canonical_json_path = os.path.join(export_state_dir, f"{field_name}.json")
            canonical_csv_path = os.path.join(export_state_dir, f"{field_name}.csv")

            export_json_path = self._collision_safe_path(export_state_dir, f"{field_name}.json")
            export_csv_path = self._collision_safe_path(export_state_dir, f"{field_name}.csv")

            with open(export_json_path, "w", encoding="utf-8") as f:
                json.dump(all_field_records, f, indent=2)

            with open(export_csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_EXPORT_FIELDS, extrasaction="ignore")
                writer.writeheader()
                for r in all_field_records:
                    writer.writerow(r)

            # Reconcile safely if this was a recovery run
            if export_json_path != canonical_json_path:
                try:
                    with open(canonical_json_path, "r", encoding="utf-8") as f_prev:
                        prev_data = json.load(f_prev)
                    prev_count = len(prev_data) if isinstance(prev_data, list) else 0
                except Exception:
                    prev_count = 0

                # If previous canonical export had 0 records and new recovery has records:
                if prev_count == 0 and len(all_field_records) > 0:
                    orig_bak_json = os.path.join(export_state_dir, f"{field_name}.orig.json")
                    orig_bak_csv = os.path.join(export_state_dir, f"{field_name}.orig.csv")
                    if os.path.exists(canonical_json_path) and not os.path.exists(orig_bak_json):
                        shutil.copyfile(canonical_json_path, orig_bak_json)
                    if os.path.exists(canonical_csv_path) and not os.path.exists(orig_bak_csv):
                        shutil.copyfile(canonical_csv_path, orig_bak_csv)

                    shutil.copyfile(export_json_path, canonical_json_path)
                    shutil.copyfile(export_csv_path, canonical_csv_path)
                    print(
                        f"[RECONCILE] Safely updated canonical {field_name}.json with {len(all_field_records)} recovered records "
                        f"(original preserved at {orig_bak_json}, separate output at {export_json_path})",
                        flush=True
                    )

            # Check field completion
            clean_failed_list = [c for c in field_progress.get("failed_chunk_ids", []) if c not in completed_chunk_ids]
            field_progress["failed_chunk_ids"] = clean_failed_list
            failed_chunk_count = len(clean_failed_list)
            all_chunks_done = len(completed_chunk_ids) == total_chunks

            field_elapsed = round(time.time() - field_start_ts, 1)

            if all_chunks_done and failed_chunk_count == 0:
                field_progress["status"] = "completed"
                field_progress["completed_at"] = datetime.now(timezone.utc).isoformat()
                field_progress["records_collected"] = len(all_field_records)
                field_progress["chunks_completed"] = len(completed_chunk_ids)
                self._save_progress()

                state_total_records += len(all_field_records)
                state_fields_summary[field_name] = len(all_field_records)
                state_logger.info(f"Field {field_name} COMPLETED with {len(all_field_records)} deduplicated records.")
            else:
                field_progress["status"] = "in_progress"
                field_progress["completed_at"] = None
                field_progress["records_collected"] = len(all_field_records)
                field_progress["chunks_completed"] = len(completed_chunk_ids)
                self._save_progress()

                state_fields_summary[field_name] = len(all_field_records)
                state_logger.warning(f"Field {field_name} remains incomplete: {failed_chunk_count} failed, {len(completed_chunk_ids)}/{total_chunks} chunks done.")

            # Print field summary immediately upon field finish
            print(f"\n{'=' * 60}", flush=True)
            print(f"  FIELD SUMMARY: {field_name} ({state_name})", flush=True)
            print(f"{'=' * 60}", flush=True)
            print(f"  Status            : {field_progress['status'].upper()}", flush=True)
            print(f"  Total chunks      : {total_chunks}", flush=True)
            print(f"  Successful chunks : {len(completed_chunk_ids)}", flush=True)
            print(f"  Failed chunks     : {failed_chunk_count}", flush=True)
            print(f"  Pending chunks    : {max(0, total_chunks - len(completed_chunk_ids))}", flush=True)
            print(f"  Records collected : {len(all_field_records)} (deduplicated)", flush=True)
            print(f"  Export JSON       : {export_json_path}", flush=True)
            print(f"  Export CSV        : {export_csv_path}", flush=True)
            print(f"  Elapsed time      : {field_elapsed}s", flush=True)
            print(f"{'=' * 60}\n", flush=True)

        all_fields_completed = all(
            self.progress_data[state_name].get(f["field"], {}).get("status") == "completed"
            for f in fields_to_run
        )

        state_summary: Dict[str, Any] = {
            "state": state_name,
            "state_code": state_code,
            "status": "completed" if all_fields_completed else "in_progress",
            "fields": state_fields_summary,
            "total_records": state_total_records,
            "chunks_total": total_chunks,
            "completed_at": datetime.now(timezone.utc).isoformat() if all_fields_completed else None
        }

        summary_path = self._collision_safe_path(
            os.path.join(self.export_base_dir, state_slug),
            "summary.json",
        )
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(state_summary, f, indent=2)

        state_elapsed_total = round(time.time() - state_start_ts, 1)
        print("\n" + "=" * 60, flush=True)
        print(f"  STATE SUMMARY: {state_name} ({state_code}) - {state_summary['status'].upper()}", flush=True)
        print("=" * 60, flush=True)
        print(f"  Total records collected : {state_total_records}", flush=True)
        print(f"  Elapsed time            : {state_elapsed_total}s", flush=True)
        print("  Fields breakdown:", flush=True)
        for fn, cnt in state_fields_summary.items():
            print(f"    - {fn:<15}: {cnt:>7} records", flush=True)
        print(f"  Summary JSON            : {summary_path}", flush=True)
        print("=" * 60 + "\n", flush=True)

        return state_summary

    def run_collection_pipeline(
        self,
        states: Optional[List[Tuple[str, str]]] = None,
        target_fields: Optional[List[str]] = None,
        resume: bool = True,
        retry_affected: bool = False,
    ) -> Dict[str, Any]:
        """
        Runs the sequential US state collection pipeline across enabled states.
        """
        states_to_process = states or ENABLED_STATES
        pipeline_start_dt = datetime.now(timezone.utc).isoformat()
        pipeline_start_ts = time.time()
        final_summary: Dict[str, Any] = {
            "pipeline_start": pipeline_start_dt,
            "pipeline_end": None,
            "states_processed": [],
            "total_records_collected": 0,
            "states_summary": {}
        }

        fields_list_str = ", ".join(target_fields) if target_fields else "all 13 fields"

        print("\n" + "#" * 60, flush=True)
        print("  US OSM STATE-WISE BUSINESS/POI COMPLETE DATA COLLECTION  ", flush=True)
        print("#" * 60, flush=True)
        print(f"Enabled States ({len(states_to_process)}): {', '.join(s[0] for s in states_to_process)}", flush=True)
        print(f"Target Fields: {fields_list_str}", flush=True)
        print(f"Chunk Grid Size: {self.chunk_size_deg} degrees", flush=True)
        print(f"Endpoint: {self.osm_source.endpoint_url}", flush=True)
        print(f"Output Directory: {self.workspace_dir}", flush=True)
        print(f"Resume Enabled: {resume} | Retry Affected: {retry_affected}", flush=True)
        print("#" * 60 + "\n", flush=True)

        for state_idx, (state_name, state_code) in enumerate(states_to_process, 1):
            summary = self.process_state(
                state_name=state_name,
                state_code=state_code,
                target_fields=target_fields,
                resume=resume,
                retry_affected=retry_affected,
                state_idx=state_idx,
                total_states=len(states_to_process),
            )

            final_summary["states_processed"].append(state_name)
            final_summary["total_records_collected"] += summary.get("total_records", 0)
            final_summary["states_summary"][state_name] = summary

        final_summary["pipeline_end"] = datetime.now(timezone.utc).isoformat()
        final_summary["elapsed_time_sec"] = round(time.time() - pipeline_start_ts, 1)

        us_summary_path = self._collision_safe_path(
            self.export_base_dir,
            "us_osm_collection_summary.json",
        )
        with open(us_summary_path, "w", encoding="utf-8") as f:
            json.dump(final_summary, f, indent=2)

        print("\n" + "#" * 60, flush=True)
        print("                 FINAL US OSM COLLECTION SUMMARY                 ", flush=True)
        print("#" * 60, flush=True)
        for st_name, st_res in final_summary["states_summary"].items():
            st_status = st_res.get("status", "unknown").upper()
            st_recs = st_res.get("total_records", 0)
            print(f"{st_name:<16} -> {st_status:<12} -> {st_recs:>8} records", flush=True)
        print("-" * 60, flush=True)
        print(f"Total Records Collected: {final_summary['total_records_collected']}", flush=True)
        print(f"Elapsed Time          : {final_summary.get('elapsed_time_sec', 0)}s", flush=True)
        print(f"US Summary JSON        : {us_summary_path}", flush=True)
        print("#" * 60 + "\n", flush=True)

        return final_summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="US OSM Business/POI Complete Data Collection Engine")
    parser.add_argument("--states", type=str, help="Comma-separated list of states (e.g. Alabama,Florida)")
    parser.add_argument("--fields", type=str, help="Comma-separated list of fields (e.g. healthcare,finance)")
    parser.add_argument("--chunk-size", type=float, help="Override chunk grid size in degrees (default from config)")
    parser.add_argument("--workspace-dir", type=str, help="Override workspace data directory")
    parser.add_argument("--endpoint", type=str, help="Override primary Overpass API endpoint URL")
    parser.add_argument("--no-resume", action="store_true", help="Do not resume; restart extraction")
    parser.add_argument("--retry-affected", action="store_true", help="Retry failed or split chunks")

    args = parser.parse_args()

    collector = OSMStateCollector(
        workspace_dir=args.workspace_dir,
        chunk_size_deg=args.chunk_size,
        endpoint_url=args.endpoint
    )

    selected_states = None
    if args.states:
        wanted = [s.strip().lower() for s in args.states.split(",") if s.strip()]
        selected_states = [s for s in US_STATES if s[0].lower() in wanted or s[1].lower() in wanted]
        if not selected_states:
            print(f"Warning: No matching states found for '{args.states}'. Exiting.")
            sys.exit(1)

    selected_fields = None
    if args.fields:
        selected_fields = [f.strip().lower() for f in args.fields.split(",") if f.strip()]

    collector.run_collection_pipeline(
        states=selected_states,
        target_fields=selected_fields,
        resume=not args.no_resume,
        retry_affected=args.retry_affected
    )

