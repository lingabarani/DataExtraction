"""
DataExtraction — Agent 2: Deep Place Extraction Workflow
========================================================
Collects details, services, reviews, contacts and people for places already
discovered by the Google Maps collector. Runs in batches so each activity stays short,
and stops early when Google serves a CAPTCHA/consent wall (no bypass attempts).
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.place_deep_activities import run_place_deep_extraction_activity

PLACE_DEEP_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    maximum_attempts=2,
)


@workflow.defn(name="PlaceDeepExtractionWorkflow")
class PlaceDeepExtractionWorkflow:
    """
    Input config:
      place_ids: [...]          explicit list, OR
      region / category:        pick stale or never-scraped places
      max_places: 100           total cap for this run
      batch_size: 25            places per activity call
      with_llm: true, max_reviews: 500
    """

    def __init__(self) -> None:
        self._status = "INIT"
        self._totals = {"places": 0, "reviews": 0, "contacts": 0, "people": 0, "blocked": 0}

    @workflow.query
    def get_status(self) -> dict:
        return {"status": self._status, **self._totals}

    @workflow.run
    async def run(self, config: dict) -> dict:
        config = config or {}
        batch_size = max(1, min(int(config.get("batch_size", 25)), 100))
        max_places = max(1, min(int(config.get("max_places", 100)), 2000))
        run_base = workflow.info().workflow_id
        explicit = list(config.get("place_ids") or [])
        results = []
        status = "complete"

        self._status = "RUNNING"
        processed = 0
        batch_no = 0
        while processed < max_places:
            batch_no += 1
            req = {k: v for k, v in config.items() if k not in ("place_ids", "batch_size", "max_places")}
            req["limit"] = min(batch_size, max_places - processed)
            req["run_id"] = f"{run_base}-b{batch_no}"
            if explicit:
                req["place_ids"] = explicit[processed:processed + req["limit"]]
                if not req["place_ids"]:
                    break

            res = await workflow.execute_activity(
                run_place_deep_extraction_activity,
                args=[req],
                start_to_close_timeout=timedelta(hours=3),
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=PLACE_DEEP_RETRY,
            )
            results.append({k: res.get(k) for k in ("run_id", "status", "places_done", "reviews_saved")})
            done = int(res.get("places_done", 0))
            self._totals["places"] += done
            self._totals["reviews"] += int(res.get("reviews_saved", 0))
            self._totals["contacts"] += int(res.get("contacts_saved", 0))
            self._totals["people"] += int(res.get("people_saved", 0))
            self._totals["blocked"] += int(res.get("places_blocked", 0))

            if res.get("status") == "blocked":
                status = "blocked"
                break
            if res.get("status") == "partial":
                status = "partial"
            requested = int(res.get("places_requested", 0))
            processed += max(requested, 1) if explicit else requested
            # Nothing left to pick (filter mode) or short batch: finished.
            if requested < req["limit"]:
                break

        self._status = status.upper()
        return {"status": status, "batches": results, **self._totals}
