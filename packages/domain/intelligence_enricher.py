"""
DataExtraction — Enterprise B2B Intelligence & Technographics Enrichment Engine
==============================================================================
Provides automated technographic detection and buyer intent synthesis:
  1. Technographic Detection:
     - DNS heuristics (MX, SPF, TXT) for Email Providers, Cloud Workspace, and Security.
     - HTML/DOM heuristics for CRM, Analytics, Marketing Automation, and Billing.
  2. Intent Signal Synthesis:
     - Computes normalized intent score (0.0000 - 1.0000) based on hiring velocity,
       technographic signals, and funding recency.
     - Categorizes intent strength: 'NONE', 'LOW', 'MEDIUM', 'HIGH', 'SURGING'.
     - Infers buying stage: 'Cold', 'Awareness', 'Consideration', 'Decision'.
  3. Lead Propensity & Grading:
     - Computes propensity-to-buy and letter grade (A+, A, B, C, D) with explainable reasoning.
"""

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("dataextraction.domain.intelligence_enricher")

# Canonical B2B Technology Signatures (Vendor, Category, Detection Regex)
KNOWN_TECHNOLOGY_SIGNATURES: List[Dict[str, Any]] = [
    # CRM & Sales Automation
    {
        "name": "Salesforce",
        "category": "CRM",
        "vendor": "Salesforce.com, Inc.",
        "html_regex": re.compile(r"(salesforce\.com|force\.com|hs-salesforce)", re.I),
        "dns_regex": re.compile(r"(salesforce|force\.com)", re.I),
    },
    {
        "name": "HubSpot",
        "category": "CRM",
        "vendor": "HubSpot, Inc.",
        "html_regex": re.compile(r"(js\.hs-scripts\.com|js\.hsforms\.net|hubspot\.com)", re.I),
        "dns_regex": re.compile(r"(hubspot|hubspotemail)", re.I),
    },
    {
        "name": "Zoho CRM",
        "category": "CRM",
        "vendor": "Zoho Corporation",
        "html_regex": re.compile(r"(zohocdn\.com|zoho\.com/crm)", re.I),
        "dns_regex": re.compile(r"(zoho\.com|zohomail)", re.I),
    },
    # Cloud Infrastructure & Hosting
    {
        "name": "Amazon Web Services (AWS)",
        "category": "Cloud Infrastructure",
        "vendor": "Amazon.com, Inc.",
        "html_regex": re.compile(r"(amazonaws\.com|cloudfront\.net)", re.I),
        "dns_regex": re.compile(r"(awsdns|amazonses\.com)", re.I),
    },
    {
        "name": "Google Cloud Platform",
        "category": "Cloud Infrastructure",
        "vendor": "Google LLC",
        "html_regex": re.compile(r"(storage\.googleapis\.com|firebaseapp\.com)", re.I),
        "dns_regex": re.compile(r"(google-site-verification|aspmx\.l\.google\.com)", re.I),
    },
    {
        "name": "Microsoft Azure",
        "category": "Cloud Infrastructure",
        "vendor": "Microsoft Corporation",
        "html_regex": re.compile(r"(azurewebsites\.net|azureedge\.net)", re.I),
        "dns_regex": re.compile(r"(outlook\.com|microsoft\.com|protection\.outlook)", re.I),
    },
    {
        "name": "Cloudflare",
        "category": "Cloud Infrastructure",
        "vendor": "Cloudflare, Inc.",
        "html_regex": re.compile(r"(cloudflare\.com|cdnjs\.cloudflare\.com)", re.I),
        "dns_regex": re.compile(r"(cloudflare\.com)", re.I),
    },
    # Payment & Billing
    {
        "name": "Stripe",
        "category": "Payment Processing",
        "vendor": "Stripe, Inc.",
        "html_regex": re.compile(r"(js\.stripe\.com|checkout\.stripe\.com)", re.I),
        "dns_regex": None,
    },
    # Analytics & Behavioral Tracking
    {
        "name": "Google Analytics 4",
        "category": "Analytics",
        "vendor": "Google LLC",
        "html_regex": re.compile(r"(googletagmanager\.com/gtag/js|google-analytics\.com/analytics\.js)", re.I),
        "dns_regex": None,
    },
    {
        "name": "Segment",
        "category": "Customer Data Platform",
        "vendor": "Twilio, Inc.",
        "html_regex": re.compile(r"(cdn\.segment\.com/analytics\.js)", re.I),
        "dns_regex": None,
    },
    {
        "name": "Hotjar",
        "category": "User Experience Analytics",
        "vendor": "Hotjar Ltd.",
        "html_regex": re.compile(r"(static\.hotjar\.com)", re.I),
        "dns_regex": None,
    },
    # Customer Support & Chat
    {
        "name": "Intercom",
        "category": "Customer Communication",
        "vendor": "Intercom, Inc.",
        "html_regex": re.compile(r"(widget\.intercom\.io|intercomcdn\.com)", re.I),
        "dns_regex": None,
    },
    {
        "name": "Zendesk",
        "category": "Customer Support",
        "vendor": "Zendesk, Inc.",
        "html_regex": re.compile(r"(assets\.zendesk\.com|zdassets\.com)", re.I),
        "dns_regex": re.compile(r"(zendesk\.com)", re.I),
    },
]


class B2BIntelligenceEnricher:
    """
    Enriches organization records with technographics and synthesizes predictive intent.
    """

    @classmethod
    def detect_technologies_from_web(
        cls,
        html_content: Optional[str] = None,
        dns_records: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Detects installed B2B technologies using DOM script/meta regex and DNS hostnames.
        """
        detected: List[Dict[str, Any]] = []
        html_str = html_content or ""
        dns_list = dns_records or []
        combined_dns = " ".join(dns_list)

        seen_names: Set[str] = set()

        for sig in KNOWN_TECHNOLOGY_SIGNATURES:
            name = sig["name"]
            if name in seen_names:
                continue

            vector = None
            confidence = 0.0

            # 1. HTML DOM check
            if sig.get("html_regex") and html_str and sig["html_regex"].search(html_str):
                vector = "HTML_SCRIPT"
                confidence = 0.95
            # 2. DNS record check
            elif sig.get("dns_regex") and combined_dns and sig["dns_regex"].search(combined_dns):
                vector = "DNS_RECORD"
                confidence = 0.90

            if vector:
                seen_names.add(name)
                detected.append({
                    "name": name,
                    "category": sig["category"],
                    "vendor": sig["vendor"],
                    "detected_via": vector,
                    "confidence": confidence,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                })

        return detected

    @classmethod
    def synthesize_organization_intent(
        cls,
        hiring_velocity: int = 0,
        detected_tech: Optional[List[Dict[str, Any]]] = None,
        total_funding_usd: Optional[float] = None,
        headcount_growth_6m: Optional[float] = None,
        recent_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Computes composite intent score (0.0000 - 1.0000), strength, topics, and buying stage.
        """
        tech_list = detected_tech or []
        events_list = recent_events or []
        topics: Set[str] = set()
        signals_detail: List[Dict[str, Any]] = []

        base_intent = 0.0

        # 1. Hiring Velocity Signal
        if hiring_velocity > 0:
            job_boost = min(0.40, hiring_velocity * 0.05)
            base_intent += job_boost
            topics.add("Talent Acquisition & Hiring")
            if hiring_velocity >= 5:
                topics.add("Engineering Expansion")
            signals_detail.append({
                "signal": "HIRING_VELOCITY",
                "open_roles": hiring_velocity,
                "weight": round(job_boost, 4),
            })

        # 2. Funding Freshness Signal
        if total_funding_usd and total_funding_usd > 0:
            funding_boost = 0.30 if total_funding_usd >= 5_000_000 else 0.15
            base_intent += funding_boost
            topics.add("Capital Investment & Growth")
            signals_detail.append({
                "signal": "RECENT_FUNDING",
                "amount_usd": total_funding_usd,
                "weight": funding_boost,
            })

        # 3. Headcount Growth Surge
        if headcount_growth_6m and headcount_growth_6m > 0:
            growth_boost = min(0.20, float(headcount_growth_6m) / 100.0)
            base_intent += growth_boost
            topics.add("Organizational Scaling")
            signals_detail.append({
                "signal": "HEADCOUNT_GROWTH",
                "growth_pct": headcount_growth_6m,
                "weight": round(growth_boost, 4),
            })

        # 4. Technographic Inferences
        categories = {t.get("category") for t in tech_list if t.get("category")}
        if "Cloud Infrastructure" in categories:
            topics.add("Cloud Services & Infrastructure")
        if "CRM" in categories:
            topics.add("Sales Acceleration & CRM")

        # Normalize score into [0.0000, 1.0000]
        final_score = round(min(1.0000, max(0.0000, base_intent)), 4)

        # Categorize strength & buying stage
        if final_score >= 0.75:
            strength = "SURGING"
            stage = "Decision"
        elif final_score >= 0.50:
            strength = "HIGH"
            stage = "Consideration"
        elif final_score >= 0.25:
            strength = "MEDIUM"
            stage = "Awareness"
        elif final_score > 0.0:
            strength = "LOW"
            stage = "Cold"
        else:
            strength = "NONE"
            stage = "Cold"

        return {
            "intent_score": final_score,
            "intent_strength": strength,
            "intent_topics": sorted(list(topics)),
            "buying_stage": stage,
            "intent_signals_detail": signals_detail,
        }

    @classmethod
    def compute_lead_propensity(
        cls,
        person_title: Optional[str] = None,
        buying_role: Optional[str] = None,
        email_status: Optional[str] = None,
        org_intent_score: float = 0.0,
        org_employee_max: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Calculates individual lead propensity to engage and buy (0.0000 - 1.0000) with grade.
        """
        score = 0.0
        reasons: List[str] = []

        # 1. Buying Role Weight
        role = str(buying_role or "").upper()
        if role in ("ECONOMIC_BUYER", "DECISION_MAKER"):
            score += 0.40
            reasons.append(f"Senior decision maker role ({role})")
        elif role == "TECHNICAL_EVALUATOR":
            score += 0.35
            reasons.append("Technical evaluation authority")
        elif role == "CHAMPION":
            score += 0.30
            reasons.append("High internal adoption influencer (Champion)")
        else:
            score += 0.15

        # 2. Account Intent Surge
        if org_intent_score >= 0.70:
            score += 0.35
            reasons.append("Company is in an active surge buying window")
        elif org_intent_score >= 0.40:
            score += 0.20
            reasons.append("Company exhibits moderate purchase intent")

        # 3. Direct Contact Deliverability
        if str(email_status or "").upper() == "VERIFIED":
            score += 0.15
            reasons.append("Direct corporate email is SMTP verified")
        elif str(email_status or "").upper() == "PROBABLE":
            score += 0.08

        # 4. Company Ideal Customer Profile (ICP) Fit
        emp = org_employee_max or 50
        if 50 <= emp <= 2500:
            score += 0.10
            reasons.append("Mid-Market to Enterprise optimal company size")

        final_propensity = round(min(1.0000, max(0.0000, score)), 4)

        # Compute Letter Grade
        if final_propensity >= 0.85:
            grade = "A+"
            engage = True
        elif final_propensity >= 0.70:
            grade = "A"
            engage = True
        elif final_propensity >= 0.50:
            grade = "B"
            engage = True
        elif final_propensity >= 0.30:
            grade = "C"
            engage = False
        else:
            grade = "D"
            engage = False

        return {
            "propensity_to_buy_score": final_propensity,
            "lead_grade": grade,
            "is_likely_to_engage": engage,
            "score_reasoning": {
                "reasons": reasons,
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            },
        }


intelligence_enricher = B2BIntelligenceEnricher()
