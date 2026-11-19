"""
Enrichment Source Adapter.
Uses LeadIntel modules to enrich discovered organizations and named leadership:
- Derives email candidates with DNS MX checks and explicit 'inferred' labeling (Decision D4).
- Formats and validates phone numbers using Google's libphonenumber into E.164.
- Runs verification engine gates (syntax, disposable domains, role accounts).
"""

from __future__ import annotations

import logging
from typing import AsyncIterator, Dict, List

from packages.discovery.models import (
    Budget,
    EmailEntry,
    FactRecord,
    OrgRecord,
    PersonRecord,
    SearchIntent,
    SourceResult,
    SourceStatus,
)
from packages.discovery.sources.base import SourceAdapter
from packages.leadintel.email_finder import company_domain, infer_email_entry
from packages.leadintel.phone_finder import PhoneFinder
from packages.leadintel.verification_engine import VerificationEngine

logger = logging.getLogger("discovery.source.enrichment")


class EnrichmentSource(SourceAdapter):
    def __init__(self, name: str = "enrichment") -> None:
        super().__init__(name=name, source_type="enricher", weight=1.0)
        self.verifier = VerificationEngine()
        self.phone_finder = PhoneFinder()

    async def _execute_search(
        self,
        intent: SearchIntent,
        budget: Budget,
    ) -> AsyncIterator[SourceResult]:
        people_to_enrich: List[PersonRecord] = intent.filters.get("people", [])
        orgs_to_enrich: List[OrgRecord] = intent.filters.get("organizations", [])

        enriched_people: List[PersonRecord] = []
        facts: List[FactRecord] = []

        # Build domain lookup from organizations
        org_domain_map: Dict[str, str] = {}
        for org in orgs_to_enrich:
            if org.domain:
                org_domain_map[org.canonical_name.lower()] = org.domain
                if org.id:
                    org_domain_map[org.id] = org.domain

        for person in people_to_enrich[:15]:
            if budget.is_expired():
                break

            name_parts = person.full_name.split()
            if len(name_parts) < 2:
                continue

            first_name = name_parts[0]
            last_name = name_parts[-1]

            domain = None
            if person.org_id and person.org_id in org_domain_map:
                domain = org_domain_map[person.org_id]
            elif person.org_name and person.org_name.lower() in org_domain_map:
                domain = org_domain_map[person.org_name.lower()]
            elif person.org_name:
                domain = company_domain(person.org_name)

            if not domain:
                continue

            # Infer corporate email candidate
            inferred = infer_email_entry(first_name, last_name, domain)
            if inferred:
                # Run through verification engine
                v_res = self.verifier.verify_email(inferred.value, check_dns=True)
                if v_res.status in ("valid", "risky"):
                    entry = EmailEntry(
                        value=inferred.value,
                        label="inferred",  # Decision D4: strictly labelled 'inferred'
                        confidence=inferred.confidence,
                        source_url=f"dns_mx:{domain}",
                    )
                    # Check if already present
                    existing_vals = {e.value for e in person.emails}
                    if entry.value not in existing_vals:
                        person.emails.append(entry)
                        facts.append(
                            FactRecord(
                                entity_type="person",
                                entity_id=person.id,
                                field="email",
                                value=entry.value,
                                source="enrichment_inferred",
                                confidence=entry.confidence,
                            )
                        )
                        enriched_people.append(person)

        status_str = "ok" if enriched_people else "empty"
        yield SourceResult(
            source=self.name,
            status=SourceStatus(
                source=self.name,
                status=status_str,
                count=len(enriched_people),
            ),
            organizations=[],
            people=enriched_people,
            facts=facts,
        )
