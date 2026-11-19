"""Worldwide locations: OpenStreetMap fallback, U.S./foreign disambiguation, and sources outside the U.S."""

from __future__ import annotations

import time
from typing import Any, Dict, List

import httpx
import pytest

from packages.discovery import world_geo
from packages.discovery.answer import format_phone
from packages.discovery.http import set_transport_override
from packages.discovery.models import Budget, SearchIntent
from packages.discovery.planner import QueryPlanner
from packages.discovery.world_geo import resolve_location

CHENNAI = {"lat": "13.0836939", "lon": "80.270186", "name": "Chennai", "importance": 0.72,
           "osm_type": "relation", "osm_id": 1, "boundingbox": ["12.95", "13.23", "80.13", "80.33"],
           "address": {"city": "Chennai", "state": "Tamil Nadu", "country": "India", "country_code": "in"}}
COIMBATORE = {**CHENNAI, "lat": "11.0168", "lon": "76.9558", "name": "Coimbatore",
              "address": {"city": "Coimbatore", "state": "Tamil Nadu", "country": "India", "country_code": "in"}}
ANNA_NAGAR = {**CHENNAI, "lat": "13.085", "lon": "80.21", "name": "Anna Nagar", "importance": 0.3,
              "boundingbox": ["13.07", "13.10", "80.20", "80.22"],
              "address": {"suburb": "Anna Nagar", "city": "Chennai", "state": "Tamil Nadu", "country": "India",
                          "country_code": "in"}}
MIAMI_US = {"lat": "25.77", "lon": "-80.19", "name": "Miami", "importance": 0.75, "boundingbox": ["25.7", "25.85", "-80.3", "-80.1"],
            "address": {"city": "Miami", "state": "Florida", "country": "United States", "country_code": "us"}}


def mock_osm(answers: Dict[str, Dict[str, Any]]) -> List[str]:
    """Answer Nominatim requests by lower-cased query; returns the list of queries seen."""
    seen: List[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params.get("q", "").lower()
        seen.append(q)
        assert "DataExtraction" in req.headers.get("user-agent", "")       # policy: identifying User-Agent
        hit = answers.get(q)
        return httpx.Response(200, json=[hit] if hit else [])

    set_transport_override(world_geo.RATE_BUCKET, httpx.MockTransport(handler))
    return seen


@pytest.mark.anyio
async def test_foreign_city_and_metro_area_resolve_worldwide():
    seen = mock_osm({"chennai": CHENNAI})
    geo = await resolve_location("chennai metro area")
    assert geo["type"] == "place" and geo["country_code"] == "in" and not geo["needs_location"]
    assert geo["name"] == "Chennai, Tamil Nadu, India" and geo["search_text"] == "chennai"
    assert 20 <= geo["radius_km"] <= 60 and geo["centers"][0]["lat"] == pytest.approx(13.08, abs=0.01)
    assert seen == ["chennai"]                                            # metro words are not sent


@pytest.mark.anyio
async def test_foreign_text_never_becomes_a_us_place_or_state():
    mock_osm({"coimbatore, tn": COIMBATORE, "anna nagar, chennai": ANNA_NAGAR})
    assert (await resolve_location("Coimbatore, TN"))["country_code"] == "in"           # not Tennessee
    geo = await resolve_location("Anna Nagar, Chennai")                                 # not Anna, TX
    assert geo["country_code"] == "in" and "Anna Nagar" in geo["cities"] and "Chennai" in geo["cities"]


@pytest.mark.anyio
async def test_us_locations_stay_offline_and_unchanged():
    seen = mock_osm({"miami": MIAMI_US})
    for text, kind in [("Charlotte metro area", "msa"), ("Austin, TX", "city"), ("Mecklenburg County NC", "county"),
                       ("28202", "zip")]:
        geo = await resolve_location(text)
        assert geo["type"] == kind and (geo.get("country_code") or "us") == "us"
    assert seen == []                                                     # explicit U.S. places: no lookup
    geo = await resolve_location("Miami")                                 # bare U.S. city: checked, stays U.S.
    assert geo["type"] == "city" and geo["state"] == "FL"


@pytest.mark.anyio
async def test_unknown_place_asks_to_check_spelling_and_is_cached():
    seen = mock_osm({})
    geo = await resolve_location("Xyzzyqqq town")
    assert geo["needs_location"] and "Could not find" in geo["error"]
    await resolve_location("Xyzzyqqq town")
    assert len(seen) == 1                                                 # the miss is cached


@pytest.mark.anyio
async def test_found_places_are_cached_on_disk():
    seen = mock_osm({"chennai": CHENNAI})
    await resolve_location("Chennai")
    world_geo._cache = None                                               # simulate a restart
    assert (await resolve_location("Chennai"))["country_code"] == "in"
    assert seen == ["chennai"]


@pytest.mark.anyio
async def test_planner_understands_the_reported_queries():
    mock_osm({"chennai": CHENNAI, "rs puram, coimbatore": {**COIMBATORE, "name": "RS Puram"}})
    planner = QueryPlanner()
    for query, category in [("homecare in chennai metro area", "home care agency"), ("homecare in Chennai", "home care agency"),
                            ("Hospitals in RS Puram ,Coimbatore", "Hospitals")]:
        intent = await planner.plan(query)
        assert not intent.geography.get("needs_location"), query
        assert intent.geography["country_code"] == "in" and category in intent.categories, query
    intent = await planner.plan("Hospitals in RS Puram ,Coimbatore")
    assert intent.geography["search_text"] == "RS Puram, Coimbatore"
    assert intent.geography["name"] == "RS Puram, Coimbatore, Tamil Nadu, India"


def test_location_phrase_extraction():
    p = QueryPlanner()
    assert p._extract_location_phrase("homes for elderly in Chennai") == "Chennai"
    assert p._extract_location_phrase("care in home in Austin") == "Austin"
    assert p._extract_location_phrase("dentists, Miami FL") == "Miami FL"
    assert p._extract_location_phrase("elderly care, home care") is None    # generic words are not a place
    assert p._extract_location_phrase("plumbers") is None


@pytest.mark.anyio
async def test_us_only_sources_say_not_applicable_abroad():
    from packages.discovery.sources.cms_care_compare import CMSCareCompareSource
    from packages.discovery.sources.state_registry import StateRegistrySource
    mock_osm({"chennai": CHENNAI})
    geo = await resolve_location("Chennai")
    intent = SearchIntent(query="home care in Chennai", categories=["home care agency"], geography=geo)
    b = Budget(total_seconds=5, deadline=time.monotonic() + 5)
    for src in (CMSCareCompareSource(), StateRegistrySource()):
        res = [r async for r in src.search(intent, b)][-1]
        assert res.status.status == "empty" and res.status.message.startswith("Not applicable")


@pytest.mark.anyio
async def test_google_maps_uses_the_country_and_keeps_foreign_addresses(monkeypatch):
    from packages.discovery.sources.google_maps import GoogleMapsSource
    from packages.scrapers.google_maps.src.gmaps_scraper.models import PlaceStub
    seen: Dict[str, Any] = {}

    async def fake_fetch(self, query, center, state, span_m, budget, offset=0, country="us"):
        seen.update(country=country, center=center["name"])
        return [PlaceStub(cid="1", ftid="f", place_id="p", name="KG Hospital", phone="0422 221 2121",
                          address="5, Arts College Rd, Coimbatore, Tamil Nadu 641018, India", city="Coimbatore")], None, False

    monkeypatch.setattr(GoogleMapsSource, "_fetch_stubs", fake_fetch)
    mock_osm({"rs puram, coimbatore": {**COIMBATORE, "name": "RS Puram"}})
    geo = await resolve_location("RS Puram ,Coimbatore")
    intent = SearchIntent(query="Hospitals in RS Puram ,Coimbatore", categories=["Hospitals"], geography=geo)
    org = [r async for r in GoogleMapsSource().search(intent, Budget(total_seconds=5, deadline=time.monotonic() + 5))][0].organizations[0]
    assert seen == {"country": "in", "center": "RS Puram, Coimbatore"}
    assert org.address["country"] == "IN" and org.address["street"].startswith("5, Arts College Rd")
    assert format_phone("0422 221 2121", "IN") == "0422 221 2121"          # not reformatted as a U.S. number
    assert format_phone("9876543210", "IN") == "9876543210"
    assert format_phone("7045550100", "US") == "(704) 555-0100"
