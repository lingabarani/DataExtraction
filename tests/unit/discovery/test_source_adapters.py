"""
Source adapter tests. Every network call goes to an httpx.MockTransport; nothing touches the internet or the real DB.
Fixture records use obviously fake names (TEST ...) in the exact shape of the official CMS / NC DHSR data.
"""

from __future__ import annotations

import io
import json
import time

import httpx
import openpyxl
import pytest

from packages.discovery.geo import resolve_geography
from packages.discovery.http import set_transport_override
from packages.discovery.models import Budget, OrgRecord, PersonRecord, SearchIntent
from packages.discovery.sources.base import SourceAdapter
from packages.discovery.sources.cms_care_compare import CMSCareCompareSource, build_conditions, DATASETS
from packages.discovery.sources.enrichment import EnrichmentSource
from packages.discovery.sources.google_maps import GoogleMapsSource, clean_website, parse_us_address, search_centers
from packages.discovery.sources.state_registry import (
    StateRegistrySource, map_dhsr_row, parse_dhsr_xlsx,
)
from packages.discovery.sources.web_search import WebSearchSource


def budget(seconds: float = 10.0) -> Budget:
    return Budget(total_seconds=seconds, deadline=time.monotonic() + seconds)


def intent(query: str, location: str, categories=None) -> SearchIntent:
    return SearchIntent(query=query, categories=categories or ["home care"], geography=resolve_geography(location))


async def collect(src, it, b=None):
    return [r async for r in src.search(it, b or budget())]


@pytest.fixture(autouse=True)
def _reset_transports():
    yield
    for name in ("discovery_cms", "discovery_state_registry", "discovery_web_search", "discovery_gmaps",
                 "discovery_website_crawl"):
        set_transport_override(name, None)


# ── base adapter ─────────────────────────────────────────────────────────────

class BrokenSource(SourceAdapter):
    def __init__(self):
        super().__init__(name="broken_source")

    async def _execute_search(self, intent, budget):
        raise RuntimeError("Simulated remote crash")
        yield  # pragma: no cover


@pytest.mark.anyio
async def test_base_source_exception_containment():
    results = await collect(BrokenSource(), SearchIntent(query="x"))
    assert len(results) == 1 and results[0].status.status == "error"
    assert "Simulated remote crash" in (results[0].status.message or "")


# ── CMS ──────────────────────────────────────────────────────────────────────

def cms_row(name, ccn, city="CHARLOTTE", **extra):
    base = {"state": "NC", "cms_certification_number_ccn": ccn, "provider_name": name, "address": "1 TEST WAY",
            "citytown": city, "zip_code": "28202", "telephone_number": "7045550101",
            "type_of_ownership": "NON-PROFIT", "offers_nursing_care_services": "Yes",
            "offers_physical_therapy_services": "No", "quality_of_patient_care_star_rating": "4.5"}
    base.update(extra)
    return base


def cms_transport(rows, status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((str(request.url), json.loads(request.content or b"{}")))
        if status != 200:
            return httpx.Response(status, text="err")
        body = json.loads(request.content)
        page = rows[body["offset"]: body["offset"] + body["limit"]]
        return httpx.Response(200, json={"results": page, "count": len(rows)})
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_cms_maps_real_field_names_and_filters_by_state_and_cities():
    seen = []
    set_transport_override("discovery_cms", cms_transport([cms_row("TEST AGENCY ALPHA", "340001"),
                                                           cms_row("TEST AGENCY BETA", "340002", city="CONCORD")], seen=seen))
    res = (await collect(CMSCareCompareSource(), intent("home care in Charlotte", "Charlotte NC")))[0]
    assert res.status.status == "ok" and len(res.organizations) == 2
    org = res.organizations[0]
    assert org.name == "TEST AGENCY ALPHA" and org.category == "Home Health Agency"
    assert org.regulatory["cms_star_rating"] == 4.5 and org.regulatory["cms_ccn"] == "340001"
    assert org.regulatory["cms_ownership"] == "NON-PROFIT" and org.services == ["nursing_care"]
    assert org.phones[0].number == "7045550101" and org.address["city"] == "Charlotte"
    assert org.sources[0]["dataset"] == "6jpm-sxkc"
    facts = {f.field for f in res.facts}
    assert {"cms_certification", "cms_star_rating"} <= facts
    url, body = seen[0]
    assert url.endswith("/datastore/query/6jpm-sxkc/0")
    props = {c["property"]: c for c in body["conditions"]}
    assert props["state"]["value"] == "NC"
    assert props["citytown"]["operator"] == "IN" and "CHARLOTTE" in props["citytown"]["value"]


@pytest.mark.anyio
async def test_cms_pages_through_results():
    rows = [cms_row(f"TEST AGENCY {i:03d}", f"34{i:04d}") for i in range(230)]
    seen = []
    set_transport_override("discovery_cms", cms_transport(rows, seen=seen))
    res = (await collect(CMSCareCompareSource(), intent("home health", "Charlotte NC")))[0]
    assert len(res.organizations) == 230
    assert [b["offset"] for _, b in seen] == [0, 100, 200]


@pytest.mark.anyio
async def test_cms_metro_queries_each_state_and_dataset_kind():
    seen = []
    set_transport_override("discovery_cms", cms_transport([], seen=seen))
    it = intent("elderly care, home care in Charlotte metro area", "Charlotte metro area", ["elderly care"])
    await collect(CMSCareCompareSource(), it)
    datasets = {u.split("/query/")[1].split("/")[0] for u, _ in seen}
    states = {next(c["value"] for c in b["conditions"] if c["property"] == "state") for _, b in seen}
    assert datasets == {"6jpm-sxkc", "4pq5-n9py", "yc9t-dgbk"} and states == {"NC", "SC"}
    county_conds = [c for _, b in seen for c in b["conditions"] if c["property"] == "countyparish"]
    assert county_conds and any("MECKLENBURG" in c["value"] for c in county_conds)


@pytest.mark.parametrize("status,expected", [(500, "unavailable"), (403, "blocked"), (429, "blocked")])
@pytest.mark.anyio
async def test_cms_reports_failures_honestly(status, expected):
    set_transport_override("discovery_cms", cms_transport([], status=status))
    res = (await collect(CMSCareCompareSource(), intent("home health", "Charlotte NC")))[0]
    assert res.status.status == expected and res.organizations == []


@pytest.mark.anyio
async def test_cms_is_not_applicable_to_other_industries():
    seen = []
    set_transport_override("discovery_cms", cms_transport([cms_row("X", "1")], seen=seen))
    res = (await collect(CMSCareCompareSource(), intent("plumbers in Charlotte NC", "Charlotte NC", ["plumbers"])))[0]
    assert res.status.status == "empty" and "Not applicable" in res.status.message
    assert res.organizations == [] and seen == []


def test_cms_conditions_use_zip_and_counties():
    zip_geo = resolve_geography("28202")
    assert {"property": "zip_code", "value": "28202", "operator": "="} in build_conditions(DATASETS["home_health"], zip_geo, "NC")
    msa = resolve_geography("Charlotte metro area")
    nh = build_conditions(DATASETS["nursing_home"], msa, "SC")
    assert any(c["property"] == "countyparish" and "YORK" in c["value"] for c in nh)


# ── NC DHSR registry ─────────────────────────────────────────────────────────

def dhsr_workbook(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, None, "Home Care All\nLicensed by the State"])
    ws.append([])
    ws.append(["RowNo.", "County", "License #", None, None, "Name of Licensee Legal Name", "DBA Name", None,
               "Facility Contact Name", "Facility Contact Number", None, "Facility Fax", "Director Name", "Director Title",
               "Owner Name", "Site Address", "Site City", "Site State", "Site Zip"])
    for i, r in enumerate(rows, 1):
        ws.append([str(i), r["county"], r["license"], None, None, r["legal"], r["dba"], None, "Contact Person",
                   r["phone"], None, "", r["director"], r["title"], r["legal"], r["street"], r["city"], "NC", r["zip"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


DHSR_ROWS = [
    {"county": "Mecklenburg", "license": "HC9901", "legal": "Test Registry Agency One LLC", "dba": "Test Registry One",
     "phone": "(704) 555-0111", "director": "Alex Testperson", "title": "Director", "street": "1 Fake St",
     "city": "Charlotte", "zip": "28202"},
    {"county": "Wake", "license": "HC9902", "legal": "Test Registry Agency Two", "dba": "", "phone": "(919) 555-0122",
     "director": "Test Registry Agency Two", "title": "Director", "street": "2 Fake St", "city": "Raleigh", "zip": "27601"},
]


@pytest.fixture
def registry_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCOVERY_REGISTRY_DIR", str(tmp_path))
    return tmp_path


def registry_transport(content=None, status=200, hits=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if hits is not None:
            hits.append(request.url.path)
        return httpx.Response(status, content=content or b"")
    return httpx.MockTransport(handler)


def test_parse_dhsr_workbook_finds_header_row_and_maps_fields():
    rows = parse_dhsr_xlsx(dhsr_workbook(DHSR_ROWS))
    assert [r["license #"] for r in rows] == ["HC9901", "HC9902"]
    mapped = map_dhsr_row(rows[0], "Home Care Agency")
    assert mapped["name"] == "Test Registry One" and mapped["county"] == "Mecklenburg"
    assert mapped["person_name"] == "Alex Testperson" and mapped["zip"] == "28202"
    with pytest.raises(ValueError):
        parse_dhsr_xlsx(_bad_workbook())


def _bad_workbook():
    wb = openpyxl.Workbook()
    wb.active.append(["nothing", "useful"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.anyio
async def test_registry_filters_by_county_and_only_keeps_real_person_names(registry_env):
    set_transport_override("discovery_state_registry", registry_transport(dhsr_workbook(DHSR_ROWS)))
    res = (await collect(StateRegistrySource(), intent("home care in Charlotte metro area", "Charlotte metro area")))[0]
    assert res.status.status == "ok"
    assert [o.name for o in res.organizations] == ["Test Registry One"]          # Wake County row filtered out
    org = res.organizations[0]
    assert org.regulatory["nc_license_number"] == "HC9901" and org.address["postal_code"] == "28202"
    assert [p.name for p in res.people] == ["Alex Testperson"]
    assert "no adapter for SC" in (res.status.message or "")
    # the second row's "director" is the company itself and must not become a person
    wake = (await collect(StateRegistrySource(), intent("home care in Raleigh NC", "Raleigh NC")))[0]
    assert wake.organizations and wake.people == []


@pytest.mark.anyio
async def test_registry_caches_downloaded_files(registry_env):
    hits = []
    set_transport_override("discovery_state_registry", registry_transport(dhsr_workbook(DHSR_ROWS), hits=hits))
    await collect(StateRegistrySource(), intent("home care in Raleigh NC", "Raleigh NC"))
    first = len(hits)
    await collect(StateRegistrySource(), intent("home care in Raleigh NC", "Raleigh NC"))
    assert first >= 1 and len(hits) == first                                       # second search: no download
    assert list((registry_env / "nc").glob("*.json"))


@pytest.mark.anyio
async def test_registry_unavailable_when_download_fails_and_no_cache(registry_env):
    set_transport_override("discovery_state_registry", registry_transport(status=404))
    res = (await collect(StateRegistrySource(), intent("home care in Raleigh NC", "Raleigh NC")))[0]
    assert res.status.status == "unavailable" and res.organizations == []


@pytest.mark.anyio
async def test_registry_unsupported_state_and_not_applicable(registry_env):
    res = (await collect(StateRegistrySource(), intent("home care in Austin, TX", "Austin, TX")))[0]
    assert res.status.status == "unavailable" and "No state licensing adapter for TX" in res.status.message
    res = (await collect(StateRegistrySource(), intent("plumbers in Raleigh NC", "Raleigh NC", ["plumbers"])))[0]
    assert res.status.status == "empty"


# ── web search ───────────────────────────────────────────────────────────────

DDG_HTML = """<html><body>
<div class="result"><h2 class="result__title"><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.senioradvice.example%2Fbest-10">10 Best Home Care Agencies in Charlotte, NC - Reviews</a></h2><a class="result__snippet">Compare</a></div>
<div class="result"><h2 class="result__title"><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.yelp.com%2Fsearch%3Ffind%3Dhome">Top Home Care - Yelp</a></h2></div>
<div class="result"><h2 class="result__title"><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.comforcare-test.example%2Fcharlotte">Home Care Services | Elderly In-Home Care | Comforcare-Test</a></h2><a class="result__snippet">Care at home.</a></div>
<div class="result"><h2 class="result__title"><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fangeliccare-test.example%2F">Home Care Agency near me in Charlotte NC | Angelic Care</a></h2></div>
</body></html>"""


def ddg_transport(status=200, body=DDG_HTML):
    return httpx.MockTransport(lambda req: httpx.Response(status, text=body))


@pytest.mark.anyio
async def test_web_search_keeps_directories_as_references_and_names_brands_from_titles():
    set_transport_override("discovery_web_search", ddg_transport())
    res = (await collect(WebSearchSource(), intent("home care in Charlotte NC", "Charlotte NC", ["home care"])))[0]
    names = {o.name for o in res.organizations}
    domains = {o.domain for o in res.organizations}
    assert "comforcare-test.example" in domains and "yelp.com" not in domains and "senioradvice.example" not in domains
    assert "Comforcare-Test" in names                       # brand taken from the matching title segment
    assert all(o.category == "home care" for o in res.organizations)   # label from the intent, never hard-coded
    assert "directory" in (res.status.message or "")


@pytest.mark.parametrize("status,body", [(202, "<html>anomaly</html>"), (429, "")])
@pytest.mark.anyio
async def test_web_search_reports_blocking(status, body):
    set_transport_override("discovery_web_search", ddg_transport(status, body))
    res = (await collect(WebSearchSource(), intent("home care in Charlotte NC", "Charlotte NC")))[0]
    assert res.status.status == "blocked" and res.organizations == []


def test_web_search_profile_snippet_parsing():
    adapter = WebSearchSource()
    parsed = adapter._parse_profile_snippet(
        title="Sarah Jenkins - Executive Director - Queen City Senior Care | LinkedIn",
        snippet="x", url="https://www.linkedin.com/in/sarah-jenkins")
    assert parsed == {"full_name": "Sarah Jenkins", "title": "Executive Director", "company": "Queen City Senior Care"}
    assert adapter._classify_role("Director of Nursing") == "director_of_nursing"


# ── Google Maps ──────────────────────────────────────────────────────────────

def test_crawl_reads_url_encoded_mailto_without_stray_digits():
    from types import SimpleNamespace
    from packages.discovery.sources.website_crawl import WebsiteCrawlSource
    html = '<a href="mailto:%20info@alfonsodental305.com">Email</a> or office@alfonsodental305.com'
    out = WebsiteCrawlSource()._build({"url": "https://alfonsodental305.com", "target": {"name": "Alfonso Dental"},
                                       "pages": [SimpleNamespace(html=html, url="https://alfonsodental305.com")]})
    assert sorted(e.value for e in out["org"].emails) == ["info@alfonsodental305.com", "office@alfonsodental305.com"]


@pytest.mark.anyio
async def test_google_maps_street_is_not_the_whole_address_line(monkeypatch):
    from packages.scrapers.google_maps.src.gmaps_scraper.models import PlaceStub

    async def fake_fetch(self, query, center, state, span_m, budget, offset=0, country="us"):
        return [PlaceStub(cid="1", ftid="f", place_id="p1", name="Alfonso Dental Miami",
                          street_address="351 NW 42nd Ave Ste 402, Miami, FL 33126",
                          address="351 NW 42nd Ave Ste 402, Miami, FL 33126")], None, False

    monkeypatch.setattr(GoogleMapsSource, "_fetch_stubs", fake_fetch)
    results = await collect(GoogleMapsSource(), intent("dentists in Miami FL", "Miami FL", categories=["dentists"]))
    addr = results[0].organizations[0].address
    assert addr["street"] == "351 NW 42nd Ave Ste 402" and addr["city"] == "Miami" and addr["postal_code"] == "33126"


def test_parse_us_address_and_website_cleaning():
    a = parse_us_address("219 Greenwich Rd, Charlotte, NC 28211")
    assert a == {"street": "219 Greenwich Rd", "city": "Charlotte", "state": "NC", "postal_code": "28211"}
    assert parse_us_address("nonsense")["postal_code"] == ""
    assert clean_website("https://x.example/a?utm_source=g&id=7&gclid=1") == "https://x.example/a?id=7"


def test_search_centers_come_from_geography_never_a_default():
    assert search_centers({}) == [] and search_centers({"state": "NC"}) == []
    msa = resolve_geography("Charlotte metro area")
    assert [c["name"] for c in search_centers(msa)][0] == "Charlotte" and len(search_centers(msa)) <= 3


@pytest.mark.anyio
async def test_google_maps_without_coordinates_is_unavailable_not_charlotte():
    res = (await collect(GoogleMapsSource(), intent("home care in North Carolina", "North Carolina")))[0]
    assert res.status.status == "unavailable" and res.organizations == []


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.anyio
async def test_google_maps_block_is_reported_and_not_retried(status):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(status, text="unusual traffic")
    set_transport_override("discovery_gmaps", httpx.MockTransport(handler))
    res = (await collect(GoogleMapsSource(), intent("home care in Charlotte NC", "Charlotte NC")))[0]
    assert res.status.status == "blocked" and res.organizations == []
    assert len(calls) == 1                                  # single city, single query: one request, no evasion


@pytest.mark.anyio
async def test_google_maps_captcha_page_is_blocked():
    set_transport_override("discovery_gmaps", httpx.MockTransport(
        lambda req: httpx.Response(200, text="<html>Our systems have detected unusual traffic</html>")))
    res = (await collect(GoogleMapsSource(), intent("home care in Charlotte NC", "Charlotte NC")))[0]
    assert res.status.status == "blocked"


def test_google_maps_pages_scale_with_wanted_results_and_stay_capped():
    from packages.discovery.sources.google_maps import MAX_PAGES, MAX_REQUESTS, pages_per_job
    assert pages_per_job(25, 6) == 1                      # metro search, few results: one page per center/query
    assert pages_per_job(250, 2) == MAX_PAGES             # single city, many results: page deeper
    assert pages_per_job(1000, 6) * 6 <= MAX_REQUESTS     # never more than the hard request cap


@pytest.mark.anyio
async def test_google_maps_pages_only_full_jobs_and_streams_each_round(monkeypatch):
    from packages.scrapers.google_maps.src.gmaps_scraper.models import PlaceStub
    calls = []

    async def fake_fetch(self, query, center, state, span_m, budget, offset=0, country="us"):
        calls.append(offset)
        n = 20 if offset < 40 else 7                      # pages 1-2 full, page 3 short
        return [PlaceStub(cid=f"{offset}-{i}", ftid="f", place_id=f"p{offset}-{i}", name=f"Plumber {offset}-{i}",
                          address=f"{i} Main St, Austin, TX 78701") for i in range(n)], None, False

    monkeypatch.setattr(GoogleMapsSource, "_fetch_stubs", fake_fetch)
    it = intent("plumbers in Austin TX", "Austin TX", categories=["plumbers"])
    it.filters["max_results"] = 250
    results = await collect(GoogleMapsSource(), it)
    batches = [r for r in results if r.organizations]
    final = results[-1]
    assert len(batches) == 2                               # round 1 is sent before round 2 starts
    assert calls[0] == 0 and sorted(calls[1:]) == [20, 40, 60, 80]
    assert final.status.status == "ok" and final.status.count == sum(len(b.organizations) for b in batches)
    assert final.status.count == 20 + 20 + 7 + 7 + 7


@pytest.mark.anyio
async def test_google_maps_can_be_disabled(monkeypatch):
    monkeypatch.setenv("DISCOVERY_DISABLE_GOOGLE_MAPS", "true")
    res = (await collect(GoogleMapsSource(), intent("home care in Charlotte NC", "Charlotte NC")))[0]
    assert res.status.status == "unavailable" and "Disabled" in res.status.message


# ── enrichment ───────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_enrichment_source_email_derivation(monkeypatch):
    import packages.leadintel.email_finder as ef
    monkeypatch.setattr(ef, "check_mx_records", lambda domain, timeout=4.0: True)
    person = PersonRecord(full_name="Marcus Holloway", normalized_name="marcus holloway", title="Agency Director",
                          role_type="administrator", org_name="Senior Helpers of Charlotte")
    org = OrgRecord(canonical_name="Senior Helpers of Charlotte", normalized_name="senior helpers of charlotte",
                    domain="seniorhelpers.com")
    it = SearchIntent(query="enrich test", filters={"people": [person], "organizations": [org]})
    res = (await collect(EnrichmentSource(), it))[0]
    assert res.status.status == "ok" and len(res.people) == 1
    email = res.people[0].emails[0]
    assert email.label == "inferred" and "seniorhelpers.com" in email.value and email.confidence >= 0.6
