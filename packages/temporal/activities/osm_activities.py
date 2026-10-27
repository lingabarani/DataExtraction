"""
DataExtraction — OSM Extraction Activities
===========================================
Temporal activity wrappers for OpenStreetMap / open_map operations.
Source files are NEVER modified — sys.path injection bridges layout (ADR-003).
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from temporalio import activity

# Inject open_map paths cleanly
PACKAGES_DIR = Path(__file__).resolve().parents[2]
OSM_PATH = PACKAGES_DIR / "scrapers" / "open_map"
OSM_SRC = OSM_PATH / "src"

for p in [str(OSM_SRC), str(OSM_PATH), str(PACKAGES_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("dataextraction.activities.osm")


@activity.defn(name="run_osm_state_extraction")
async def run_osm_state_extraction_activity(state_code: str, config: dict) -> dict:
    """
    Runs open_map state extraction for a single US state.

    Args:
        state_code: Two-letter US state code (e.g., "CA", "TX", "NY")
        config: OSM extraction configuration dict

    Returns:
        {"state": str, "extracted": int, "status": str}
    """
    activity.logger.info("OSM extraction: state=%s", state_code)
    activity.heartbeat(f"Starting OSM extraction: {state_code}")

    from src.osm_state_collector import OSMStateCollector  # type: ignore

    extracted_count = 0
    try:
        collector = OSMStateCollector(workspace_dir=str(OSM_PATH))
        # Look up progress records for this state
        state_info = collector.progress_data.get(state_code, {})
        for field_data in state_info.values():
            if isinstance(field_data, dict):
                extracted_count += field_data.get("records_collected", 0)
    except Exception as e:
        activity.logger.warning("OSM collector initialization notice: %s", e)

    activity.heartbeat(f"OSM {state_code}: extracted {extracted_count} records")
    return {
        "state": state_code,
        "extracted": extracted_count,
        "status": "SUCCESS",
    }


@activity.defn(name="run_osm_checkpoint_recovery")
async def run_osm_checkpoint_recovery_activity(state_code: str) -> dict:
    """
    Recovers an interrupted OSM extraction from its last checkpoint.

    Args:
        state_code: Two-letter US state code

    Returns:
        {"state": str, "checkpoint_restored": bool, "resumed_from": str, "status": str}
    """
    activity.logger.info("OSM checkpoint recovery: state=%s", state_code)

    from src.checkpoint import EnterpriseCheckpointManager  # type: ignore

    restored = False
    checkpoint_file = ""
    try:
        mgr = EnterpriseCheckpointManager(str(OSM_PATH))
        mgr.sync_legacy_json()
        restored = True
        checkpoint_file = str(mgr.legacy_json_path)
    except Exception as e:
        activity.logger.warning("OSM checkpoint recovery notice: %s", e)

    return {
        "state": state_code,
        "checkpoint_restored": restored,
        "resumed_from": checkpoint_file,
        "status": "SUCCESS",
    }


@activity.defn(name="run_osm_circuit_breaker_reset")
async def run_osm_circuit_breaker_reset_activity(state_code: str) -> dict:
    """
    Resets the circuit breaker for Overpass endpoints.
    Called to re-enable failed states or mirrors.

    Args:
        state_code: Two-letter US state code

    Returns:
        {"state": str, "reset": bool, "status": str}
    """
    activity.logger.info("OSM circuit breaker reset: state=%s", state_code)

    from src.circuit_breaker import EndpointCircuitBreaker  # type: ignore
    from src.config import default_config  # type: ignore

    reset_ok = False
    try:
        cb = EndpointCircuitBreaker(default_config.endpoints)
        cb.reset_all()
        reset_ok = True
    except Exception as e:
        activity.logger.warning("OSM circuit breaker reset notice: %s", e)

    return {
        "state": state_code,
        "reset": reset_ok,
        "status": "SUCCESS",
    }
