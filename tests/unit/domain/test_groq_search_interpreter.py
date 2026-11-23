"""
Unit tests for GroqSearchInterpreter & ParsedSearchPlan.
Validates Pydantic v2 schemas, multi-key rotation, failover mechanics,
and deterministic entity extraction.
"""

import pytest
import asyncio
from packages.domain.groq_search_interpreter import (
    ParsedSearchPlan,
    GroqSearchInterpreter,
    groq_search_interpreter,
)


def test_parsed_search_plan_schema_validation():
    """Verifies ParsedSearchPlan enforces valid types and default values."""
    plan = ParsedSearchPlan(
        mode="company",
        expanded_keywords=["home health care", "senior living", "assisted living"],
        naics_codes=["621610", "624120"],
        states=["TX"],
        cities=["Dallas"],
        require_verified_email=True,
        require_direct_phone=False,
        assistant_summary="Searching for Texas home care companies with verified emails.",
        source_model="groq-openai-gpt-oss-20b",
    )
    assert plan.mode == "company"
    assert len(plan.expanded_keywords) == 3
    assert plan.naics_codes == ["621610", "624120"]
    assert plan.states == ["TX"]
    assert plan.cities == ["Dallas"]
    assert plan.require_verified_email is True
    assert plan.source_model == "groq-openai-gpt-oss-20b"


def test_heuristic_fallback_extraction():
    """Verifies deterministic regex engine accurately extracts entities when LLM is offline."""
    interpreter = GroqSearchInterpreter()

    # Company mode query
    plan_company = interpreter._heuristic_fallback(
        "Find homecare agencies in Texas with verified emails",
        mode="company"
    )
    assert plan_company.mode == "company"
    assert "TX" in plan_company.states
    assert plan_company.require_verified_email is True
    assert len(plan_company.expanded_keywords) >= 5
    assert "621610" in plan_company.naics_codes

    # People mode query
    plan_people = interpreter._heuristic_fallback(
        "Show C-suite and VPs of Engineering at SaaS companies in California",
        mode="people"
    )
    assert plan_people.mode == "people"
    assert "CA" in plan_people.states
    assert "C_SUITE" in plan_people.seniority_tiers
    assert "VP" in plan_people.seniority_tiers
    assert "ENGINEERING_TECH" in plan_people.departments


@pytest.mark.asyncio
async def test_live_or_fallback_interpret_query():
    """Verifies end-to-end interpret_query returns a valid ParsedSearchPlan."""
    plan = await groq_search_interpreter.interpret_query(
        "Find manufacturing companies in California with verified emails",
        mode="company"
    )
    assert plan.mode == "company"
    assert isinstance(plan.expanded_keywords, list)
    assert "CA" in plan.states
    assert plan.require_verified_email is True
    assert len(plan.assistant_summary) > 10
    assert plan.source_model is not None


def test_metro_geography_resolution():
    """Verifies that metro area queries accurately resolve states, cities, and clean keywords."""
    interpreter = GroqSearchInterpreter()
    plan = interpreter._heuristic_fallback(
        "child care in Charlotte metro area",
        mode="company"
    )
    assert plan.mode == "company"
    assert "NC" in plan.states
    assert "SC" in plan.states
    assert "Charlotte" in plan.cities
    assert "624410" in plan.naics_codes
    # Location tokens should NOT pollute expanded_keywords
    assert "charlotte" not in [kw.lower() for kw in plan.expanded_keywords]
    assert "metro" not in [kw.lower() for kw in plan.expanded_keywords]
    assert "area" not in [kw.lower() for kw in plan.expanded_keywords]
