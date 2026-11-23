"""
Live Discovery Client Integration.
Reuses existing packages/discovery modules (DiscoveryOrchestrator, sources,
EntityResolver, QueryPlanner) for fallback and targeted missing-field enrichment.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from packages.chatbot.models import ChatIntent
from packages.discovery.models import Budget, OrgRecord, SearchIntent
from packages.discovery.orchestrator import DiscoveryOrchestrator

logger = logging.getLogger("dataextraction.chatbot.live_discovery")


STATE_PRIMARY_METROS = {
    "TX": "Dallas, TX",
    "CA": "San Francisco, CA",
    "FL": "Miami, FL",
    "NY": "New York, NY",
    "IL": "Chicago, IL",
    "WA": "Seattle, WA",
    "MA": "Boston, MA",
    "GA": "Atlanta, GA",
    "CO": "Denver, CO",
    "AZ": "Phoenix, AZ",
    "PA": "Philadelphia, PA",
    "OH": "Columbus, OH",
    "NC": "Charlotte, NC",
}


class LiveDiscoveryClient:
    def __init__(self, orchestrator: Optional[DiscoveryOrchestrator] = None) -> None:
        self.orchestrator = orchestrator or DiscoveryOrchestrator()

    async def run_discovery_stream(
        self,
        intent: ChatIntent,
        target_missing_fields: Optional[List[str]] = None,
        timeout: float = 25.0,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Runs Live Discovery as an async generator yielding structured events:
        source_status, snapshot, answer, error.
        """
        geo_dict = dict(intent.geography)
        if "country" not in geo_dict:
            geo_dict["country"] = "US"

        state_code = (geo_dict.get("state") or "").upper()
        location_str = geo_dict.get("city")
        if not location_str and state_code in STATE_PRIMARY_METROS:
            location_str = STATE_PRIMARY_METROS[state_code]
        elif not location_str:
            location_str = geo_dict.get("state") or ""

        raw_query = f"{intent.industry or ''} in {location_str}".strip() if location_str else (intent.industry or "")
        if intent.company_name:
            raw_query = f"{intent.company_name} in {location_str}".strip() if location_str else intent.company_name

        filters = {
            "max_results": intent.limit,
            "include_unverified": not intent.verification_required,
            "crawl_websites": True,
        }

        try:
            async for event in self.orchestrator.search_stream(query=raw_query or "business discovery", filters=filters, budget_seconds=timeout):
                evt_name = event.get("event")
                evt_data = event.get("data", {})
                yield {"type": evt_name, **(evt_data if isinstance(evt_data, dict) else {"payload": evt_data})}
        except Exception as exc:
            logger.warning("Live discovery execution error: %s", exc)
            yield {"type": "error", "error": str(exc)}

    async def discover_missing_fields_for_companies(
        self,
        missing_data_plan: List[Dict[str, Any]],
        timeout: float = 15.0,
    ) -> List[Dict[str, Any]]:
        """
        Targeted discovery: for companies that already exist in DB but lack specific
        fields (such as email, phone, website, or CEO), searches targeted sources.
        """
        enriched_results: List[Dict[str, Any]] = []

        # Bound concurrent discovery to top 3 items to avoid flooding sources and maintain sub-second SLA
        batch = missing_data_plan[:3]
        per_item_timeout = min(5.0, timeout)

        async def _enrich_single(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            comp_id = item["company_id"]
            comp_name = item["company_name"]
            domain = item.get("domain")
            city = item.get("city")
            state = item.get("state")
            missing = item.get("missing_fields", [])

            target_q = f"{comp_name} {city or ''} {state or ''}".strip()
            if "email" in missing:
                target_q += " contact email"
            elif "ceo" in missing:
                target_q += " CEO executive"

            filters = {
                "max_results": 2,
                "crawl_websites": bool(domain),
            }

            try:
                answer = await asyncio.wait_for(
                    self.orchestrator.search(
                        query=target_q,
                        filters=filters,
                        budget_seconds=per_item_timeout,
                    ),
                    timeout=per_item_timeout,
                )
                if answer and answer.cards:
                    best_match = answer.cards[0].model_dump() if hasattr(answer.cards[0], "model_dump") else dict(answer.cards[0])
                    return {
                        "target_company_id": comp_id,
                        "target_company_name": comp_name,
                        "discovered_data": best_match,
                    }
            except Exception as exc:
                logger.debug("Targeted discovery failed for %s: %s", comp_name, exc)
            return None

        tasks = [_enrich_single(item) for item in batch]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for g in gathered:
            if isinstance(g, dict) and g.get("target_company_id"):
                enriched_results.append(g)

        return enriched_results

        return enriched_results
