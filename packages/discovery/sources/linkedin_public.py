"""
LinkedIn Public Discovery Source Adapter.
Extracts public Schema.org ld+json organizations and profiles from public LinkedIn pages.
Non-negotiable: Public only by default, stops immediately on HTTP 999/429/401/403 or login wall.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, List, Optional

from packages.discovery.models import (
    Budget,
    FactRecord,
    OrgRecord,
    PersonRecord,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.discovery.sources.base import SourceAdapter
from packages.scrapers.linkedin.client import (
    AuthExpired,
    Blocked,
    LinkedInHttpClient,
    RateLimited,
)
from packages.scrapers.linkedin.discover import fetch_and_parse_linkedin_url

logger = logging.getLogger("discovery.source.linkedin_public")


class LinkedInPublicSource(SourceAdapter):
    def __init__(self, name: str = "linkedin_public") -> None:
        super().__init__(name=name, source_type="public_scraper", weight=1.1)

    async def _execute_search(
        self,
        intent: SearchIntent,
        budget: Budget,
    ) -> AsyncIterator[SourceResult]:
        client = LinkedInHttpClient()

        # Check circuit breaker
        if client.is_breaker_tripped():
            yield SourceResult(
                source=self.name,
                status=SourceStatus(
                    source=self.name,
                    status="blocked",
                    count=0,
                    message="LinkedIn public source circuit breaker is tripped due to previous blocks.",
                ),
            )
            return

        urls: List[str] = intent.filters.get("linkedin_urls", [])
        orgs: List[OrgRecord] = []
        people: List[PersonRecord] = []
        facts: List[FactRecord] = []

        is_blocked = False
        error_msg: Optional[str] = None

        try:
            for url in urls[:5]:
                if budget.is_expired():
                    break
                try:
                    org, person = await fetch_and_parse_linkedin_url(client, url)
                    if org:
                        orgs.append(org)
                        facts.append(
                            FactRecord(
                                entity_type="organization",
                                entity_id=org.id,
                                field="canonical_name",
                                value=org.canonical_name,
                                source="linkedin_public",
                                source_url=url,
                                confidence=0.9,
                            )
                        )
                    if person:
                        people.append(person)
                        facts.append(
                            FactRecord(
                                entity_type="person",
                                entity_id=person.id,
                                field="full_name",
                                value=person.full_name,
                                source="linkedin_public",
                                source_url=url,
                                confidence=0.9,
                            )
                        )
                except (Blocked, RateLimited, AuthExpired) as exc:
                    logger.warning("LinkedIn source encountered barrier on %s: %s. Stopping source.", url, exc)
                    is_blocked = True
                    error_msg = f"{type(exc).__name__}: {str(exc)}"
                    break
                except Exception as exc:
                    logger.debug("Error fetching LinkedIn url %s: %s", url, exc)
                    continue
        finally:
            await client.aclose()

        if is_blocked:
            status_val = "blocked"
        elif orgs or people:
            status_val = "ok"
        else:
            status_val = "empty"

        yield SourceResult(
            source=self.name,
            status=SourceStatus(
                source=self.name,
                status=status_val,
                count=len(orgs) + len(people),
                message=error_msg,
            ),
            organizations=orgs,
            people=people,
            facts=facts,
        )
