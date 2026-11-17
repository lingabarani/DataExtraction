"""
Unit tests for packages/leadintel.
Tests:
  - 9-candidate corporate email permutation logic
  - Explicit 'inferred' labelling and confidence scoring
  - Phone extraction and E.164 formatting
  - Verification engine with disposable, role accounts, and syntax gates
  - Team page HTML parser
  - Fast deduplication key generation
"""


from packages.leadintel.email_finder import (
    company_domain,
    generate_email_candidates,
    infer_email_entry,
)
from packages.leadintel.parser import TeamPageParser
from packages.leadintel.phone_finder import PhoneFinder
from packages.leadintel.verification_engine import VerificationEngine
from packages.leadintel.deduplication import generate_company_match_key, generate_person_match_key


def test_email_candidate_permutations():
    candidates = generate_email_candidates("Jane", "Doe", "acmecare.org")
    assert len(candidates) == 9
    assert candidates[0] == "jane.doe@acmecare.org"
    assert candidates[1] == "janedoe@acmecare.org"
    assert candidates[2] == "jane@acmecare.org"
    assert candidates[3] == "jane_doe@acmecare.org"
    assert candidates[4] == "jdoe@acmecare.org"
    assert candidates[5] == "janed@acmecare.org"
    assert candidates[6] == "doe.jane@acmecare.org"
    assert candidates[7] == "j.doe@acmecare.org"
    assert candidates[8] == "doejane@acmecare.org"


def test_company_domain_derivation():
    assert company_domain("https://www.carolinaeldercare.com/about") == "carolinaeldercare.com"
    assert company_domain("carolinaeldercare.com") == "carolinaeldercare.com"
    assert company_domain("Carolina Elder Care") == "carolinaeldercare.com"


def test_infer_email_entry_label_and_confidence(monkeypatch):
    # Mock check_mx_records to return True
    import packages.leadintel.email_finder as ef
    monkeypatch.setattr(ef, "check_mx_records", lambda domain, timeout=4.0: True)

    entry = infer_email_entry("Sarah", "Jenkins", "charlotteseniorcare.org")
    assert entry is not None
    assert entry.value == "sarah.jenkins@charlotteseniorcare.org"
    assert entry.label == "inferred"
    assert entry.confidence == 0.9

    # Derived domain -> confidence 0.6
    entry_derived = infer_email_entry("Sarah", "Jenkins", "charlotteseniorcare.org", is_derived_domain=True)
    assert entry_derived.confidence == 0.6


def test_phone_finder_extraction():
    finder = PhoneFinder()
    sample_text = """
    Contact Charlotte Care: 704-555-0199 or toll-free (800) 555-0123.
    Direct line: +1 704 555 9988.
    """
    phones = finder.extract_from_text(sample_text, default_region="US")
    assert len(phones) >= 2
    e164_numbers = [p["e164"] for p in phones]
    assert "+17045550199" in e164_numbers
    assert "+18005550123" in e164_numbers
    assert any(p["type"] == "toll_free" for p in phones)


def test_verification_engine_checks(monkeypatch):
    import packages.leadintel.verification_engine as ve
    monkeypatch.setattr(ve, "check_mx_records", lambda domain: True)

    engine = VerificationEngine()

    # Valid corporate email
    res1 = engine.verify_email("administrator@carolinahealth.org", check_dns=True)
    assert res1.is_valid_syntax is True
    assert res1.is_role_account is True
    assert res1.status in ("valid", "risky")

    # Disposable email
    res2 = engine.verify_email("fakeuser@mailinator.com", check_dns=False)
    assert res2.is_disposable is True
    assert res2.status == "invalid"

    # Malformed email
    res3 = engine.verify_email("not-an-email", check_dns=False)
    assert res3.is_valid_syntax is False
    assert res3.status == "invalid"


def test_team_page_parser():
    parser = TeamPageParser()
    html = """
    <div class="team-container">
        <div class="team-member">
            <h3>Dr. Robert King</h3>
            <p>Executive Director & Owner</p>
            <p>Email: rking@kingcare.org | Phone: (704) 555-4321</p>
        </div>
        <div class="team-member">
            <h3>Linda Gomez, RN</h3>
            <p>Director of Nursing</p>
            <p>Email: lgomez@kingcare.org</p>
        </div>
    </div>
    """
    members = parser.parse_team_members(html, source_url="https://kingcare.org/team")
    assert len(members) == 2

    m1 = members[0]
    assert m1["full_name"] == "Dr. Robert King"
    assert m1["role_type"] == "owner"
    assert "rking@kingcare.org" in m1["emails"]
    assert "+17045554321" in m1["phones"]

    m2 = members[1]
    assert m2["full_name"] == "Linda Gomez, RN"
    assert m2["role_type"] == "director_of_nursing"


def test_deduplication_keys():
    k1 = generate_company_match_key("Charlotte Senior Living, Inc.", "charlotteseniorcare.org", "+17045550199")
    k2 = generate_company_match_key("Charlotte Senior Living LLC", "charlotteseniorcare.org")
    assert k1 == k2

    p1 = generate_person_match_key("Dr. Robert King", "Charlotte Senior Living", "rking@care.org")
    p2 = generate_person_match_key("Robert King", "Different Org", "rking@care.org")
    assert p1 == p2
