"""
Entity resolution and fact fusion for the Discovery Engine.

Organizations from different sources are merged when ANY strong identity signal agrees (union-find):
  * same non-generic website domain
  * same phone number (last 10 digits) AND similar names
  * same normalized name AND same ZIP (or same city when ZIP is missing)
  * same street number + first street word + ZIP AND similar names (different spellings of one address)
  * same official identifier (CMS CCN, state license number)
Two branches of one chain at different addresses do NOT merge unless they share a domain, and a shared
domain is only trusted when the names are also similar (chains often share one website).
People are merged by email, else by name + organization.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Set, Tuple

from packages.discovery.models import FactRecord, OrgRecord, PersonRecord
from packages.discovery.names import canonical_person_name
from packages.leadintel.deduplication import (
    GENERIC_DOMAINS,
    clean_domain,
    generate_person_match_key,
    normalize_string,
)

logger = logging.getLogger("discovery.resolver")

SOURCE_TRUST_HIERARCHY: Dict[str, float] = {
    "state_registry": 1.5,
    "cms_care_compare": 1.5,
    "website_crawl": 1.3,
    "google_maps": 1.2,
    "linkedin_public": 1.1,
    "web_search": 1.1,
    "local_db": 1.0,
    "enrichment": 0.9,
    "manual_seed": 0.5,
}

_NAME_NOISE = {"the", "of", "and", "at", "a", "an", "llc", "inc", "co", "corp", "ltd", "pllc", "services", "service"}


def phone_key(number: Optional[str]) -> str:
    digits = re.sub(r"\D", "", number or "")
    return digits[-10:] if len(digits) >= 10 else ""


def _name_tokens(name: str) -> Set[str]:
    return {t for t in normalize_string(name).split() if t not in _NAME_NOISE and len(t) > 1}


def name_similarity(a: str, b: str) -> float:
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _street_key(address: Dict[str, object]) -> str:
    street = str(address.get("street") or "").lower()
    m = re.match(r"\s*(\d+)\s+([a-z0-9]+)", street)
    zip5 = str(address.get("postal_code") or "")[:5]
    return f"{m.group(1)}|{m.group(2)}|{zip5}" if (m and zip5) else ""


# Directory, booking and listing sites: many different organizations give these as their "website", so the domain
# says nothing about identity.
DIRECTORY_DOMAINS = {
    "hexahealth.com", "practo.com", "justdial.com", "sulekha.com", "lybrate.com", "credihealth.com", "indiamart.com",
    "zomato.com", "swiggy.com", "tripadvisor.com", "tripadvisor.in", "yelp.com", "yellowpages.com", "bbb.org",
    "linktr.ee", "wa.me", "whatsapp.com", "booking.com", "opentable.com", "healthgrades.com", "zocdoc.com",
    "caring.com", "seniorly.com", "aplaceformom.com", "agingcare.com", "care.com", "homeadvisor.com", "angi.com",
    "thumbtack.com", "nextdoor.com", "wixsite.com", "business.site", "sites.google.com", "blogspot.com",
    "wordpress.com", "godaddysites.com", "square.site", "ueniweb.com",
}


def is_identity_domain(domain: Optional[str]) -> bool:
    """True when a domain can identify one organization (not a social, directory or free-site host)."""
    return bool(domain) and domain not in GENERIC_DOMAINS and domain not in DIRECTORY_DOMAINS and not any(
        domain.endswith("." + d) for d in DIRECTORY_DOMAINS)


def _identity_keys(org: OrgRecord) -> List[Tuple[str, float]]:
    """(key, min_name_similarity) pairs. A key only links records when names are at least this similar."""
    keys: List[Tuple[str, float]] = []
    domain = clean_domain(org.domain or org.website)
    norm = normalize_string(org.canonical_name or org.name)
    zip5 = str(org.address.get("postal_code") or "")[:5]
    city = str(org.address.get("city") or "").lower()
    if is_identity_domain(domain):
        keys.append((f"domain:{domain}", 0.34))
    for ph in org.phones:
        pk = phone_key(ph.number)
        if pk:
            keys.append((f"phone:{pk}", 0.4))
    if norm and zip5:
        keys.append((f"namezip:{norm}|{zip5}", 0.0))
    elif norm and city:
        keys.append((f"namecity:{norm}|{city}", 0.0))
    sk = _street_key(org.address)
    if sk:
        keys.append((f"street:{sk}", 0.34))
    reg = org.regulatory or {}
    if reg.get("cms_ccn"):
        keys.append((f"ccn:{reg['cms_ccn']}", 0.0))
    if reg.get("nc_license_number"):
        keys.append((f"nclic:{reg['nc_license_number']}", 0.0))
    return keys


class _UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _source_name(org: OrgRecord) -> str:
    return org.sources[0].get("source", org.first_seen_source) if org.sources else org.first_seen_source


class EntityResolver:
    """Resolves and merges entities from diverse discovery sources."""

    def resolve(
        self,
        raw_orgs: List[OrgRecord],
        raw_people: List[PersonRecord],
        raw_facts: List[FactRecord],
        include_unverified: bool = False,
    ) -> Tuple[List[OrgRecord], List[PersonRecord], List[FactRecord]]:
        # 1. Organizations: link records that share a strong key and have similar names
        uf = _UnionFind(len(raw_orgs))
        by_key: Dict[str, List[int]] = {}
        for idx, org in enumerate(raw_orgs):
            for key, _min_sim in _identity_keys(org):
                by_key.setdefault(key, []).append(idx)
        thresholds = {i: dict(_identity_keys(o)) for i, o in enumerate(raw_orgs)}
        for key, members in by_key.items():
            anchor = members[0]
            for other in members[1:]:
                need = max(thresholds[anchor].get(key, 0.0), thresholds[other].get(key, 0.0))
                if need == 0.0 or name_similarity(raw_orgs[anchor].canonical_name, raw_orgs[other].canonical_name) >= need:
                    uf.union(anchor, other)

        groups: Dict[int, List[int]] = {}
        for idx in range(len(raw_orgs)):
            groups.setdefault(uf.find(idx), []).append(idx)

        resolved_orgs: List[OrgRecord] = []
        org_id_lookup: Dict[str, str] = {}
        for root in sorted(groups):
            members = [raw_orgs[i] for i in groups[root]]
            members.sort(key=lambda o: -SOURCE_TRUST_HIERARCHY.get(_source_name(o), 1.0))
            canonical = members[0].model_copy(deep=True)
            org_id_lookup[members[0].id] = canonical.id
            for other in members[1:]:
                org_id_lookup[other.id] = canonical.id
                self._merge_organization(canonical, other)
            # Registries often publish names in capitals; show the same name in its mixed-case spelling when another
            # source has it, so the display does not depend on which equal-trust source arrived first.
            display = canonical.canonical_name or canonical.name
            if display and display.isupper():
                for other in members[1:]:
                    cand = other.canonical_name or other.name
                    if cand and not cand.isupper() and normalize_string(cand) == normalize_string(display):
                        canonical.canonical_name = cand
                        break
            resolved_orgs.append(canonical)

        # 2. People
        resolved_people_map: Dict[str, PersonRecord] = {}
        all_input_people = list(raw_people)
        for org in raw_orgs:
            all_input_people.extend(org.people)

        for person in all_input_people:
            if person.provenance == "manual_seed" and not include_unverified:
                continue
            if person.suppressed:
                continue
            first_email = person.emails[0].value if person.emails else None
            p_key = generate_person_match_key(canonical_person_name(person.full_name) or person.full_name,
                                              person.org_name, first_email)
            if p_key not in resolved_people_map:
                canonical_person = person.model_copy(deep=True)
                if canonical_person.org_id in org_id_lookup:
                    canonical_person.org_id = org_id_lookup[canonical_person.org_id]
                resolved_people_map[p_key] = canonical_person
            else:
                self._merge_person(resolved_people_map[p_key], person)

        # 3. Associate people with organizations (rebuild nested people so merged orgs do not hold stale copies)
        for org in resolved_orgs:
            org.people = []
        final_people = list(resolved_people_map.values())
        org_by_id = {o.id: o for o in resolved_orgs}
        org_by_norm_name = {o.normalized_name: o for o in resolved_orgs}
        for p in final_people:
            matched: Optional[OrgRecord] = None
            if p.org_id and p.org_id in org_by_id:
                matched = org_by_id[p.org_id]
            elif p.org_name and normalize_string(p.org_name) in org_by_norm_name:
                matched = org_by_norm_name[normalize_string(p.org_name)]
            if matched:
                p.org_id = matched.id
                p.org_name = matched.canonical_name
                if not any(existing.id == p.id for existing in matched.people):
                    matched.people.append(p)

        # 4. Facts follow their entities to the canonical ids
        person_ids = {p.id for p in final_people}
        final_facts: List[FactRecord] = []
        for fact in raw_facts:
            new_fact = fact.model_copy()
            if fact.entity_type == "organization" and fact.entity_id in org_id_lookup:
                new_fact.entity_id = org_id_lookup[fact.entity_id]
            elif fact.entity_type == "person" and fact.entity_id not in person_ids:
                # person was merged into another record or filtered out: keep the fact only if its entity survived
                continue
            final_facts.append(new_fact)
        return resolved_orgs, final_people, final_facts

    def _merge_organization(self, target: OrgRecord, source: OrgRecord) -> None:
        """Merge `source` into `target`. Callers sort so that `target` is the highest-trust record."""
        # Keep the best display values from the target, fill gaps from the source.
        if not target.website and source.website:
            target.website = source.website
        if not target.domain and source.domain:
            target.domain = source.domain
        if not target.category and source.category:
            target.category = source.category
        for k, v in source.address.items():
            if v and not target.address.get(k):
                target.address[k] = v
        if target.latitude is None and source.latitude is not None:
            target.latitude, target.longitude = source.latitude, source.longitude

        # Consumer rating: keep the one with more reviews (Google) unless the target has none.
        if source.rating is not None and (target.rating is None or (source.review_count or 0) > (target.review_count or 0)):
            target.rating = source.rating
            target.review_count = source.review_count or target.review_count

        for k, v in source.regulatory.items():
            target.regulatory.setdefault(k, v)
        for k, v in source.social.items():
            target.social.setdefault(k, v)
        for s in source.subcategories:
            if s not in target.subcategories:
                target.subcategories.append(s)

        existing_services = set(target.services)
        for s in source.services:
            if s not in existing_services:
                target.services.append(s)
                existing_services.add(s)

        existing_phones = {phone_key(p.number) or p.number for p in target.phones}
        for p in source.phones:
            key = phone_key(p.number) or p.number
            if key not in existing_phones:
                target.phones.append(p)
                existing_phones.add(key)

        existing_emails = {e.value.lower() for e in target.emails}
        for e in source.emails:
            if e.value.lower() not in existing_emails:
                target.emails.append(e)
                existing_emails.add(e.value.lower())

        for h in source.hours:
            if h not in target.hours:
                target.hours.append(h)

        target.sources.extend(source.sources)
        target.quality_score = max(target.quality_score, source.quality_score)
        target.verified = target.verified or source.verified

    def _merge_person(self, target: PersonRecord, source: PersonRecord) -> None:
        if not target.title and source.title:
            target.title = source.title
        if not target.role_type and source.role_type:
            target.role_type = source.role_type
        if not target.headline and source.headline:
            target.headline = source.headline
        if source.verified:
            target.verified = True
        for u in source.profile_urls:
            if u not in target.profile_urls:
                target.profile_urls.append(u)
        existing_emails = {e.value.lower() for e in target.emails}
        for e in source.emails:
            if e.value.lower() not in existing_emails:
                target.emails.append(e)
                existing_emails.add(e.value.lower())
        existing_phones = {phone_key(p.number) or p.number for p in target.phones}
        for ph in source.phones:
            key = phone_key(ph.number) or ph.number
            if key not in existing_phones:
                target.phones.append(ph)
                existing_phones.add(key)
