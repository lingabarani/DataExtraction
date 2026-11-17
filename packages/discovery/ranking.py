"""
Entity Ranking Module for Discovery Engine.
Ranks resolved organizations based on textual relevance, regulatory standing (CMS/State),
completeness, and consumer ratings.
"""

from __future__ import annotations

import re
from typing import List

from packages.discovery.models import OrgRecord, SearchIntent


def score_organization(org: OrgRecord, intent: SearchIntent) -> float:
    """Compute 0-100 quality/relevance score for an organization."""
    score = 0.0

    # 1. Textual relevance to categories & query keywords (up to 40 pts)
    q_words = re.findall(r"\w+", (intent.query + " " + " ".join(intent.categories)).lower())
    target_text = (
        f"{org.canonical_name} {org.category or ''} {' '.join(org.subcategories)} {' '.join(org.services)}"
    ).lower()

    matches = sum(1 for w in set(q_words) if len(w) > 3 and w in target_text)
    score += min(40.0, matches * 10.0)

    # 2. Regulatory standing (up to 30 pts)
    if "nc_license_number" in org.regulatory:
        score += 15.0  # State licensed facility
    if "cms_star_rating" in org.regulatory:
        star = org.regulatory.get("cms_star_rating") or 0.0
        score += min(15.0, float(star) * 3.0)  # Up to 15 pts for 5-star rating

    # 3. Completeness (up to 20 pts)
    if org.phones:
        score += 5.0
    if org.website:
        score += 5.0
    if org.address.get("street"):
        score += 5.0
    if org.people:
        score += 5.0  # Has named leadership/administrator

    # 4. Consumer ratings (up to 10 pts)
    if org.rating:
        score += min(10.0, org.rating * 2.0)

    return score


def rank_organizations(orgs: List[OrgRecord], intent: SearchIntent) -> List[OrgRecord]:
    """Sort organizations descending by composite ranking score."""
    scored = [(score_organization(org, intent), org) for org in orgs]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [org for _, org in scored]
