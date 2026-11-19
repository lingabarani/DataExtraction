"""
Unit tests for packages/discovery/orchestrator.py.
Tests:
  - Streaming SSE generator sequence (plan -> source_started -> result -> source_done -> entities_resolved -> answer -> done)
  - Inter-stage wiring: Stage A websites pass to WebsiteCrawlSource; LinkedIn URLs pass to LinkedInPublicSource
  - Per-source hard timeout enforcement via asyncio.wait_for
  - Fault tolerance: failing or hanging source does not crash orchestrator
  - Numbered citation generation and truthful summary composition
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator
import pytest

from packages.discovery.models import (
    Budget,
    FactRecord,
    OrgRecord,
    PersonRecord,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.discovery.orchestrator import DiscoveryOrchestrator
from packages.discovery.sources.base import SourceAdapter


class MockFastSource(SourceAdapter):
    def __init__(self, name: str = "mock_fast") -> None:
        super().__init__(name=name)
        self.source_type = "official_registry"
        self.weight = 1.5

    async def _execute_search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        org = OrgRecord(
            name="Alpha Home Health",
            canonical_name="Alpha Home Health",
            normalized_name="alpha home health",
            category="Home Health Agency",
            website="https://alphacare.example.com",
            address={"city": "Charlotte", "state": "NC", "postal_code": "28202"},
            regulatory={"cms_star_rating": 4.5},
            first_seen_source=self.name,
        )
        fact = FactRecord(
            entity_type="organization",
            entity_id=org.id,
            field="cms_star_rating",
            value=4.5,
            source=self.name,
            source_url="https://data.cms.gov/mock",
            confidence=0.95,
        )
        yield SourceResult(
            source=self.name,
            status=SourceStatus(name=self.name, status="ok", record_count=1),
            organizations=[org],
            facts=[fact],
        )


class MockWebSource(SourceAdapter):
    def __init__(self, name: str = "mock_web") -> None:
        super().__init__(name=name)
        self.source_type = "web_search"
        self.weight = 1.0

    async def _execute_search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        person = PersonRecord(
            name="Jane Doe",
            full_name="Jane Doe",
            title="Administrator",
            role_type="administrator",
            org_name="Alpha Home Health",
            profile_urls=["https://www.linkedin.com/in/jane-doe-care"],
            provenance="web_search",
        )
        fact = FactRecord(
            entity_type="person",
            entity_id=person.id,
            field="profile_url",
            value="https://www.linkedin.com/in/jane-doe-care",
            source=self.name,
            source_url="https://www.linkedin.com/in/jane-doe-care",
        )
        yield SourceResult(
            source=self.name,
            status=SourceStatus(name=self.name, status="ok", record_count=1),
            people=[person],
            facts=[fact],
        )


class MockHangingSource(SourceAdapter):
    def __init__(self, name: str = "mock_hanging") -> None:
        super().__init__(name=name)
        self.source_type = "scraper"
        self.weight = 1.0

    async def _execute_search(self, intent: SearchIntent, budget: Budget) -> AsyncIterator[SourceResult]:
        # Sleep far beyond per-source budget to test wait_for timeout
        await asyncio.sleep(50.0)
        yield SourceResult(
            source=self.name,
            status=SourceStatus(name=self.name, status="ok", record_count=0),
        )


@pytest.mark.anyio
async def test_orchestrator_streaming_sequence_and_citations():
    fast_src = MockFastSource()
    web_src = MockWebSource()
    orchestrator = DiscoveryOrchestrator(sources=[fast_src, web_src])

    # Disable network crawler/linkedin in unit test
    orchestrator.website_crawler = None
    orchestrator.linkedin_source = None

    query = "home care in Charlotte metro area"
    events = []

    async for event_msg in orchestrator.search_stream(query=query, budget_seconds=5.0):
        events.append(event_msg)

    event_types = [e["event"] for e in events]
    assert "plan" in event_types
    assert "source_started" in event_types
    assert "result" in event_types
    assert "source_done" in event_types
    assert "entities_resolved" in event_types
    assert "answer" in event_types
    assert "done" in event_types

    # Inspect answer payload
    answer_event = next(e for e in events if e["event"] == "answer")
    ans_data = answer_event["data"]

    assert ans_data["query"] == query
    assert ans_data["total_organizations"] == 1
    assert len(ans_data["cards"]) == 1
    assert len(ans_data["citations"]) >= 1

    # Check citation format
    top_card = ans_data["cards"][0]
    assert top_card["name"] == "Alpha Home Health"
    assert len(top_card["citation_ids"]) >= 1
    assert top_card["citation_ids"][0] == 1


@pytest.mark.anyio
async def test_orchestrator_stage_wiring():
    """Verify Stage B receives websites and LinkedIn URLs discovered in Stage A."""
    fast_src = MockFastSource()
    web_src = MockWebSource()
    orchestrator = DiscoveryOrchestrator(sources=[fast_src, web_src])

    crawled_urls = []
    linkedin_urls = []

    class MockCrawler(SourceAdapter):
        def __init__(self) -> None:
            super().__init__(name="website_crawl")

        async def _execute_search(self, intent, budget):
            crawled_urls.extend(intent.filters.get("crawl_urls", []))
            yield SourceResult(status=SourceStatus(name=self.name, status="ok", record_count=0))

    class MockLinkedIn(SourceAdapter):
        def __init__(self) -> None:
            super().__init__(name="linkedin_public")

        async def _execute_search(self, intent, budget):
            linkedin_urls.extend(intent.filters.get("linkedin_urls", []))
            yield SourceResult(status=SourceStatus(name=self.name, status="ok", record_count=0))

    orchestrator.website_crawler = MockCrawler()
    orchestrator.linkedin_source = MockLinkedIn()

    async for _ in orchestrator.search_stream("home health agency in Charlotte", budget_seconds=5.0):
        pass

    assert "https://alphacare.example.com" in crawled_urls
    assert "https://www.linkedin.com/in/jane-doe-care" in linkedin_urls


@pytest.mark.anyio
async def test_orchestrator_per_source_timeout_handling():
    """Verify a hanging source times out without preventing other sources or the answer."""
    fast_src = MockFastSource()
    hanging_src = MockHangingSource()
    orchestrator = DiscoveryOrchestrator(sources=[fast_src, hanging_src])
    orchestrator.website_crawler = None
    orchestrator.linkedin_source = None

    # Run with small budget (1.0 second per source)
    events = []
    async for event_msg in orchestrator.search_stream("elderly care in Charlotte NC", budget_seconds=1.5):
        events.append(event_msg)

    # Fast source should succeed with records
    assert any(e["event"] == "result" and e["data"]["source"] == "mock_fast" for e in events)

    # Hanging source should report timeout in source_done
    hanging_done = next(
        e for e in events
        if e["event"] == "source_done" and e["data"]["source"] == "mock_hanging"
    )
    assert hanging_done["data"]["status"] == "timeout"

    # Stream should cleanly conclude with answer and done
    assert any(e["event"] == "answer" for e in events)
    assert any(e["event"] == "done" for e in events)


@pytest.mark.anyio
async def test_internet_only_mode_skips_saved_database():
    ran = []

    class FakeLocalDB(SourceAdapter):
        def __init__(self) -> None:
            super().__init__(name="local_db")

        async def _execute_search(self, intent, budget):
            ran.append("local_db")
            yield SourceResult(status=SourceStatus(name=self.name, status="empty"))

    orchestrator = DiscoveryOrchestrator(sources=[FakeLocalDB(), MockFastSource()])
    orchestrator.website_crawler = None
    orchestrator.linkedin_source = None
    events = [e async for e in orchestrator.search_stream("home care in Charlotte NC", {"sources": "internet"},
                                                          budget_seconds=5.0)]
    started = [e["data"]["source"] for e in events if e["event"] == "source_started"]
    assert "local_db" not in started and ran == []
    assert next(e for e in events if e["event"] == "answer")["data"]["total_organizations"] == 1

    events = [e async for e in orchestrator.search_stream("home care in Charlotte NC", budget_seconds=5.0)]
    assert "local_db" in [e["data"]["source"] for e in events if e["event"] == "source_started"]


@pytest.mark.anyio
async def test_fast_mode_skips_website_crawl():
    crawled = []

    class MockCrawler(SourceAdapter):
        def __init__(self) -> None:
            super().__init__(name="website_crawl")

        async def _execute_search(self, intent, budget):
            crawled.append(1)
            yield SourceResult(status=SourceStatus(name=self.name, status="ok"))

    orchestrator = DiscoveryOrchestrator(sources=[MockFastSource()], website_crawler=MockCrawler())
    orchestrator.linkedin_source = None
    async for _ in orchestrator.search_stream("home care in Charlotte NC", {"crawl_websites": False}, budget_seconds=5.0):
        pass
    assert crawled == []
    async for _ in orchestrator.search_stream("home care in Charlotte NC", budget_seconds=5.0):
        pass
    assert crawled == [1]


@pytest.mark.anyio
async def test_snapshot_shows_merged_cards_before_the_final_answer():
    orchestrator = DiscoveryOrchestrator(sources=[MockFastSource()])
    orchestrator.website_crawler = None
    orchestrator.linkedin_source = None
    events = [e async for e in orchestrator.search_stream("home care in Charlotte NC", budget_seconds=5.0)]
    names = [e["event"] for e in events]
    assert "_tick" not in names
    assert "snapshot" in names and names.index("snapshot") < names.index("answer")
    snap = next(e for e in events if e["event"] == "snapshot")["data"]
    assert snap["preliminary"] is True and snap["total_organizations"] == 1
    assert snap["cards"][0]["name"] == "Alpha Home Health"
