"""
Answer Composer & Citation Engine for Discovery Engine.
Transforms resolved entities and facts into structured presentation cards and
an executive synthesis with strict numbered citations and truthful source breakdown.
Never mentions CMS, licensing, or Medicare ratings unless actually present in results.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from packages.discovery.models import (
    FactRecord,
    OrgRecord,
    PersonRecord,
    SearchIntent,
    SourceStatus,
)

logger = logging.getLogger("discovery.answer")


class CitationItem(BaseModel):
    id: int
    source: str
    url: Optional[str] = None
    entity_name: str
    fact_description: str


def format_phone(number: Optional[str], country: Optional[str] = "US") -> Optional[str]:
    """Display US numbers as (704) 555-0100; numbers from other countries are shown as published."""
    if not number:
        return None
    if (country or "US").upper() != "US":
        return number
    digits = re.sub(r"\D", "", number)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return number


class AnswerCard(BaseModel):
    org_id: str
    name: str
    category: Optional[str] = None
    address: Dict[str, Any] = Field(default_factory=dict)
    phone: Optional[str] = None
    phones: List[str] = Field(default_factory=list)
    website: Optional[str] = None
    hours: List[Dict[str, Any]] = Field(default_factory=list)
    social: Dict[str, Any] = Field(default_factory=dict)
    source_links: List[Dict[str, str]] = Field(default_factory=list)
    rating: Optional[float] = None
    review_count: Optional[int] = None
    services: List[str] = Field(default_factory=list)
    cms_star_rating: Optional[float] = None
    cms_ownership: Optional[str] = None
    nc_license_number: Optional[str] = None
    nc_license_status: Optional[str] = None
    named_people: List[Dict[str, Any]] = Field(default_factory=list)
    emails: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    citation_ids: List[int] = Field(default_factory=list)


class SearchAnswer(BaseModel):
    query: str
    total_organizations: int
    total_people: int
    summary_markdown: str
    source_breakdown: Dict[str, int] = Field(default_factory=dict)
    shown_organizations: int = 0
    needs_location: bool = False
    message: Optional[str] = None
    geography: Dict[str, Any] = Field(default_factory=dict)
    cards: List[AnswerCard] = Field(default_factory=list)
    citations: List[CitationItem] = Field(default_factory=list)
    source_statuses: List[SourceStatus] = Field(default_factory=list)
    elapsed_ms: int = 0


class AnswerComposer:
    def compose(
        self,
        intent: SearchIntent,
        orgs: List[OrgRecord],
        people: List[PersonRecord],
        facts: List[FactRecord],
        source_statuses: List[SourceStatus],
        elapsed_ms: int = 0,
        max_results: int = 50,
    ) -> SearchAnswer:
        """Compose presentation cards and cited synthesis."""
        citations: List[CitationItem] = []
        citation_counter = 1

        # Citations only for entities that appear in the returned cards (orgs shown + their people)
        shown_orgs = orgs[:max(1, max_results)]
        shown_ids = {o.id for o in shown_orgs} | {p.id for o in shown_orgs for p in o.people}
        fact_citation_map: Dict[str, int] = {}
        for fact in facts:
            if fact.entity_id not in shown_ids:
                continue
            fact_key = f"{fact.entity_id}:{fact.field}"
            if fact_key not in fact_citation_map:
                cit_id = citation_counter
                citation_counter += 1
                fact_citation_map[fact_key] = cit_id

                ent_name = fact.entity_id
                for o in orgs:
                    if o.id == fact.entity_id:
                        ent_name = o.canonical_name or o.name
                        break
                for p in people:
                    if p.id == fact.entity_id:
                        ent_name = p.full_name or p.name
                        break

                citations.append(
                    CitationItem(
                        id=cit_id,
                        source=fact.source,
                        url=fact.source_url,
                        entity_name=ent_name,
                        fact_description=f"{fact.field}: {str(fact.value)[:60]}",
                    )
                )

        # Source breakdown counting
        source_breakdown: Dict[str, int] = {}
        for st in source_statuses:
            src_name = st.name or st.source
            if src_name == "enrichment":
                continue  # adds email candidates to people, not organizations
            if st.record_count or st.count:
                source_breakdown[src_name] = st.record_count or st.count

        # Build cards
        cards: List[AnswerCard] = []
        for org in shown_orgs:
            country = (org.address or {}).get("country") or "US"
            phone_val = format_phone(org.phones[0].number, country) if org.phones else None
            reg = org.regulatory or org.metadata or {}
            cms_rating = reg.get("star_rating") or reg.get("cms_star_rating")
            cms_owner = reg.get("ownership_type") or reg.get("cms_ownership")
            nc_lic = reg.get("license_number") or reg.get("nc_license_number")
            nc_stat = reg.get("license_status") or reg.get("nc_license_status")

            card_people = []
            for p in org.people:
                if not (p.full_name or p.name):
                    continue
                p_emails = [{"value": e.value, "label": e.label, "confidence": e.confidence} for e in p.emails]
                card_people.append({
                    "name": p.full_name or p.name,
                    "title": p.title,
                    "role_type": p.role_type,
                    "emails": p_emails,
                    "phones": [ph.number if hasattr(ph, "number") else str(ph) for ph in p.phones],
                    "profile_urls": p.profile_urls,
                })

            org_emails = [{"value": e.value, "label": e.label, "confidence": e.confidence} for e in org.emails]
            org_sources = list(dict.fromkeys(
                s.get("source", "unknown") if isinstance(s, dict) else str(s)
                for s in org.sources
            ))
            # "discovery" is the model's placeholder default, not a real source
            if org.first_seen_source and org.first_seen_source != "discovery" and org.first_seen_source not in org_sources:
                org_sources.append(org.first_seen_source)

            # Citations for this org
            org_cit_ids = []
            for field in ("cms_certification", "cms_star_rating", "nc_license", "listing", "rating", "website",
                          "stored_record", "canonical_name", "cms_certification_number", "license_number"):
                f_key = f"{org.id}:{field}"
                if f_key in fact_citation_map:
                    org_cit_ids.append(fact_citation_map[f_key])

            cards.append(
                AnswerCard(
                    org_id=org.id,
                    name=org.canonical_name or org.name,
                    category=org.category,
                    address=org.address,
                    phone=phone_val,
                    phones=[format_phone(p.number, country) or p.number for p in org.phones],
                    website=org.website,
                    hours=org.hours,
                    social=org.social,
                    source_links=[{"source": s.get("source", "unknown"), "url": s.get("url") or s.get("page") or ""}
                                  for s in org.sources if isinstance(s, dict) and (s.get("url") or s.get("page"))],
                    rating=org.rating,
                    review_count=org.review_count,
                    services=org.services,
                    cms_star_rating=cms_rating,
                    cms_ownership=cms_owner,
                    nc_license_number=nc_lic,
                    nc_license_status=nc_stat,
                    named_people=card_people,
                    emails=org_emails,
                    sources=org_sources,
                    citation_ids=org_cit_ids,
                )
            )

        summary_md = self._generate_cited_summary(intent, cards, citations, source_breakdown, total=len(orgs))

        return SearchAnswer(
            query=intent.query,
            total_organizations=len(orgs),
            total_people=len(people),
            shown_organizations=len(cards),
            geography=intent.geography,
            summary_markdown=summary_md,
            source_breakdown=source_breakdown,
            cards=cards,
            citations=citations,
            source_statuses=source_statuses,
            elapsed_ms=elapsed_ms,
        )

    def _generate_cited_summary(
        self,
        intent: SearchIntent,
        cards: List[AnswerCard],
        citations: List[CitationItem],
        source_breakdown: Dict[str, int],
        total: Optional[int] = None,
    ) -> str:
        """Constructs an executive synthesis strictly matching returned records."""
        geo = intent.geography or {}
        loc_display = geo.get("name") or (f"{geo.get('city', '')}, {geo.get('state', '')}".strip(" ,"))

        breakdown_parts = [f"{src}: {cnt}" for src, cnt in source_breakdown.items() if cnt > 0]
        breakdown_str = f" (records per source: {', '.join(breakdown_parts)})" if breakdown_parts else ""

        has_cms = any(c.cms_star_rating is not None for c in cards)
        has_lic = any(c.nc_license_number is not None for c in cards)
        has_people = any(len(c.named_people) > 0 for c in cards)

        total = total if total is not None else len(cards)
        lines = [f"### Discovery Synthesis: {intent.query}"]

        if not cards:
            lines.append("No matching organizations found for this query and location.")
            return "\n".join(lines)

        desc_features = []
        if has_cms:
            desc_features.append("Medicare quality ratings")
        if has_lic:
            desc_features.append("state licensing records")
        if has_people:
            desc_features.append("named contacts")

        feature_clause = f" with {', '.join(desc_features)}" if desc_features else ""
        shown = f", showing the top {len(cards)}" if len(cards) < total else ""
        where = f" in {loc_display}" if loc_display else ""
        lines.append(f"Found **{total} organizations**{where}{breakdown_str}{feature_clause}{shown}.\n")

        for i, card in enumerate(cards[:5], 1):
            cit_tags = "".join(f"[{c}]" for c in card.citation_ids[:3])
            details = []
            if card.category:
                details.append(card.category)
            if card.cms_star_rating:
                details.append(f"CMS {card.cms_star_rating}★")
            if card.nc_license_number:
                details.append(f"NC Lic #{card.nc_license_number}")
            if card.phone:
                details.append(card.phone)

            detail_str = " | ".join(details)
            lines.append(f"{i}. **{card.name}** {cit_tags} — {detail_str}")

            if card.named_people:
                lead = card.named_people[0]
                role_desc = lead.get("title") or lead.get("role_type")
                role_part = f" ({role_desc})" if role_desc else ""
                lines.append(f"   - *Leadership:* {lead['name']}{role_part}")

        return "\n".join(lines)
