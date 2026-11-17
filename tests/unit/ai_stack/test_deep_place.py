"""Deep place extraction: parsing helpers, extractor flow, privacy modes and storage."""

import asyncio
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

_GMAPS_SRC = pathlib.Path(__file__).resolve().parents[3] / "packages" / "scrapers" / "google_maps" / "src"
if str(_GMAPS_SRC) not in sys.path:
    sys.path.insert(0, str(_GMAPS_SRC))

from packages.infrastructure.llm.base import LLMResult  # noqa: E402
from packages.scrapers.google_maps import deep_place as dp  # noqa: E402
from packages.scrapers.google_maps.deep_place import (  # noqa: E402
    DeepPlaceExtractor, ReviewInsights, SiteFacts, attributes_to_service_rows, build_review_row,
    hash_reviewer_name, parse_relative_date, regex_contacts, reviewer_identity,
)
from packages.scrapers.google_maps.deep_place_writer import Suppressor, save_bundle  # noqa: E402
from packages.scrapers.google_maps.deep_runner import run_deep_extraction, select_stubs  # noqa: E402

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
TS_MS = 1_700_000_000_000  # 2023-11-14T22:13:20Z


# ══ fixtures that mimic Google's wire format ═════════════════════════════════

def make_review(i, name="Alice Smith", rating=5, text="Great service", rel="2 weeks ago", ts_ms=TS_MS):
    rev = [None] * 40
    rev[1] = rating
    rev[2] = [rel, None, ts_ms]
    rev[3] = [name, "https://img/avatar", f"https://www.google.com/maps/contrib/{1000 + i}/reviews"]
    rev[4] = [None, "1 week ago", "Thanks for visiting!"] if i == 0 else None
    rev[5] = f"rev-{i}"
    rev[26] = "en"
    rev[27] = text
    rev[34] = 2
    return rev


def reviews_response(revs, token=None):
    container = [None, None, revs, None, None, None, token]
    return ")]}'\n" + json.dumps([None, [None] * 10 + [container]])


def details_response():
    p = [None] * 210
    p[4] = [0] * 9
    p[4][7], p[4][8] = 4.6, 120
    p[30] = "America/Chicago"
    p[67] = 1
    p[100] = [None, [["g1", "Service options", [
        ["a1", "Dine-in", [None, [[True, "Dine-in"]]]],
        ["a2", "Takeout", [None, [[True, "Takeout"]]]],
    ]]]]
    p[203] = [[["Monday", 1, None, [["9 AM-5 PM"]]], ["Sunday", 7, None, [["Closed"]]]]]
    return ")]}'\n" + json.dumps([[None, [None, p_wrap(p)]]])


def p_wrap(p):
    # data[0][1][1][14] == p
    return [None] * 14 + [p]


class FakeResp:
    def __init__(self, text="", status=200, url="https://www.google.com/x"):
        self.text, self.status_code, self.url, self.headers = text, status, url, {}


class FakeHttp:
    """Serves details and review pages; counts requests."""

    def __init__(self, pages=None, details=None, block_reviews=False, block_details=False):
        self.pages = list(pages or [])
        self.details = details if details is not None else details_response()
        self.block_reviews, self.block_details = block_reviews, block_details
        self.urls = []

    async def get(self, url, **kw):
        self.urls.append(url)
        if "GetLocalBoqProxy" in url:
            if self.block_reviews:
                return FakeResp("unusual traffic detected", 429)
            return FakeResp(self.pages.pop(0) if self.pages else reviews_response([]))
        if self.block_details:
            return FakeResp("<html>captcha</html>", 429, "https://www.google.com/sorry/index")
        return FakeResp(self.details)


class Page:
    def __init__(self, html):
        self.html = html


class FakeCrawler:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def crawl(self, url):
        self.calls.append(url)
        return {u: Page(h) for u, h in self.pages.items()}


SITE_HTML = {
    "https://acme.test/": (
        '<html><body><h1>Acme Dental</h1><p>Call us: (415) 555-2671</p>'
        '<a href="mailto:Info@Acme.test">email</a><a href="tel:+14155552671">tel</a>'
        '<a href="https://www.facebook.com/acmedental/?ref=x">fb</a>'
        '<p>Our owner Jane Roe leads the practice. We offer teeth whitening and implants.</p>'
        '<img src="logo@2x.png"></body></html>'),
}

STUB = {"cid": "123456789", "ftid": "0x1:0x2", "place_id": "ChIJabc", "name": "Acme Dental",
        "website": "https://acme.test/", "latitude": 37.77, "longitude": -122.41, "city": "San Francisco",
        "region": "CA", "category": "dentist", "company_id": "gmaps_123456789"}


class FakeLLM:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def chat(self, messages, schema=None, **kw):
        self.calls.append(kw.get("purpose"))
        if self.fail:
            raise RuntimeError("llm down")
        if schema is SiteFacts:
            parsed = SiteFacts(people=[{"full_name": "Jane Roe", "role_title": "Owner"},
                                       {"full_name": "Zed Hallucinated", "role_title": "CEO"}],
                               services=["Teeth whitening", "Implants"])
        else:
            parsed = ReviewInsights(items=[{"review_id": "rev-0", "sentiment": "POSITIVE", "topics": ["service"]},
                                           {"review_id": "not-a-real-id", "sentiment": "negative", "topics": []}])
        return LLMResult(text="{}", provider="fake", model="fake", parsed=parsed)


def run(coro):
    return asyncio.run(coro)


def extractor(http, **kw):
    kw.setdefault("run_id", "run-1")
    kw.setdefault("mode", "hash")
    kw.setdefault("crawler", FakeCrawler(SITE_HTML))
    return DeepPlaceExtractor(http, **kw)


# ══ pure helpers ═════════════════════════════════════════════════════════════

@pytest.mark.parametrize("text,delta", [
    ("2 weeks ago", timedelta(days=14)), ("a month ago", timedelta(days=30.4375)),
    ("3 years ago", timedelta(days=3 * 365.25)), ("an hour ago", timedelta(hours=1)),
    ("Edited 5 days ago", timedelta(days=5)), ("yesterday", timedelta(days=1)),
])
def test_relative_dates_become_absolute(text, delta):
    assert parse_relative_date(text, NOW) == NOW - delta


def test_relative_date_unparseable_returns_none():
    assert parse_relative_date("sometime", NOW) is None and parse_relative_date(None, NOW) is None
    assert parse_relative_date("just now", NOW) == NOW


def test_hash_mode_hides_name_and_id_and_is_stable():
    a = reviewer_identity("Alice Smith", "1000", "hash", key=b"k")
    b = reviewer_identity("  alice SMITH ", "1000", "hash", key=b"k")
    assert a["reviewer_name"] is None and a["reviewer_id"] is None
    assert a["reviewer_name_hash"] == b["reviewer_name_hash"] and len(a["reviewer_name_hash"]) == 64
    assert "Alice" not in json.dumps(a)
    assert hash_reviewer_name("Alice Smith", b"other") != a["reviewer_name_hash"]


def test_plain_mode_keeps_name_and_id():
    r = reviewer_identity("Alice Smith", "1000", "plain")
    assert r == {"reviewer_name": "Alice Smith", "reviewer_name_hash": None, "reviewer_id": "1000"}


def test_anonymous_reviewer_stores_nothing():
    assert reviewer_identity("Anonymous", "9", "plain")["reviewer_name"] is None
    assert reviewer_identity("", None, "hash")["reviewer_name_hash"] is None


def test_hash_mode_without_any_key_material_is_refused(monkeypatch):
    monkeypatch.delenv("REVIEWER_HASH_SALT", raising=False)
    monkeypatch.delenv("SECRETS_MASTER_KEY", raising=False)
    with pytest.raises(ValueError, match="REVIEWER_HASH_SALT"):
        hash_reviewer_name("x")


def test_reviewer_mode_validates_env(monkeypatch):
    assert dp.reviewer_mode() == "hash"
    monkeypatch.setenv("REVIEWER_NAME_MODE", "plain")
    assert dp.reviewer_mode() == "plain"
    monkeypatch.setenv("REVIEWER_NAME_MODE", "bogus")
    with pytest.raises(ValueError):
        dp.reviewer_mode()


def test_build_review_row_converts_timestamps_ms_and_us_and_relative():
    raw = {"review_id": "r1", "author_name": "Bob", "author_id": "7", "rating": 4, "text": "ok",
           "timestamp_ms": TS_MS, "relative_date": "a year ago", "photos_json": "[]"}
    row = build_review_row(raw, "p1", "run", "plain", key=None)
    assert row["published_at"] == datetime.fromtimestamp(TS_MS / 1000, tz=timezone.utc)
    us = build_review_row({**raw, "timestamp_ms": TS_MS * 1000}, "p1", "run", "plain")
    assert us["published_at"] == row["published_at"]
    rel = build_review_row({**raw, "timestamp_ms": None}, "p1", "run", "plain", now=NOW)
    assert rel["published_at"] == NOW - timedelta(days=365.25)
    assert row["reviewer_name"] == "Bob" and row["review_text"] == "ok"


def test_attributes_to_service_rows_dedupes_and_skips_blank():
    rows = attributes_to_service_rows([
        {"group_name": "Options", "attribute_name": "Dine-in", "is_enabled": True, "display_value": "Dine-in"},
        {"group_name": "Options", "attribute_name": "Dine-in"}, {"attribute_name": " "},
        {"group_name": "Pay", "attribute_name": "Cards", "is_enabled": False}], "p1", "run")
    assert [(r["group_name"], r["service_name"], r["is_enabled"]) for r in rows] == [
        ("Options", "Dine-in", True), ("Pay", "Cards", False)]


def test_regex_contacts_finds_email_phone_social_and_ignores_junk():
    contacts = regex_contacts(SITE_HTML)
    got = {(c["contact_type"], c["value"]) for c in contacts}
    assert ("email", "info@acme.test") in got
    assert ("phone", "4155552671") in got or ("phone", "+14155552671") in got
    assert ("social", "https://www.facebook.com/acmedental") in got
    assert not any(v.endswith(".png") for _, v in got)
    assert len(contacts) == len(got)  # deduplicated
    assert all(c["extraction_method"] == "regex" for c in contacts)


def test_regex_contacts_drops_placeholder_domains():
    got = regex_contacts({"u": "<p>write to user@example.com or real@shop.test</p>"})
    assert [c["value"] for c in got if c["contact_type"] == "email"] == ["real@shop.test"]


# ══ extractor flow ═══════════════════════════════════════════════════════════

def test_reviews_are_paginated_until_the_token_runs_out():
    http = FakeHttp(pages=[
        reviews_response([make_review(0), make_review(1)], token="T1"),
        reviews_response([make_review(2), make_review(3)], token="T2"),
        reviews_response([make_review(4)], token=None),
    ])
    bundle = run(extractor(http).extract_place(STUB))
    assert [r["review_id"] for r in bundle.reviews] == [f"rev-{i}" for i in range(5)]
    review_urls = [u for u in http.urls if "GetLocalBoqProxy" in u]
    assert len(review_urls) == 3 and "T1" in review_urls[1] and "T2" in review_urls[2]
    assert bundle.status == "complete"


def test_max_reviews_caps_collection():
    http = FakeHttp(pages=[reviews_response([make_review(i) for i in range(10)], token="T1"),
                           reviews_response([make_review(i) for i in range(10, 20)], token=None)])
    bundle = run(extractor(http, max_reviews=7).extract_place(STUB))
    assert len(bundle.reviews) == 7


def test_repeated_page_does_not_loop_forever():
    page = reviews_response([make_review(0)], token="SAME")
    http = FakeHttp(pages=[page, page, page, page])
    bundle = run(extractor(http).extract_place(STUB))
    assert len(bundle.reviews) == 1 and len([u for u in http.urls if "GetLocalBoqProxy" in u]) <= 2


def test_details_and_services_and_hours_are_parsed():
    bundle = run(extractor(FakeHttp(pages=[reviews_response([])])).extract_place(STUB))
    d = bundle.details
    assert d["rating"] == 4.6 and d["review_count"] == 120 and d["timezone"] == "America/Chicago"
    assert [h["day_name"] for h in d["hours"]] == ["Monday", "Sunday"] and d["hours"][1]["is_closed"] is True
    assert {s["service_name"] for s in bundle.services} == {"Dine-in", "Takeout"}


def test_captcha_on_details_marks_blocked_and_stops_early():
    http = FakeHttp(block_details=True)
    bundle = run(extractor(http).extract_place(STUB))
    assert bundle.status == "blocked" and bundle.reviews == [] and bundle.contacts == []
    assert not any("GetLocalBoqProxy" in u for u in http.urls)  # no further requests after a block


def test_captcha_during_reviews_keeps_what_was_collected_as_partial():
    http = FakeHttp(pages=[reviews_response([make_review(0)], token="T1")])
    orig = http.get
    calls = {"n": 0}

    async def flaky(url, **kw):
        if "GetLocalBoqProxy" in url:
            calls["n"] += 1
            if calls["n"] == 2:
                return FakeResp("captcha", 429)
        return await orig(url, **kw)
    http.get = flaky
    bundle = run(extractor(http).extract_place(STUB))
    assert bundle.status == "partial" and len(bundle.reviews) == 1
    assert any("blocked" in n for n in bundle.notes)


def test_website_contacts_are_collected_without_llm():
    http = FakeHttp(pages=[reviews_response([])])
    bundle = run(extractor(http, llm=None).extract_place(STUB))
    types = {c["contact_type"] for c in bundle.contacts}
    assert {"email", "phone", "social"} <= types
    assert all(c["place_id"] == "123456789" and c["run_id"] == "run-1" for c in bundle.contacts)


def test_no_website_means_no_crawl():
    crawler = FakeCrawler(SITE_HTML)
    stub = {**STUB, "website": None}
    run(extractor(FakeHttp(pages=[reviews_response([])]), crawler=crawler).extract_place(stub))
    assert crawler.calls == []


def test_llm_adds_people_services_and_review_insights_but_drops_hallucinations():
    http = FakeHttp(pages=[reviews_response([make_review(0)], token=None)])
    llm = FakeLLM()
    bundle = run(extractor(http, llm=llm).extract_place(STUB))
    names = {p["full_name"] for p in bundle.people}
    assert "Jane Roe" in names and "Zed Hallucinated" not in names
    assert {"Teeth whitening", "Implants"} <= {s["service_name"] for s in bundle.services}
    review = bundle.reviews[0]
    assert review["sentiment"] == "positive" and review["topics"] == ["service"]
    assert set(llm.calls) == {"place_site_facts", "place_review_insights"}


def test_llm_failure_never_breaks_the_scrape():
    http = FakeHttp(pages=[reviews_response([make_review(0)])])
    bundle = run(extractor(http, llm=FakeLLM(fail=True)).extract_place(STUB))
    assert len(bundle.reviews) == 1 and bundle.contacts
    assert any("llm" in n for n in bundle.notes)
    assert bundle.reviews[0].get("sentiment") is None


def test_hash_mode_extractor_never_returns_plain_names():
    http = FakeHttp(pages=[reviews_response([make_review(0, name="Alice Smith")])])
    bundle = run(extractor(http, mode="hash").extract_place(STUB))
    row = bundle.reviews[0]
    assert row["reviewer_name"] is None and row["reviewer_name_hash"]
    assert "Alice" not in json.dumps(row, default=str)


def test_plain_mode_extractor_keeps_names():
    http = FakeHttp(pages=[reviews_response([make_review(0, name="Alice Smith")])])
    row = run(extractor(http, mode="plain").extract_place(STUB)).reviews[0]
    assert row["reviewer_name"] == "Alice Smith" and row["reviewer_name_hash"] is None


def test_suppressed_people_never_reach_the_bundle():
    import hashlib
    h = lambda s: hashlib.sha256(s.strip().lower().encode()).hexdigest()  # noqa: E731
    suppressor = Suppressor({h("Alice Smith"), h("info@acme.test"), h("Jane Roe")})
    http = FakeHttp(pages=[reviews_response([make_review(0, name="Alice Smith"), make_review(1, name="Bob Lee")])])
    bundle = run(extractor(http, llm=FakeLLM(), suppressed=suppressor, mode="plain").extract_place(STUB))
    assert [r["reviewer_name"] for r in bundle.reviews] == ["Bob Lee"]
    assert "Jane Roe" not in {p["full_name"] for p in bundle.people}
    assert "info@acme.test" not in {c["value"] for c in bundle.contacts}


# ══ storage (PostgreSQL) ═════════════════════════════════════════════════════

def _counts(db):
    out = {}
    with db.cursor() as cur:
        for t in ("place_details", "place_services", "place_reviews", "place_contacts", "place_people"):
            cur.execute(f"SELECT COUNT(*) FROM staging_dataextraction.{t}")
            out[t] = cur.fetchone()[0]
    return out


def _bundle(mode="hash", llm=None):
    http = FakeHttp(pages=[reviews_response([make_review(0), make_review(1, name="Bob Lee")], token=None)])
    return run(extractor(http, llm=llm, mode=mode).extract_place(STUB))


def test_saving_twice_is_idempotent(db):
    bundle = _bundle(llm=FakeLLM())
    first = save_bundle(db, bundle, STUB, "run-1")
    db.commit()
    before = _counts(db)
    save_bundle(db, _bundle(llm=FakeLLM()), STUB, "run-2")
    db.commit()
    assert _counts(db) == before
    assert before["place_details"] == 1 and before["place_reviews"] == 2
    assert first["reviews"] == 2 and before["place_services"] >= 4
    with db.cursor() as cur:
        cur.execute("SELECT run_id FROM staging_dataextraction.place_reviews LIMIT 1")
        assert cur.fetchone()[0] == "run-2"  # re-scrape refreshed the row, did not duplicate it


def test_hash_mode_stores_no_plain_reviewer_names(db):
    save_bundle(db, _bundle(mode="hash"), STUB, "run-1")
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT reviewer_name, reviewer_name_hash, reviewer_id FROM staging_dataextraction.place_reviews")
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM staging_dataextraction.place_reviews "
                    "WHERE review_text ILIKE '%Alice%' OR reviewer_name IS NOT NULL")
        assert cur.fetchone()[0] == 0
    assert all(r[0] is None and len(r[1]) == 64 and r[2] is None for r in rows)


def test_plain_mode_stores_names(db):
    save_bundle(db, _bundle(mode="plain"), STUB, "run-1")
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT reviewer_name FROM staging_dataextraction.place_reviews ORDER BY review_id")
        assert [r[0] for r in cur.fetchall()] == ["Alice Smith", "Bob Lee"]


def test_details_row_carries_provenance_and_survives_a_later_sparse_scrape(db):
    save_bundle(db, _bundle(), STUB, "run-1")
    db.commit()
    sparse = dp.PlaceBundle(place_id="123456789", details={}, status="partial")
    save_bundle(db, sparse, {"cid": "123456789", "name": None}, "run-2")
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT name, rating, timezone, status, source, run_id, scraped_at "
                    "FROM staging_dataextraction.place_details")
        name, rating, tz, status, source, run_id, scraped_at = cur.fetchone()
    assert name == "Acme Dental" and float(rating) == 4.6 and tz == "America/Chicago"  # not wiped by NULLs
    assert status == "partial" and source == "GOOGLE_MAPS" and run_id == "run-2" and scraped_at


def test_suppressor_loads_active_hashes_from_database(db):
    import hashlib
    h = hashlib.sha256(b"jane roe").hexdigest()
    with db.cursor() as cur:
        cur.execute("INSERT INTO kg_audit.suppression_lists (hashed_identifier, identifier_type, reason, is_active) "
                    "VALUES (%s, 'name', 'test', TRUE), (%s, 'name', 'test', FALSE)",
                    (h, hashlib.sha256(b"inactive").hexdigest()))
    db.commit()
    s = Suppressor.load(db)
    assert s("Jane Roe") is True and s("inactive") is False and s(None) is False


def _seed_company(db, cid="123456789", state_code="CA", industry="dentist"):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO staging_dataextraction.staging_companies "
            "(id, name, website, city, state_code, industry, source, raw_payload) "
            "VALUES (%s, 'Acme Dental', 'https://acme.test/', 'San Francisco', %s, %s, 'GOOGLE_MAPS', %s::jsonb)",
            (f"gmaps_{cid}", state_code, industry, json.dumps(
                {"cid": cid, "ftid": "0x1:0x2", "place_id": "ChIJabc", "latitude": 37.77, "longitude": -122.41})))
    db.commit()


def test_select_stubs_by_ids_and_by_region_and_skips_fresh(db):
    _seed_company(db)
    assert [s["cid"] for s in select_stubs(db, {"place_ids": ["gmaps_123456789"]})] == ["123456789"]
    assert [s["cid"] for s in select_stubs(db, {"region": "US-CA", "category": "dent"})] == ["123456789"]
    assert select_stubs(db, {"region": "US-TX"}) == []
    save_bundle(db, _bundle(), STUB, "run-1")
    db.commit()
    assert select_stubs(db, {"region": "US-CA"}) == []  # freshly scraped places are not picked again


def test_run_deep_extraction_end_to_end_and_second_run_adds_nothing(db):
    _seed_company(db)
    req = {"place_ids": ["123456789"], "run_id": "e2e-1", "with_llm": True}
    kw = dict(http_client=FakeHttp(pages=[reviews_response([make_review(0), make_review(1)])]),
              llm=FakeLLM(), crawler=FakeCrawler(SITE_HTML), get_conn=lambda: db,
              release_conn=lambda c: None, delay_range=(0, 0))
    summary = run(run_deep_extraction(req, **kw))
    assert summary["status"] == "complete" and summary["places_done"] == 1 and summary["reviews_saved"] == 2
    assert summary["reviewer_mode"] == "hash"
    before = _counts(db)
    assert before["place_reviews"] == 2 and before["place_contacts"] >= 3 and before["place_people"] >= 1
    kw["http_client"] = FakeHttp(pages=[reviews_response([make_review(0), make_review(1)])])
    again = run(run_deep_extraction({**req, "run_id": "e2e-2"}, **kw))
    assert again["status"] == "complete" and _counts(db) == before
    with db.cursor() as cur:
        cur.execute("SELECT status, places_done, reviews_saved FROM staging_dataextraction.place_extraction_runs "
                    "WHERE run_id = 'e2e-1'")
        assert cur.fetchone() == ("complete", 1, 2)


def test_run_stops_on_block_and_reports_blocked(db):
    _seed_company(db, "111")
    _seed_company(db, "222")
    kw = dict(http_client=FakeHttp(block_details=True), llm=None, crawler=FakeCrawler(SITE_HTML),
              get_conn=lambda: db, release_conn=lambda c: None, delay_range=(0, 0))
    summary = run(run_deep_extraction({"place_ids": ["111", "222"], "run_id": "blk"}, **kw))
    assert summary["status"] == "blocked" and summary["places_blocked"] == 1 and summary["places_done"] == 0
    assert len(kw["http_client"].urls) == 1  # stopped hammering after the first block
    with db.cursor() as cur:
        cur.execute("SELECT status FROM staging_dataextraction.place_details")
        assert cur.fetchone()[0] == "blocked"


def test_dry_run_selects_but_writes_nothing(db):
    _seed_company(db)
    summary = run(run_deep_extraction({"place_ids": ["123456789"], "dry_run": True}, get_conn=lambda: db,
                                      release_conn=lambda c: None))
    assert summary["status"] == "dry_run" and summary["place_ids"] == ["123456789"]
    assert _counts(db)["place_details"] == 0
