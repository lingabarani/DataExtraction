"""
Unit Tests for Enterprise B2B Intelligence & Buying Committee Classification
============================================================================
Verifies:
  1. Technographics detection from HTML DOM and DNS signatures.
  2. Synthesized buyer intent scoring, strength levels, and buying stages.
  3. Individual lead propensity scoring and explainable reasoning.
  4. Buying committee role classification and org chart hierarchy reconstruction.
  5. In-place database schema enhancements and public view integrity.
"""

import pytest
from packages.domain.intelligence_enricher import intelligence_enricher, B2BIntelligenceEnricher
from packages.domain.buying_committee_classifier import buying_committee_classifier, BuyingCommitteeClassifier
from packages.infrastructure.db_connector import get_db_connection


def test_technographics_detection():
    # 1. HTML script signatures
    sample_html = """
    <html>
      <head>
        <script src="https://js.hs-scripts.com/12345.js"></script>
        <script src="https://js.stripe.com/v3/"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
      </head>
      <body><h1>Welcome to SaaS Corp</h1></body>
    </html>
    """
    detected = intelligence_enricher.detect_technologies_from_web(html_content=sample_html)
    names = {t["name"] for t in detected}
    categories = {t["category"] for t in detected}

    assert "HubSpot" in names
    assert "Stripe" in names
    assert "CRM" in categories
    assert "Payment Processing" in categories

    # 2. DNS heuristics
    sample_dns = ["aspmx.l.google.com", "google-site-verification=abc", "10.0.0.1"]
    detected_dns = intelligence_enricher.detect_technologies_from_web(dns_records=sample_dns)
    dns_names = {t["name"] for t in detected_dns}
    assert "Google Cloud Platform" in dns_names


def test_synthesize_organization_intent():
    # 1. Surging Intent: high hiring velocity + recent funding
    res = intelligence_enricher.synthesize_organization_intent(
        hiring_velocity=8,
        total_funding_usd=15_000_000.0,
        headcount_growth_6m=25.0,
        detected_tech=[{"category": "Cloud Infrastructure"}, {"category": "CRM"}],
    )
    assert res["intent_score"] >= 0.75
    assert res["intent_strength"] == "SURGING"
    assert res["buying_stage"] == "Decision"
    assert "Talent Acquisition & Hiring" in res["intent_topics"]
    assert "Capital Investment & Growth" in res["intent_topics"]
    assert "Cloud Services & Infrastructure" in res["intent_topics"]

    # 2. Cold / None Intent: zero hiring, zero funding
    cold = intelligence_enricher.synthesize_organization_intent(hiring_velocity=0)
    assert cold["intent_score"] == 0.0
    assert cold["intent_strength"] == "NONE"
    assert cold["buying_stage"] == "Cold"


def test_compute_lead_propensity():
    # High-tier economic buyer at high-intent account with verified email
    lead_eval = intelligence_enricher.compute_lead_propensity(
        person_title="Chief Financial Officer",
        buying_role="ECONOMIC_BUYER",
        email_status="VERIFIED",
        org_intent_score=0.85,
        org_employee_max=500,
    )
    assert lead_eval["propensity_to_buy_score"] >= 0.85
    assert lead_eval["lead_grade"] == "A+"
    assert lead_eval["is_likely_to_engage"] is True
    assert len(lead_eval["score_reasoning"]["reasons"]) >= 3


def test_buying_committee_classification():
    # Economic Buyer
    role, level = buying_committee_classifier.classify_title("Chief Financial Officer")
    assert role == "ECONOMIC_BUYER"
    assert level == "C_SUITE"

    # Technical Evaluator
    role, level = buying_committee_classifier.classify_title("VP of Engineering")
    assert role == "TECHNICAL_EVALUATOR"
    assert level == "VP"

    # Champion
    role, level = buying_committee_classifier.classify_title("Staff DevOps Engineer")
    assert role == "CHAMPION"
    assert level == "INDIVIDUAL_CONTRIBUTOR"

    # Blocker
    role, level = buying_committee_classifier.classify_title("Director of Procurement & Vendor Relations")
    assert role == "BLOCKER"
    assert level == "DIRECTOR"


def test_org_chart_reconstruction():
    roster = [
        {"id": "p1", "title": "Chief Executive Officer", "department": "Executive"},
        {"id": "p2", "title": "VP of Engineering", "department": "Engineering"},
        {"id": "p3", "title": "Engineering Director", "department": "Engineering"},
        {"id": "p4", "title": "Senior Software Engineer", "department": "Engineering"},
        {"id": "p5", "title": "Chief Financial Officer", "department": "Finance"},
    ]

    reconstructed = buying_committee_classifier.reconstruct_org_chart(roster)
    lookup = {e["id"]: e for e in reconstructed}

    # CEO is top leader (depth 1, reports to None)
    assert lookup["p1"]["reports_to_person_id"] is None
    assert lookup["p1"]["org_chart_depth"] == 1

    # VP Engineering reports to CEO (p1)
    assert lookup["p2"]["reports_to_person_id"] == "p1"
    assert lookup["p2"]["org_chart_depth"] == 2

    # Engineering Director reports to VP Engineering (p2)
    assert lookup["p3"]["reports_to_person_id"] == "p2"
    assert lookup["p3"]["org_chart_depth"] == 3

    # Senior Engineer reports to Engineering Director (p3)
    assert lookup["p4"]["reports_to_person_id"] == "p3"
    assert lookup["p4"]["org_chart_depth"] == 4


def test_database_schema_and_views_integrity():
    """Verify that in-place migration 021 columns and views are queryable without errors."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # 1. Check master organizations columns
            cur.execute("""
                SELECT tech_categories, primary_crm, primary_cloud, intent_score,
                       intent_strength, intent_topics, buying_stage, recent_hiring_velocity
                FROM master_dataextraction.organizations
                LIMIT 1;
            """)
            org_row = cur.fetchone()
            assert org_row is not None

            # 2. Check master persons columns
            cur.execute("""
                SELECT reports_to_person_id, management_level, buying_role,
                       propensity_to_buy_score, lead_grade, score_reasoning
                FROM master_dataextraction.persons
                LIMIT 1;
            """)
            person_row = cur.fetchone()
            assert person_row is not None

            # 3. Check public.companies view
            cur.execute("""
                SELECT id, name, tech_categories, primary_crm, intent_score, intent_strength
                FROM public.companies
                LIMIT 1;
            """)
            assert cur.fetchone() is not None

            # 4. Check public.us_leads view
            cur.execute("""
                SELECT id, full_name, buying_role, management_level, propensity_to_buy_score, intent_strength
                FROM public.us_leads
                LIMIT 1;
            """)
            assert cur.fetchone() is not None
