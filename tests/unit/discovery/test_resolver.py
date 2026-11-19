"""
Unit tests for packages/discovery/resolver.py and packages/discovery/ranking.py.
Tests:
  - Canonical organization resolution and field trust hierarchy
  - Person entity resolution and association with canonical organizations
  - Suppression list enforcement (Decision D5)
  - Manual seed filtering unless include_unverified=True (Decision D3)
  - Multi-factor ranking
"""

from __future__ import annotations


from packages.discovery.models import (
    FactRecord,
    OrgRecord,
    PersonRecord,
    PhoneEntry,
    SearchIntent,
)
from packages.discovery.ranking import rank_organizations
from packages.discovery.resolver import EntityResolver


def test_entity_resolution_and_trust_hierarchy():
    resolver = EntityResolver()

    # Source 1: Google Maps
    org_gmaps = OrgRecord(
        canonical_name="Bayada Home Health",
        normalized_name="bayada home health",
        category="Home health care service",
        website="https://www.bayada.com",
        domain="bayada.com",
        phones=[PhoneEntry(number="+17045569150")],
        rating=4.2,
        review_count=18,
        sources=[{"source": "google_maps"}],
    )

    # Source 2: CMS Care Compare (Official)
    org_cms = OrgRecord(
        canonical_name="BAYADA HOME HEALTH CARE",
        normalized_name="bayada home health care",
        category="Home Health Agency",
        domain="bayada.com",
        regulatory={
            "cms_star_rating": 4.5,
            "cms_ownership": "Non-profit",
        },
        services=["nursing_care", "physical_therapy"],
        sources=[{"source": "cms_care_compare"}],
    )

    fact_gmaps = FactRecord(
        entity_type="organization",
        entity_id=org_gmaps.id,
        field="rating",
        value=4.2,
        source="google_maps",
    )
    fact_cms = FactRecord(
        entity_type="organization",
        entity_id=org_cms.id,
        field="cms_star_rating",
        value=4.5,
        source="cms_care_compare",
    )

    resolved_orgs, resolved_people, resolved_facts = resolver.resolve(
        raw_orgs=[org_gmaps, org_cms],
        raw_people=[],
        raw_facts=[fact_gmaps, fact_cms],
    )

    assert len(resolved_orgs) == 1
    canonical = resolved_orgs[0]

    # Domain was identical so they merged into 1 canonical org
    assert canonical.domain == "bayada.com"
    assert canonical.website == "https://www.bayada.com"
    assert len(canonical.phones) == 1
    assert canonical.phones[0].number == "+17045569150"
    assert canonical.regulatory.get("cms_star_rating") == 4.5
    assert canonical.regulatory.get("cms_ownership") == "Non-profit"
    assert "nursing_care" in canonical.services

    # Verify facts were remapped to canonical id
    assert len(resolved_facts) == 2
    for f in resolved_facts:
        assert f.entity_id == canonical.id


def test_person_association_and_provenance_gates():
    resolver = EntityResolver()

    org = OrgRecord(
        canonical_name="Senior Helpers of Charlotte",
        normalized_name="senior helpers of charlotte",
        domain="seniorhelpers.com",
    )

    # 1. State licensed administrator (verified)
    admin = PersonRecord(
        full_name="Marcus Holloway",
        normalized_name="marcus holloway",
        title="Agency Director",
        role_type="administrator",
        org_name="Senior Helpers of Charlotte",
        provenance="state_registry",
        verified=True,
    )

    # 2. Manual seed person (Decision D3: must be hidden by default)
    seed_person = PersonRecord(
        full_name="Untrusted Seed Lead",
        normalized_name="untrusted seed lead",
        title="CEO",
        org_name="Senior Helpers of Charlotte",
        provenance="manual_seed",
        verified=False,
    )

    # 3. Suppressed person (Decision D5: must be filtered)
    suppressed_person = PersonRecord(
        full_name="Suppressed Individual",
        normalized_name="suppressed individual",
        title="Executive",
        org_name="Senior Helpers of Charlotte",
        provenance="web_search",
        suppressed=True,
    )

    # Run default resolution (include_unverified=False)
    resolved_orgs, resolved_people, _ = resolver.resolve(
        raw_orgs=[org],
        raw_people=[admin, seed_person, suppressed_person],
        raw_facts=[],
        include_unverified=False,
    )

    assert len(resolved_orgs) == 1
    assert len(resolved_people) == 1
    assert resolved_people[0].full_name == "Marcus Holloway"
    # Admin must be attached to org.people
    assert len(resolved_orgs[0].people) == 1
    assert resolved_orgs[0].people[0].full_name == "Marcus Holloway"

    # Run resolution with include_unverified=True
    _, people_unverified, _ = resolver.resolve(
        raw_orgs=[org],
        raw_people=[admin, seed_person, suppressed_person],
        raw_facts=[],
        include_unverified=True,
    )
    # Manual seed now included, but suppressed remains excluded
    names = [p.full_name for p in people_unverified]
    assert "Untrusted Seed Lead" in names
    assert "Suppressed Individual" not in names


def test_ranking_organizations():
    intent = SearchIntent(
        query="home care agency",
        categories=["home care", "elderly care"],
    )

    org_basic = OrgRecord(
        canonical_name="Random Health Inc",
        normalized_name="random health inc",
    )
    org_certified = OrgRecord(
        canonical_name="Charlotte Home Care Agency",
        normalized_name="charlotte home care agency",
        category="home care",
        regulatory={"nc_license_number": "HC1234", "cms_star_rating": 4.5},
        phones=[PhoneEntry(number="+17045550100")],
        website="https://charlottecare.com",
    )

    ranked = rank_organizations([org_basic, org_certified], intent)
    assert len(ranked) == 2
    assert ranked[0].canonical_name == "Charlotte Home Care Agency"


def test_all_caps_registry_name_uses_mixed_case_spelling_from_same_org():
    cms = OrgRecord(canonical_name="ADORATION HOME HEALTH", normalized_name="adoration home health",
                    regulatory={"cms_certification_number": "345001"}, sources=[{"source": "cms_care_compare"}],
                    address={"postal_code": "28025"})
    gm = OrgRecord(canonical_name="Adoration Home Health", normalized_name="adoration home health",
                   sources=[{"source": "google_maps"}], address={"postal_code": "28025"})
    orgs, _, _ = EntityResolver().resolve([cms, gm], [], [])
    assert len(orgs) == 1
    assert orgs[0].canonical_name == "Adoration Home Health"


def test_directory_domain_does_not_merge_different_organizations():
    from packages.discovery.persistence import stable_org_id
    a = OrgRecord(canonical_name="R S Hospital", normalized_name="r s hospital", domain="hexahealth.com",
                  website="https://www.hexahealth.com/hospitals/r-s-hospital", address={"city": "Coimbatore"},
                  sources=[{"source": "web_search"}])
    b = OrgRecord(canonical_name="Apollo Hospital", normalized_name="apollo hospital", domain="hexahealth.com",
                  website="https://www.hexahealth.com/hospitals/apollo", address={"city": "Coimbatore"},
                  sources=[{"source": "web_search"}])
    orgs, _, _ = EntityResolver().resolve([a, b], [], [])
    assert len(orgs) == 2
    assert stable_org_id(a) != stable_org_id(b)
    c = OrgRecord(canonical_name="Kauvery Hospital", normalized_name="kauvery hospital", domain="kauveryhospital.com")
    d = OrgRecord(canonical_name="Sri Ramakrishna Hospital", normalized_name="sri ramakrishna hospital",
                  domain="kauveryhospital.com")
    assert stable_org_id(c) != stable_org_id(d)    # even a real domain needs the same name for the same stored row
