"""
DataExtraction — Deep Place Extraction Activity
===============================================
Thin Temporal wrapper around packages.scrapers.google_maps.deep_runner.
Heartbeats once per place so long review pagination is never mistaken for a hang.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from temporalio import activity

_PACKAGES_DIR = Path(__file__).resolve().parents[2]
_GMAPS_SRC = _PACKAGES_DIR / "scrapers" / "google_maps" / "src"
if str(_GMAPS_SRC) not in sys.path:
    sys.path.insert(0, str(_GMAPS_SRC))

logger = logging.getLogger("dataextraction.activities.place_deep")


def _heartbeat(payload: Dict[str, Any]) -> None:
    try:
        activity.heartbeat(payload)
    except Exception:
        pass


@activity.defn(name="run_place_deep_extraction")
async def run_place_deep_extraction_activity(request: dict) -> dict:
    """
    request: {place_ids?: [...], region?: "US-CA", category?: "restaurant", limit: 25,
              with_llm: true, max_reviews: 500, run_id?: str, dry_run?: bool}
    Returns the summary from run_deep_extraction().
    """
    from packages.scrapers.google_maps.deep_runner import run_deep_extraction
    summary = await run_deep_extraction(request, heartbeat=_heartbeat)
    logger.info("Deep extraction %s: status=%s places=%d reviews=%d",
                summary.get("run_id"), summary.get("status"), summary.get("places_done", 0),
                summary.get("reviews_saved", 0))
    return summary
