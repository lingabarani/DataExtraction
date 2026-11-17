"""
Decides which official healthcare registries are relevant for a query.

CMS and state licensing registries only cover regulated care providers, so a query such as "plumbers in Charlotte"
must not be answered from them. Matching is keyword based on the planner's categories, synonyms and the raw query.
"""

from __future__ import annotations

from typing import Set

from packages.discovery.models import SearchIntent

# registry kind -> trigger words (substring match on lowercase text)
_KIND_TRIGGERS = {
    "home_health": ("home health", "home care", "in-home", "visiting nurse", "personal care", "companion care",
                    "home-care", "homecare", "elderly", "elder care", "senior", "aging", "geriatric"),
    "nursing_home": ("nursing home", "skilled nursing", "nursing facility", "rehab", "convalescent", "long-term care",
                     "long term care", "elderly", "elder care", "senior", "geriatric"),
    "hospice": ("hospice", "palliative", "end-of-life", "end of life", "elderly", "senior", "geriatric"),
    "adult_care": ("assisted living", "adult care", "family care home", "residential care", "senior living",
                   "memory care", "dementia", "alzheimer", "elderly", "elder care", "senior", "geriatric",
                   "independent living", "retirement"),
}
_GENERIC_CARE = ("healthcare", "health care", "caregiver", "care home", "medical care")


def intent_text(intent: SearchIntent) -> str:
    return " ".join([intent.query, *intent.categories, *intent.synonyms]).lower()


def registry_kinds(intent: SearchIntent) -> Set[str]:
    """Subset of {'home_health','nursing_home','hospice','adult_care'} that the query is about (may be empty)."""
    text = intent_text(intent)
    kinds = {kind for kind, words in _KIND_TRIGGERS.items() if any(w in text for w in words)}
    if not kinds and any(w in text for w in _GENERIC_CARE):
        kinds = {"home_health", "nursing_home", "hospice", "adult_care"}
    return kinds
