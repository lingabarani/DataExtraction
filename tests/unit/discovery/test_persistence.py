"""
Persistence, suppression, restart survival and resolver behaviour against a real *test* PostgreSQL database.
Skipped unless the configured database name contains "test" (set DEX_SKIP_DOTENV=true and POSTGRES_DB=dex_ai_test).
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from packages.discovery.models import (
    EmailEntry, FactRecord, OrgRecord, PersonRecord, PhoneEntry, SearchIntent, SourceResult, SourceStatus,
)
from packages.discovery.orchestrator import DiscoveryOrchestrator
from packages.discovery.persistence import get_search_run, persist_discovery_search
from packages.discovery.resolver import EntityResolver
from packages.discovery import suppression


def _org(name="Test Care One", zip5="28202", phone="7045550101", domain=None, **kw):
    return OrgRecord(name=name, category="home care", address={"street": "1 Test Way", "city": "Charlotte", "state": "NC",
                                                              "postal_code": zip5},
                     phones=[PhoneEntry(number=phone)] if phone else [], domain=domain,
                     website=f"https://{domain}" if domain else None, quality_score=0.8, **kw)


def _counts(db):
    with db.cursor() as cur:
        out = {}
        for t in ("organizations", "people", "facts", "search_runs", "search_results"):
            cur.execute(f"SELECT COUNT(*) FROM discovery_dataextraction.{t}")
            out[t] = cur.fetchone()[0]
    return out


def test_persist_writes_all_tables_and_repeat_does_not_duplicate(db, persist):
    org = _org(regulatory={"cms_ccn": "349999"})
    person = PersonRecord(name="Alex Testperson", title="Administrator", org_id=org.id, org_name=org.name)
    fact = FactRecord(entity_type="organization", entity_id=org.id, field="cms_certification",
                      value={"ccn": "349999"}, source="cms_care_compare", source_url="https://data.cms.gov/x")
    r1 = persist_discovery_search(str(uuid.uuid4()), "q", SearchIntent(query="q"), [org], [person], [fact],
                                  [SourceStatus(name="cms_care_compare", status="ok", count=1)])
    assert r1.ok, r1.error
    first = _counts(db)
    assert first == {"organizations": 1, "people": 1, "facts": 1, "search_runs": 1, "search_results": 2}

    # Same real organization found again by a new search (new in-memory ids): rows are reused.
    org2 = _org(regulatory={"cms_ccn": "349999"}, rating=4.4, review_count=10)
    person2 = PersonRecord(name="Alex Testperson", title="Administrator", org_id=org2.id, org_name=org2.name)
    r2 = persist_discovery_search(str(uuid.uuid4()), "q", SearchIntent(query="q"), [org2], [person2], [],
                                  [SourceStatus(name="google_maps", status="ok", count=1)])
    assert r2.ok and r2.org_ids[org2.id] == r1.org_ids[org.id]
    second = _counts(db)
    assert second["organizations"] == 1 and second["people"] == 1 and second["search_runs"] == 2
    with db.cursor() as cur:
        cur.execute("SELECT rating, review_count FROM discovery_dataextraction.organizations")
        rating, reviews = cur.fetchone()
        assert float(rating) == pytest.approx(4.4) and reviews == 10


def test_suppressed_person_is_never_written(db, persist):
    with db.cursor() as cur:
        cur.execute("INSERT INTO kg_audit.suppression_lists (hashed_identifier) VALUES (%s)",
                    (hashlib.sha256(b"pat suppressed").hexdigest(),))
    db.commit()
    suppression.load_suppression_hashes(force=True)
    org = _org()
    keep = PersonRecord(name="Kim Visible", org_id=org.id, org_name=org.name)
    drop = PersonRecord(name="Pat Suppressed", org_id=org.id, org_name=org.name,
                        emails=[EmailEntry(value="pat@test.example", label="found")])
    fact = FactRecord(entity_type="person", entity_id=drop.id, field="title", value="x", source="website_crawl")
    res = persist_discovery_search(str(uuid.uuid4()), "q", SearchIntent(query="q"), [org], [keep, drop], [fact], [])
    assert res.ok
    with db.cursor() as cur:
        cur.execute("SELECT full_name FROM discovery_dataextraction.people")
        assert [r[0] for r in cur.fetchall()] == ["Kim Visible"]
        cur.execute("SELECT COUNT(*) FROM discovery_dataextraction.facts WHERE entity_type = 'person'")
        assert cur.fetchone()[0] == 0


class _Src:
    def __init__(self, name, orgs):
        self.name, self._orgs = name, orgs

    async def search(self, intent, budget):
        yield SourceResult(organizations=[o.model_copy(deep=True) for o in self._orgs],
                           status=SourceStatus(name=self.name, status="ok", count=len(self._orgs)))


@pytest.mark.anyio
async def test_search_survives_restart_and_detail_ids_match(db, persist):
    orgs = [_org("Test Care One", domain="testcare-one.example"), _org("Test Care Two", zip5="28203", phone="7045550102")]
    o1 = DiscoveryOrchestrator(sources=[_Src("google_maps", orgs)])
    o1.website_crawler = o1.linkedin_source = None
    run_id = str(uuid.uuid4())
    answer = await o1.search("home care in Charlotte NC", budget_seconds=10, search_id=run_id)
    assert answer.total_organizations == 2

    stored = get_search_run(run_id)                     # "restart": read back from the database only
    assert stored and stored["total_organizations"] == 2 and len(stored["cards"]) == 2
    with db.cursor() as cur:
        cur.execute("SELECT id::text FROM discovery_dataextraction.organizations")
        db_ids = {r[0] for r in cur.fetchall()}
    assert {c.org_id for c in answer.cards} == db_ids  # card ids are the stored ids (detail pages work)

    # A second, identical search creates a new run but no duplicate organizations
    o2 = DiscoveryOrchestrator(sources=[_Src("google_maps", orgs)])
    o2.website_crawler = o2.linkedin_source = None
    await o2.search("home care in Charlotte NC", budget_seconds=10)
    c = _counts(db)
    assert c["organizations"] == 2 and c["search_runs"] == 2


def test_resolver_merges_by_phone_and_address_but_not_branches():
    gm = OrgRecord(name="Preferred Care at Home of Charlotte South", category="Home health care service",
                   address={"street": "6201 Fairview Rd #236", "city": "Charlotte", "state": "NC", "postal_code": "28210"},
                   phones=[PhoneEntry(number="+17046261237")], rating=5.0, review_count=34,
                   sources=[{"source": "google_maps"}])
    reg = OrgRecord(name="Preferred Care at Home Of Charlotte South", category="Home Care Agency",
                    address={"street": "6201 Fairview Road, St #236", "city": "Charlotte", "state": "NC",
                             "postal_code": "28210"},
                    phones=[PhoneEntry(number="(704) 626-1237")], regulatory={"nc_license_number": "HC0000"},
                    sources=[{"source": "state_registry"}])
    branch = OrgRecord(name="Preferred Care at Home of Charlotte North", category="Home Care Agency",
                       address={"street": "9 Other St", "city": "Huntersville", "state": "NC", "postal_code": "28078"},
                       phones=[PhoneEntry(number="(704) 555-0199")], sources=[{"source": "state_registry"}])
    orgs, _, _ = EntityResolver().resolve([gm, reg, branch], [], [])
    assert len(orgs) == 2
    merged = next(o for o in orgs if o.regulatory.get("nc_license_number") == "HC0000")
    assert merged.rating == 5.0 and merged.review_count == 34              # Google rating kept
    assert merged.category == "Home Care Agency"                           # official registry wins the display value
    assert len(merged.phones) == 1                                          # same number in two formats


def test_resolver_does_not_merge_unrelated_orgs_sharing_a_phone():
    a = OrgRecord(name="Alpha Test Plumbing", phones=[PhoneEntry(number="7045550000")], sources=[{"source": "web_search"}])
    b = OrgRecord(name="Zeta Test Bakery", phones=[PhoneEntry(number="704-555-0000")], sources=[{"source": "google_maps"}])
    orgs, _, _ = EntityResolver().resolve([a, b], [], [])
    assert len(orgs) == 2
