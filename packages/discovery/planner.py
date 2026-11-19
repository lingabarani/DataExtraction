"""
Query Planning Module for Discovery Engine.
Deconstructs natural language queries into structured search intents with categories,
synonyms, and geography. Uses get_llm() with Pydantic structured output, falling back
to deterministic rules if LLM is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from packages.discovery.geo import _STOP_PLACE_WORDS
from packages.discovery.world_geo import resolve_location
from packages.discovery.models import SearchIntent
from packages.infrastructure.llm import get_llm

logger = logging.getLogger("discovery.planner")

CATEGORY_KEYWORDS = {
    "elderly care": ["elderly care", "elder care", "senior care", "geriatric care"],
    "home care agency": ["home care", "homecare", "in-home care", "home health", "aide services", "companion care"],
    "assisted living": ["assisted living", "residential care", "senior living", "memory care"],
    "nursing home": ["nursing home", "skilled nursing", "long term care", "rehabilitation center"],
    "hospice care": ["hospice", "palliative care", "end of life care"],
    "plumber": ["plumber", "plumbing", "drain cleaning", "pipe repair"],
    "roofing contractor": ["roofing", "roofer", "roof replacement", "roof repair"],
}


class PlannedIntent(BaseModel):
    categories: List[str] = Field(default_factory=list)
    synonyms: List[str] = Field(default_factory=list)
    location_phrase: Optional[str] = None
    want: List[str] = Field(default_factory=lambda: ["organizations", "people", "reviews", "contacts"])


class QueryPlanner:
    def __init__(self, cache_ttl_seconds: float = 3600.0) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, tuple[float, SearchIntent]] = {}

    async def plan(self, query: str, filters: Optional[Dict[str, Any]] = None) -> SearchIntent:
        """Parse query into structured SearchIntent, cached by normalized query."""
        norm_key = " ".join(query.lower().split())
        now = time.monotonic()

        if norm_key in self._cache:
            ts, cached_intent = self._cache[norm_key]
            if now - ts < self._cache_ttl:
                if filters:
                    merged = cached_intent.model_copy(deep=True)
                    merged.filters.update(filters)
                    return merged
                return cached_intent

        intent = None
        location: Optional[str] = None
        # Try LLM via unified infrastructure layer if key or provider is available
        if self._has_usable_llm():
            try:
                planned = await self._plan_with_llm(query)
                if planned is not None:
                    intent, location = planned
            except Exception as exc:
                logger.debug("LLM query planner call skipped: %s", exc)

        # Fallback to rule-based parser
        if intent is None:
            location = self._extract_location_phrase(query)
            intent = self._plan_rule_based(query, location)

        # U.S. places from Census files, everywhere else from OpenStreetMap
        intent.geography = await resolve_location(location)

        if filters:
            intent.filters.update(filters)

        self._cache[norm_key] = (now, intent)
        return intent

    def _has_usable_llm(self) -> bool:
        if os.getenv("GROQ_API_KEY"):
            return True
        try:
            from packages.infrastructure.key_vault import get_secrets_manager
            mgr = get_secrets_manager()
            key = mgr.get_active_key("groq")
            if key and getattr(key, "value", None):
                return True
        except Exception:
            pass
        return False

    async def _plan_with_llm(self, query: str) -> Optional[Tuple[SearchIntent, Optional[str]]]:
        """Calls routed LLM with Pydantic structured output schema."""
        llm = get_llm()
        system_prompt = (
            "You are a search query planner for a business and entity discovery engine. "
            "Analyze the user query and output structured categories, synonyms, location phrase, and desired entity types."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Query: {query}"},
        ]

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: llm.chat(messages, schema=PlannedIntent, temperature=0.0, purpose="discovery_planner"),
                ),
                timeout=5.0,
            )
            if result and result.parsed:
                parsed: PlannedIntent = result.parsed
                loc = parsed.location_phrase or self._extract_location_phrase(query)
                return SearchIntent(
                    query=query,
                    categories=parsed.categories or [query],
                    synonyms=parsed.synonyms,
                    want=parsed.want or ["organizations", "people", "reviews", "contacts"],
                ), loc
        except Exception as exc:
            logger.debug("LLM planner failed: %s", exc)
        return None

    def _extract_location_phrase(self, query: str) -> Optional[str]:
        """Text after the last 'in' / 'near' / 'around' / 'at' (then 'for'), else the part after the last comma.

        'homes for elderly in Chennai' -> 'Chennai'; 'Hospitals in RS Puram ,Coimbatore' -> 'RS Puram ,Coimbatore';
        'dentists, Miami FL' -> 'Miami FL'.
        """
        # text after each 'in'/'near'/... keyword, keeping only letters, digits and place punctuation
        after_word = [re.match(r"[\w\s,.'&\-]*", query[m.end():]).group(0)
                      for m in re.finditer(r"\b(?:in|near|around|at|within)\s+", query, flags=re.IGNORECASE)]
        after_comma = [query.rsplit(",", 1)[1]] if "," in query else []
        for cand in after_word[::-1] + after_comma:
            cand = cand.strip(" ,.")
            # a phrase made only of generic words ("home care") is not a location
            if cand and any(w not in _STOP_PLACE_WORDS for w in re.findall(r"[a-z0-9]+", cand.lower())):
                return cand
        return None

    def _plan_rule_based(self, query: str, loc_str: Optional[str]) -> SearchIntent:
        q_lower = query.lower()

        # 1. Identify categories from keyword patterns
        categories: List[str] = []
        synonyms: List[str] = []

        for primary_cat, kw_list in CATEGORY_KEYWORDS.items():
            if any(k in q_lower for k in kw_list):
                categories.append(primary_cat)
                synonyms.extend(kw_list)

        # 3. If no pre-defined category matched, derive category from query without location
        if not categories:
            query_base = query
            if loc_str:
                query_base = re.sub(re.escape(loc_str), "", query, flags=re.IGNORECASE)
            # drop only the connecting word before the location ("hospitals in X" -> "hospitals"), keep "homes for elderly"
            query_base = re.sub(r"\s*\b(in|around|near|at|within)\s*$", "", query_base.strip(" ,."), flags=re.IGNORECASE)
            query_base = query_base.strip(" ,.")
            clean_category = " ".join(query_base.split())
            categories = [clean_category] if clean_category else [query]

        unique_synonyms = [s for s in list(dict.fromkeys(synonyms)) if s not in categories]

        return SearchIntent(
            query=query,
            categories=categories,
            synonyms=unique_synonyms[:6],
            want=["organizations", "people", "reviews", "contacts"],
        )
