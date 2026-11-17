"""
Unit tests for packages/discovery/planner.py and packages/discovery/geo.py.
Tests:
  - Natural language location resolution (Charlotte MSA, coordinates, counties)
  - Category and synonym expansion
  - QueryPlanner rule-based intent parsing
  - In-memory cache behavior
"""

from __future__ import annotations

import pytest

from packages.discovery.geo import resolve_geography
from packages.discovery.planner import QueryPlanner


def test_resolve_geography_charlotte_metro():
    geo = resolve_geography("elderly care in Charlotte metro area")
    assert geo["type"] == "msa"
    assert geo["city"] == "Charlotte"
    assert geo["state"] == "NC"
    assert "lat" in geo and geo["lat"] > 30.0
    assert any("Mecklenburg" in c for c in geo["counties"])
    assert "Concord" in geo["cities"]


def test_resolve_geography_specific_city():
    geo = resolve_geography("home care in Concord, NC")
    assert geo["city"] == "Concord"
    assert geo["state"] == "NC"


@pytest.mark.anyio
async def test_query_planner_parsing_and_caching():
    planner = QueryPlanner()

    # Query 1
    intent1 = await planner.plan("elderly care, home care in Charlotte metro area")
    assert "elderly care" in intent1.categories
    assert any("home care" in c for c in intent1.categories)
    assert intent1.geography["city"] == "Charlotte"
    assert intent1.geography["state"] == "NC"
    assert len(intent1.synonyms) > 0

    # Query 2 (should hit cache)
    intent2 = await planner.plan("elderly care, home care in Charlotte metro area")
    assert intent1.model_dump() == intent2.model_dump()


def test_resolve_geography_austin_and_wake_and_unresolved():
    austin = resolve_geography("Austin, TX")
    assert austin["city"] == "Austin"
    assert austin["state"] == "TX"
    assert not austin.get("needs_location")

    wake = resolve_geography("Wake County NC")
    assert wake["type"] == "county"
    assert "Wake" in wake["name"]
    assert wake["state"] == "NC"
    assert not wake.get("needs_location")

    plumbers = resolve_geography("plumbers")
    assert plumbers.get("needs_location") is True


@pytest.mark.anyio
async def test_planner_unknown_category_derivation():
    planner = QueryPlanner()
    intent = await planner.plan("specialized hydraulic pump repair in Concord, NC")
    assert intent.geography["city"] == "Concord"
    assert any("hydraulic pump repair" in c for c in intent.categories)
    assert not any("elderly" in c.lower() for c in intent.categories)


def test_geography_comes_from_census_tables():
    from packages.discovery.geo import resolve_geography
    msa = resolve_geography("Charlotte metro area")
    assert msa["type"] == "msa" and msa["cbsa_code"] == "16740"
    assert {"Mecklenburg, NC", "Union, NC", "Cabarrus, NC", "Gaston, NC", "York, SC", "Lancaster, SC"} <= set(msa["counties"])
    assert set(msa["states"]) == {"NC", "SC"} and msa["centers"][0]["name"] == "Charlotte"
    assert resolve_geography("28202")["city"] == "Charlotte"
    assert resolve_geography("North Carolina") == {**resolve_geography("North Carolina"), "type": "state", "state": "NC"}
    assert resolve_geography("Charlotte, WV").get("needs_location") is True     # no silent fallback to NC
    assert resolve_geography("roofing contractors").get("needs_location") is True
