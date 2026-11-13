"""
DataExtraction — Agent 1: Official Registry Ingestion Workflow
==============================================================
Queue: registry-ingestion-queue
Worker: packages.temporal.workers.worker_registry

Orchestrates official registry scrapers sequentially with:
- SEC EDGAR Fair Access compliance (10 req/s, compliant User-Agent)
- Sequential rate-limited execution
- Per-source error isolation
- Signals: pause, resume, cancel_source
- Queries: get_status
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from packages.temporal.activities.federal_activities import (
        run_cms_npi_activity,
        run_sec_edgar_activity,
        run_fdic_activity,
        run_usaspending_activity,
        run_propublica_activity,
        run_sam_gov_activity,
        enrich_gleif_lei_activity,
    )
    from packages.temporal.config import QUEUE_REGISTRY, REGISTRY_RETRY_POLICY

TASK_QUEUE = QUEUE_REGISTRY

GROUP_SOURCE_ALIASES = {
    "registry_sources",
    "federal",
    "federal_sources",
    "official_registries",
    "all",
    "*",
}

SOURCE_ALIASES = {
    "cms": "cms_npi",
    "npi": "cms_npi",
    "sec": "sec_edgar",
    "edgar": "sec_edgar",
    "fdic_ncua": "fdic",
    "fdic_banks": "fdic",
    "usa_spending": "usaspending",
    "propublica_990": "propublica",
    "sam": "sam_gov",
}


def _safe_wf_now() -> datetime:
    try:
        now = workflow.now()
        if isinstance(now, datetime):
            return now
    except Exception:
        pass
    return datetime.now(timezone.utc)


def resolve_registry_sources(
    raw_sources: Any,
    all_supported: List[str],
    configured_defaults: List[str] | None = None,
) -> List[str]:
    """
    Expands UI/API source groups (e.g. 'registry_sources') into concrete
    Agent 1 scraper keys while preserving operator exclusions.
    """
    defaults = [s for s in (configured_defaults or all_supported) if s in all_supported]
    if not defaults:
        defaults = list(all_supported)

    if raw_sources is None:
        return defaults

    if isinstance(raw_sources, dict):
        requested = [str(k).strip().lower() for k, enabled in raw_sources.items() if enabled]
    elif isinstance(raw_sources, str):
        requested = [s.strip().lower() for s in raw_sources.split(",") if s.strip()]
    else:
        requested = [str(s).strip().lower() for s in raw_sources if str(s).strip()]

    resolved: List[str] = []
    for item in requested:
        canonical = SOURCE_ALIASES.get(item, item)
        if canonical in GROUP_SOURCE_ALIASES:
            for src in defaults:
                if src not in resolved:
                    resolved.append(src)
        elif canonical in all_supported and canonical not in resolved:
            resolved.append(canonical)
    return resolved


@workflow.defn(name="Agent1RegistryWorkflow")
class Agent1RegistryWorkflow:
    """
    Agent 1 Workflow: Official Registry Intelligence.
    Ingests sovereign and regulatory registry data (SEC, CMS, FDIC, USASpending, SAM, ProPublica).
    """

    SOURCES = [
        ("cms_npi", run_cms_npi_activity),
        ("sec_edgar", run_sec_edgar_activity),
        ("fdic", run_fdic_activity),
        ("usaspending", run_usaspending_activity),
        ("propublica", run_propublica_activity),
        ("sam_gov", run_sam_gov_activity),
    ]

    def __init__(self) -> None:
        self._status: str = "INITIALIZED"
        self._current_source: str = ""
        self._paused: bool = False
        self._cancelled_sources: set[str] = set()
        self._results: Dict[str, Any] = {}

    @workflow.signal
    def pause(self) -> None:
        workflow.logger.warning("[Agent 1] Pause signal received")
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        workflow.logger.info("[Agent 1] Resume signal received")
        self._paused = False

    @workflow.signal
    def cancel_source(self, source_name: str) -> None:
        workflow.logger.warning("[Agent 1] Cancel source signal received: %s", source_name)
        self._cancelled_sources.add(source_name.lower())

    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "Agent 1 - Official Registry Intelligence",
            "workflow_id": workflow.info().workflow_id,
            "status": self._status,
            "current_source": self._current_source,
            "paused": self._paused,
            "completed": [s for s, r in self._results.items() if r.get("status") == "SUCCESS"],
            "skipped": [s for s, r in self._results.items() if r.get("status") in ("SKIPPED", "SKIPPED_UNCONFIGURED")],
            "failed": [s for s, r in self._results.items() if r.get("status") == "FAILED"],
            "total_sources": len(self.SOURCES),
            "results": self._results,
        }

    @workflow.run
    async def run(self, config: dict = None) -> dict:
        config = config or {}
        wf_start = _safe_wf_now()
        self._status = "RUNNING"
        workflow.logger.info("[Agent 1] Registry Ingestion started on queue: %s", TASK_QUEUE)

        supported_keys = [s[0] for s in self.SOURCES]
        default_sources = config.get("default_sources")
        sources_to_run = resolve_registry_sources(
            config.get("sources"),
            all_supported=supported_keys,
            configured_defaults=default_sources,
        )
        workflow.logger.info(
            "[Agent 1] Resolved registry sources (requested=%s -> resolved=%s)",
            config.get("sources"),
            sources_to_run,
        )

        exec_mode = str(config.get("execution_mode", "INCREMENTAL")).upper()
        default_mode = "full" if exec_mode == "FULL_REFRESH" else "incremental"

        for source_name, activity_fn in self.SOURCES:
            if source_name not in sources_to_run:
                continue
            if source_name in self._cancelled_sources:
                self._results[source_name] = {"status": "SKIPPED", "reason": "Cancelled by operator"}
                continue

            await workflow.wait_condition(lambda: not self._paused)
            self._current_source = source_name
            workflow.logger.info("[Agent 1] Ingesting registry source: %s", source_name)

            source_cfg = dict(config.get(source_name, {"mode": default_mode}))
            source_cfg.setdefault("mode", default_mode)
            if "data_count" in config and "limit" not in source_cfg:
                source_cfg["limit"] = config["data_count"]
            if source_name == "sec_edgar" and "sec_default_mode" in config and "mode" not in config.get(source_name, {}):
                source_cfg["mode"] = config["sec_default_mode"]
            if source_name == "fdic" and "fdic_default_source" in config and "source" not in source_cfg:
                source_cfg["source"] = config["fdic_default_source"]

            try:
                res = await workflow.execute_activity(
                    activity_fn,
                    args=[source_cfg],
                    task_queue=TASK_QUEUE,
                    start_to_close_timeout=timedelta(hours=4),
                    retry_policy=REGISTRY_RETRY_POLICY,
                )
                act_status = str((res or {}).get("status", "SUCCESS")).upper()
                if act_status in ("SKIPPED", "SKIPPED_UNCONFIGURED"):
                    self._results[source_name] = {**res, "status": act_status}
                elif act_status == "FAILED":
                    self._results[source_name] = {**res, "status": "FAILED"}
                else:
                    self._results[source_name] = {"status": "SUCCESS", **res}
            except Exception as exc:
                workflow.logger.error("[Agent 1] Registry source %s failed: %s", source_name, exc)
                self._results[source_name] = {"status": "FAILED", "error": str(exc)}

        # Optional GLEIF LEI Enrichment
        enrich_lei_records = config.get("enrich_lei_records", [])
        if enrich_lei_records:
            workflow.logger.info("[Agent 1] Executing GLEIF LEI enrichment for %d entities", len(enrich_lei_records))
            lei_results = []
            for record_payload in enrich_lei_records:
                try:
                    lei_res = await workflow.execute_activity(
                        enrich_gleif_lei_activity,
                        args=[record_payload],
                        task_queue=TASK_QUEUE,
                        start_to_close_timeout=timedelta(minutes=15),
                        retry_policy=REGISTRY_RETRY_POLICY,
                    )
                    lei_results.append(lei_res)
                except Exception as exc:
                    lei_results.append({"status": "FAILED", "error": str(exc)})
            self._results["lei_enrichment"] = lei_results

        sources_successful = len([s for s, r in self._results.items() if isinstance(r, dict) and r.get("status") == "SUCCESS"])
        sources_failed = len([s for s, r in self._results.items() if isinstance(r, dict) and r.get("status") == "FAILED"])
        sources_skipped = len([s for s, r in self._results.items() if isinstance(r, dict) and r.get("status") in ("SKIPPED", "SKIPPED_UNCONFIGURED")])

        if not sources_to_run:
            self._status = "SKIPPED"
        elif sources_successful == 0 and sources_failed > 0:
            self._status = "FAILED"
        elif sources_failed > 0:
            self._status = "COMPLETED_WITH_ERRORS"
        elif sources_successful == 0 and sources_skipped > 0:
            self._status = "SKIPPED"
        else:
            self._status = "COMPLETED"

        total_staged = sum(
            int(r.get("inserted_count", 0) or 0)
            for r in self._results.values()
            if isinstance(r, dict) and r.get("status") == "SUCCESS"
        )
        duration_seconds = round(max((_safe_wf_now() - wf_start).total_seconds(), 0.0), 2)
        return {
            "status": self._status,
            "organizations_processed": total_staged,
            "sources_requested": sources_to_run,
            "sources_successful": sources_successful,
            "sources_failed": sources_failed,
            "sources_skipped": sources_skipped,
            "duration_seconds": duration_seconds,
            "results": self._results,
        }

