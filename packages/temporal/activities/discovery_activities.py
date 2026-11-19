"""
Temporal Activities for Discovery Engine.
Encapsulates multi-source discovery execution and shared persistence.
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from uuid import uuid4
from temporalio import activity

from packages.discovery.models import (
    FactRecord,
    OrgRecord,
    PersonRecord,
    SearchIntent,
    SourceStatus,
)
from packages.discovery.orchestrator import DiscoveryOrchestrator
from packages.discovery.persistence import persist_discovery_search

logger = logging.getLogger("temporal.activities.discovery")


@activity.defn(name="run_discovery_search_activity")
async def run_discovery_search_activity(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query", "")
    filters = args.get("filters", {})
    budget = args.get("budget_seconds", 45.0)

    orchestrator = DiscoveryOrchestrator()
    answer = await orchestrator.search(query=query, filters=filters, budget_seconds=budget)
    return answer.model_dump()


@activity.defn(name="persist_discovery_results_activity")
async def persist_discovery_results_activity(answer_dict: Dict[str, Any]) -> Dict[str, Any]:
    query = answer_dict.get("query", "")
    cards = answer_dict.get("cards", [])
    run_id = answer_dict.get("search_id") or str(uuid4())

    orgs = []
    for c in cards:
        orgs.append(
            OrgRecord(
                id=c.get("org_id") or str(uuid4()),
                name=c.get("name", ""),
                canonical_name=c.get("name", ""),
                category=c.get("category"),
                address=c.get("address", {}),
                phone=c.get("phone"),
                website=c.get("website"),
                rating=c.get("rating"),
                review_count=c.get("review_count"),
                services=c.get("services", []),
                regulatory={
                    "cms_star_rating": c.get("cms_star_rating"),
                    "cms_ownership": c.get("cms_ownership"),
                    "nc_license_number": c.get("nc_license_number"),
                    "nc_license_status": c.get("nc_license_status"),
                },
            )
        )

    intent = SearchIntent(query=query)
    source_statuses = [SourceStatus(**st) for st in answer_dict.get("source_statuses", [])]

    ok = persist_discovery_search(
        run_id=run_id,
        query=query,
        intent=intent,
        organizations=orgs,
        people=[],
        facts=[],
        source_statuses=source_statuses,
        timings={"elapsed_ms": answer_dict.get("elapsed_ms", 0)},
    )

    return {"persisted": ok, "persisted_count": len(orgs), "query": query, "run_id": run_id}
