"""
Discovery Engine orchestrator.

Pipeline (events are streamed as they happen):
  plan             query understanding + geography
  Stage A          local DB, CMS, state registry, Google Maps, web search run in parallel
  Stage B          organization websites found in stage A are crawled; LinkedIn public pages found by web search are
                   read; emails/phones are enriched
  Stage C          entity resolution, ranking, persistence (stable ids), answer composition

While stages A and B run, a `snapshot` event carries the merged, ranked cards received so far (at most every
SNAPSHOT_INTERVAL seconds), so results appear within about a second and fill in as slower sources answer.
Filters: `sources="internet"` skips the saved database; `crawl_websites=false` skips stage B for a faster answer.

Every source runs under its own timeout. A source that fails, times out or is blocked reports that status and the
others continue. Nothing is invented: a source without data returns zero records.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from packages.discovery.answer import AnswerComposer, SearchAnswer
from packages.discovery.models import (
    Budget,
    OrgRecord,
    SearchIntent,
    SourceStatus,
)
from packages.discovery.persistence import persist_discovery_search, save_search_answer
from packages.discovery.planner import QueryPlanner
from packages.discovery.ranking import rank_organizations
from packages.discovery.resolver import EntityResolver
from packages.discovery.sources.cms_care_compare import CMSCareCompareSource
from packages.discovery.sources.enrichment import EnrichmentSource
from packages.discovery.sources.google_maps import GoogleMapsSource
from packages.discovery.sources.linkedin_public import LinkedInPublicSource
from packages.discovery.sources.local_db import LocalDBSource
from packages.discovery.sources.state_registry import StateRegistrySource
from packages.discovery.sources.web_search import WebSearchSource
from packages.discovery.sources.website_crawl import WebsiteCrawlSource

logger = logging.getLogger("discovery.orchestrator")

STAGE_A_TIMEOUT = 20.0
STAGE_B_TIMEOUT = 20.0
MAX_RESULTS_LIMIT = 1000
SNAPSHOT_INTERVAL = 0.6      # seconds between live "snapshot" events (merged cards so far)
SNAPSHOT_MAX_CARDS = 200     # cards per snapshot; the final answer carries up to max_results
MAX_CRAWL_SITES = 20
_TICK = "_tick"              # internal idle event, never sent to clients
MAX_LINKEDIN_URLS = 5
_NOT_CRAWLABLE = ("linkedin.com", "google.com", "yelp.com", "facebook.com", "instagram.com", "twitter.com", "x.com",
                  "youtube.com", "caring.com", "seniorly.com", "agingcare.com", "aplaceformom.com")


def _compact_org(o: OrgRecord) -> Dict[str, Any]:
    return {
        "id": o.id, "name": o.canonical_name or o.name, "category": o.category,
        "city": (o.address or {}).get("city"), "state": (o.address or {}).get("state"),
        "phone": o.phones[0].number if o.phones else None, "website": o.website,
    }


class DiscoveryOrchestrator:
    def __init__(
        self,
        sources: Optional[List[Any]] = None,
        website_crawler: Any = None,
        linkedin_source: Any = None,
    ) -> None:
        self.planner = QueryPlanner()
        self.resolver = EntityResolver()
        self.composer = AnswerComposer()
        self.enricher = EnrichmentSource()
        self.stage_a_sources: List[Any] = sources if sources is not None else [
            LocalDBSource(),
            CMSCareCompareSource(),
            StateRegistrySource(),
            GoogleMapsSource(),
            WebSearchSource(),
        ]
        self.website_crawler = website_crawler or WebsiteCrawlSource()
        self.linkedin_source = linkedin_source or LinkedInPublicSource()

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    async def _drain(tasks: List["asyncio.Task[None]"], queue: "asyncio.Queue[Dict[str, Any]]") -> AsyncIterator[Dict[str, Any]]:
        """Yield queued events until every task is finished and the queue is empty (idle periods yield a tick)."""
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), timeout=0.1)
                continue
            except asyncio.TimeoutError:
                pass
            if all(t.done() for t in tasks) and queue.empty():
                return
            yield {"event": _TICK}

    async def _snapshot(self, intent: SearchIntent, acc: Dict[str, List[Any]], started: float, max_results: int,
                        include_unverified: bool) -> Dict[str, Any]:
        """Merged, ranked cards from everything received so far (no citations; ids are not final yet)."""
        orgs, people, statuses = list(acc["orgs"]), list(acc["people"]), list(acc["statuses"])
        elapsed_ms = int((time.monotonic() - started) * 1000)

        def build() -> Dict[str, Any]:
            r_orgs, r_people, _ = self.resolver.resolve(orgs, people, [], include_unverified=include_unverified)
            ranked = rank_organizations(r_orgs, intent)
            ans = self.composer.compose(intent, ranked, r_people, [], statuses, elapsed_ms,
                                        max_results=min(max_results, SNAPSHOT_MAX_CARDS))
            return {"total_organizations": ans.total_organizations, "total_people": ans.total_people,
                    "cards": [c.model_dump() for c in ans.cards] if ranked else [], "elapsed_ms": elapsed_ms,
                    "sources_done": len(statuses), "preliminary": True}

        return await asyncio.to_thread(build)

    async def _run_adapter(
        self,
        adapter: Any,
        intent: SearchIntent,
        budget: Budget,
        queue: "asyncio.Queue[Dict[str, Any]]",
        acc: Dict[str, List[Any]],
        timeout: float,
    ) -> None:
        src_name = getattr(adapter, "name", adapter.__class__.__name__)
        started = time.monotonic()
        await queue.put({"event": "source_started", "data": {"source": src_name}})
        n_orgs = n_people = 0
        final_status: Optional[SourceStatus] = None
        deadline = started + min(timeout, max(1.0, budget.remaining()))
        gen = adapter.search(intent, budget)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                try:
                    res = await asyncio.wait_for(gen.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    break
                batch = res.organizations or res.orgs
                if batch:
                    acc["orgs"].extend(batch)
                    n_orgs += len(batch)
                if res.people:
                    acc["people"].extend(res.people)
                    n_people += len(res.people)
                if res.facts:
                    acc["facts"].extend(res.facts)
                if batch or res.people:
                    await queue.put({"event": "result", "data": {
                        "source": src_name, "organizations": len(batch or []), "people": len(res.people or []),
                        "preview": [_compact_org(o) for o in (batch or [])[:20]]}})
                if res.status:
                    final_status = res.status
        except asyncio.TimeoutError:
            final_status = SourceStatus(name=src_name, status="timeout", count=n_orgs + n_people,
                                        message=f"Exceeded {int(timeout)}s time budget; partial results kept")
        except Exception as exc:
            logger.warning("Source %s failed: %s", src_name, exc, exc_info=True)
            final_status = SourceStatus(name=src_name, status="unavailable", count=n_orgs + n_people,
                                        message=f"{type(exc).__name__}: {exc}"[:300])
        finally:
            try:
                await gen.aclose()
            except Exception:
                pass

        if final_status is None:
            final_status = SourceStatus(name=src_name, status="ok" if (n_orgs or n_people) else "empty",
                                        count=n_orgs + n_people)
        if final_status.status in ("empty", "ok") and (n_orgs or n_people):
            final_status.status = "ok"
        final_status.name = final_status.source = src_name
        final_status.elapsed_ms = int((time.monotonic() - started) * 1000)
        if n_orgs or n_people:
            # count = organizations returned by this source (people-only sources report people)
            final_status.count = final_status.record_count = n_orgs if n_orgs else n_people
        acc["statuses"].append(final_status)
        await queue.put({"event": "source_done", "data": final_status.model_dump()})

    async def _run_stage(
        self,
        adapters: List[Any],
        intents: List[SearchIntent],
        budget: Budget,
        acc: Dict[str, List[Any]],
        timeout: float,
    ) -> AsyncIterator[Dict[str, Any]]:
        queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        tasks = [asyncio.create_task(self._run_adapter(a, i, budget, queue, acc, timeout))
                 for a, i in zip(adapters, intents)]
        async for evt in self._drain(tasks, queue):
            yield evt
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _with_snapshots(
        self,
        events: AsyncIterator[Dict[str, Any]],
        intent: SearchIntent,
        acc: Dict[str, List[Any]],
        started: float,
        max_results: int,
        include_unverified: bool,
        state: Dict[str, Any],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Forward stage events and add a merged `snapshot` at most every SNAPSHOT_INTERVAL seconds."""
        async for evt in events:
            name = evt.get("event")
            if name != _TICK:
                yield evt
            if name == "result":
                state["dirty"] = True
            if state["dirty"] and acc["orgs"] and time.monotonic() - state["last"] >= SNAPSHOT_INTERVAL:
                state["dirty"] = False
                yield {"event": "snapshot",
                       "data": await self._snapshot(intent, acc, started, max_results, include_unverified)}
                state["last"] = time.monotonic()

    # ── main flow ────────────────────────────────────────────────────────────
    async def search_stream(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        budget_seconds: float = 45.0,
        search_id: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        run_id = search_id or str(uuid4())
        filters = dict(filters or {})
        started = time.monotonic()
        budget = Budget(total_seconds=budget_seconds, deadline=started + budget_seconds)
        max_results = max(1, min(int(filters.get("max_results", 50) or 50), MAX_RESULTS_LIMIT))
        filters["max_results"] = max_results
        include_unverified = bool(filters.get("include_unverified", False))
        internet_only = filters.get("sources") == "internet"
        crawl_websites = filters.get("crawl_websites", True) is not False

        # 1. Plan
        intent = await self.planner.plan(query, filters)
        yield {"event": "plan", "data": {"search_id": run_id, "intent": intent.model_dump()}}

        geo = intent.geography or {}
        if geo.get("needs_location"):
            message = geo.get("error") or ("Add where to search, for example: 'home care in Chennai' or "
                                           "'plumbers in Austin, TX'. Any city, area, ZIP or PIN code in the world works.")
            answer = self.composer.compose(intent, [], [], [], [], 0)
            answer.needs_location = True
            answer.message = message
            yield {"event": "needs_location", "data": {"message": message}}
            yield {"event": "answer", "data": answer.model_dump()}
            yield {"event": "done", "data": {"search_id": run_id, "elapsed_ms": 0, "status": "needs_location"}}
            return

        acc: Dict[str, List[Any]] = {"orgs": [], "people": [], "facts": [], "statuses": []}
        snap_state: Dict[str, Any] = {"dirty": False, "last": 0.0}

        def live(events: AsyncIterator[Dict[str, Any]]) -> AsyncIterator[Dict[str, Any]]:
            return self._with_snapshots(events, intent, acc, started, max_results, include_unverified, snap_state)

        # 2. Stage A ("internet" mode skips the saved database)
        stage_a = [s for s in self.stage_a_sources
                   if not (internet_only and getattr(s, "name", "") == "local_db")]
        async for evt in live(self._run_stage(stage_a, [intent] * len(stage_a), budget, acc, STAGE_A_TIMEOUT)):
            yield evt

        # 3. Stage B: crawl organization websites, read LinkedIn public pages found by search
        # Stage B runs for whichever of the two sources is configured (set an attribute to None to disable it) and is
        # skipped when the caller asked for a fast search without website details (crawl_websites=false).
        if crawl_websites and (self.website_crawler or self.linkedin_source) and not budget.is_expired():
            crawl_targets: List[Dict[str, str]] = []
            seen_sites = set()
            for o in sorted(acc["orgs"], key=lambda x: -len(x.sources)):
                site = o.website
                if site and not any(d in site for d in _NOT_CRAWLABLE) and site not in seen_sites:
                    seen_sites.add(site)
                    crawl_targets.append({"url": site, "org_id": o.id, "name": o.canonical_name or o.name})
                if len(crawl_targets) >= MAX_CRAWL_SITES:
                    break
            li_urls: List[str] = []
            for o in acc["orgs"]:
                u = (o.social or {}).get("linkedin")
                if u and u not in li_urls:
                    li_urls.append(u)
            for p in acc["people"]:
                li_urls.extend(u for u in p.profile_urls if "linkedin.com" in u and u not in li_urls)

            stage_b: List[Any] = []
            stage_b_intents: List[SearchIntent] = []
            if self.website_crawler and crawl_targets and budget.remaining() > 3.0:
                ci = intent.model_copy(deep=True)
                ci.filters["crawl_targets"] = crawl_targets
                ci.filters["crawl_urls"] = [t["url"] for t in crawl_targets]
                stage_b.append(self.website_crawler)
                stage_b_intents.append(ci)
            if self.linkedin_source and li_urls and budget.remaining() > 3.0:
                li = intent.model_copy(deep=True)
                li.filters["linkedin_urls"] = li_urls[:MAX_LINKEDIN_URLS]
                stage_b.append(self.linkedin_source)
                stage_b_intents.append(li)
            if stage_b:
                async for evt in live(self._run_stage(stage_b, stage_b_intents, budget, acc, STAGE_B_TIMEOUT)):
                    yield evt

            if acc["people"] and acc["orgs"] and budget.remaining() > 2.0:
                ei = intent.model_copy(deep=True)
                ei.filters["people"] = acc["people"]
                ei.filters["organizations"] = acc["orgs"]
                try:
                    async for enrich_res in self.enricher.search(ei, budget):
                        acc["people"].extend(enrich_res.people)
                        acc["facts"].extend(enrich_res.facts)
                        if enrich_res.status:
                            acc["statuses"].append(enrich_res.status)
                            yield {"event": "source_done", "data": enrich_res.status.model_dump()}
                except Exception as exc:
                    logger.debug("Enrichment skipped: %s", exc)

        # Latest merged view before the (slower) save step, so the page is complete as early as possible
        if snap_state["dirty"] and acc["orgs"]:
            yield {"event": "snapshot",
                   "data": await self._snapshot(intent, acc, started, max_results, include_unverified)}

        # 4. Resolve + rank
        resolved_orgs, resolved_people, final_facts = self.resolver.resolve(
            acc["orgs"], acc["people"], acc["facts"], include_unverified=include_unverified,
        )
        ranked = rank_organizations(resolved_orgs, intent)
        yield {"event": "entities_resolved",
               "data": {"organization_count": len(ranked), "people_count": len(resolved_people)}}

        # 5. Persist with stable ids (off the event loop), then expose the stored ids
        elapsed_ms = int((time.monotonic() - started) * 1000)
        persisted = await asyncio.to_thread(
            persist_discovery_search, run_id, query, intent, ranked, resolved_people, final_facts,
            acc["statuses"], {"elapsed_ms": elapsed_ms, "budget_seconds": budget_seconds}, requested_by,
        )
        if persisted.ok:
            for o in ranked:
                o.id = persisted.org_ids.get(o.id, o.id)
            for p in resolved_people:
                p.id = persisted.person_ids.get(p.id, p.id)
                if p.org_id:
                    p.org_id = persisted.org_ids.get(p.org_id, p.org_id)
            for f in final_facts:
                mapping = persisted.org_ids if f.entity_type == "organization" else persisted.person_ids
                f.entity_id = mapping.get(f.entity_id, f.entity_id)
            # Two results that map to the same stored row are one organization: merge them, never show it twice
            unique: Dict[str, OrgRecord] = {}
            for o in ranked:
                if o.id in unique:
                    self.resolver._merge_organization(unique[o.id], o)
                    for p in o.people:
                        if not any(x.id == p.id for x in unique[o.id].people):
                            unique[o.id].people.append(p)
                else:
                    unique[o.id] = o
            ranked = list(unique.values())
        else:
            logger.warning("Search %s was not persisted: %s", run_id, persisted.error)

        # 6. Answer
        answer = self.composer.compose(intent, ranked, resolved_people, final_facts, acc["statuses"],
                                       int((time.monotonic() - started) * 1000), max_results=max_results)
        if not persisted.ok:
            answer.message = "Results could not be saved to the database; details pages are unavailable for this search."
        payload = answer.model_dump()
        if persisted.ok:
            await asyncio.to_thread(save_search_answer, run_id, payload)

        yield {"event": "answer", "data": payload}
        yield {"event": "done", "data": {"search_id": run_id, "elapsed_ms": answer.elapsed_ms, "status": "completed",
                                         "persisted": persisted.ok}}

    async def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        budget_seconds: float = 45.0,
        search_id: Optional[str] = None,
    ) -> SearchAnswer:
        """One-shot search returning the final SearchAnswer."""
        final: Optional[SearchAnswer] = None
        async for msg in self.search_stream(query, filters, budget_seconds, search_id):
            if msg["event"] == "answer":
                final = SearchAnswer(**msg["data"])
        if final is None:
            intent = await self.planner.plan(query, filters)
            return self.composer.compose(intent, [], [], [], [], 0)
        return final
