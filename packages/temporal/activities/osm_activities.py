"""
DataExtraction — OSM Extraction Activities
===========================================
Temporal activity wrappers for OpenStreetMap / openmap_engine operations.
Source files are NEVER modified — sys.path injection used (ADR-003).
"""

import logging
import sys
from pathlib import Path

from temporalio import activity

# Inject openmap_engine path
OSM_PATH = Path(__file__).resolve().parents[3] / "scrapers" / "open_map"
if str(OSM_PATH.parent) not in sys.path:
    sys.path.insert(0, str(OSM_PATH.parent))

logger = logging.getLogger("dataextraction.activities.osm")


@activity.defn(name="run_osm_state_extraction")
async def run_osm_state_extraction_activity(state_code: str, config: dict) -> dict:
    """
    Runs openmap_engine quadtree extraction for a single US state.

    Args:
        state_code: Two-letter US state code (e.g., "CA", "TX", "NY")
        config: OSM extraction configuration dict

    Returns:
        {"state": str, "extracted": int, "status": str}
    """
    activity.logger.info("OSM extraction: state=%s", state_code)
    activity.heartbeat(f"Starting OSM extraction: {state_code}")

    from open_map import quadtree  # type: ignore

    result = quadtree.extract_state(
        state=state_code,
        taxonomy=config.get("taxonomy", "default"),
        checkpoint_enabled=config.get("checkpoint_enabled", True),
    )
    activity.heartbeat(f"OSM {state_code}: extracted {result.count} records")
    return {
        "state": state_code,
        "extracted": result.count,
        "status": "SUCCESS",
    }


@activity.defn(name="run_osm_checkpoint_recovery")
async def run_osm_checkpoint_recovery_activity(state_code: str) -> dict:
    """
    Recovers an interrupted OSM extraction from its last checkpoint.

    Args:
        state_code: Two-letter US state code

    Returns:
        {"state": str, "checkpoint_restored": bool, "resumed_from": str}
    """
    activity.logger.info("OSM checkpoint recovery: state=%s", state_code)

    from open_map import checkpoint  # type: ignore

    result = checkpoint.restore(state=state_code)
    return {
        "state": state_code,
        "checkpoint_restored": result.restored,
        "resumed_from": str(result.checkpoint_path),
        "status": "SUCCESS",
    }


@activity.defn(name="run_osm_circuit_breaker_reset")
async def run_osm_circuit_breaker_reset_activity(state_code: str) -> dict:
    """
    Resets the circuit breaker for a state that previously tripped due to API errors.
    Called by DLQReplayWorkflow to re-enable failed states.

    Args:
        state_code: Two-letter US state code

    Returns:
        {"state": str, "reset": bool, "status": str}
    """
    activity.logger.info("OSM circuit breaker reset: state=%s", state_code)

    from open_map import circuit_breaker  # type: ignore

    result = circuit_breaker.reset(state=state_code)
    return {
        "state": state_code,
        "reset": result.reset,
        "status": "SUCCESS",
    }
