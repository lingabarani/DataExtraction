"""
DataExtraction — Bayesian Trust & Governance Scoring Engine
============================================================
Computes multi-source Bayesian trust scores, data quality scores, and
enforces OFAC/AML sanctions and compliance suppression checks for entities in
staging_dataextraction.working_organizations.

Certification Thresholds:
  - Quality Score: >= 80 (0 - 100)
  - Trust Score:   >= 0.8500 (0.0000 - 1.0000)
  - Sanctions:     CLEAR (Not present in kg_audit.suppression_lists)
"""

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from packages.domain.compliance_manager import ComplianceManager
from packages.pipeline.bayesian_quality_engine import bayesian_quality_engine

logger = logging.getLogger("dataextraction.domain.trust_engine")

SOURCE_TRUST_PRIORS: Dict[str, float] = {
    "GLEIF_LEI": 0.9900,
    "SEC_EDGAR": 0.9800,
    "SAM_GOV": 0.9500,
    "CMS_NPI": 0.9500,
    "IRS_990": 0.9400,
    "STATE_REGISTRY": 0.9200,
    "REGISTRY": 0.9000,
    "AGENT_3_SPLINK": 0.9500,
    "LINKEDIN": 0.9000,
    "OPENSTREETMAP": 0.8800,
    "GOOGLE_MAPS": 0.8500,
    "WEBSITE_CRAWL": 0.7000,
    "DIRECTORY_CRAWLER": 0.6500,
    "GENERIC_WEB": 0.5000,
}


class TrustAndGovernanceEngine:
    """
    Evaluates pre-master entities for certification and promotion.
    """

    def __init__(self, priors: Optional[Dict[str, float]] = None):
        self.priors = dict(SOURCE_TRUST_PRIORS)
        if priors:
            self.priors.update(priors)

    def get_source_prior(self, source_name: str) -> float:
        """Looks up calibrated prior probability for a source."""
        s_upper = str(source_name).strip().upper()
        for key, weight in self.priors.items():
            if key in s_upper:
                return weight
        return 0.6500

    def compute_trust_score(
        self,
        contributing_sources: List[str],
        identity_confidence: float = 1.0,
        has_statutory_id: bool = False,
    ) -> float:
        """
        Calculates normalized Bayesian trust score:
        Combines multi-source corroboration posterior with statutory identity verification.
        P(Truth | S1...Sk) = 1 - Prod(1 - P(Si))
        """
        sources = [s for s in contributing_sources if s] if contributing_sources else ["REGISTRY"]
        prob_error = 1.0
        for src in set(sources):
            prior = self.get_source_prior(src)
            prob_error *= (1.0 - prior)

        base_posterior = 1.0 - prob_error

        # Factor in Splink / entity resolution identity confidence
        id_factor = min(1.0, max(0.5, float(identity_confidence)))

        # Statutory identity bonus (EIN/RFC/CIK verified)
        statutory_bonus = 0.05 if has_statutory_id else 0.0

        raw_trust = (base_posterior * id_factor) + statutory_bonus
        return round(min(0.9999, max(0.1000, raw_trust)), 4)

    def evaluate_organization(self, org_row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates a working_organizations record against the Certification Gate.
        Returns:
            {
                "data_quality_score": int (0-100),
                "trust_score": float (0.0-1.0),
                "is_suppressed": bool,
                "is_certified": bool,
                "governance_status": "APPROVED" | "QUARANTINED",
                "quarantine_reason": Optional[str],
                "score_breakdown": dict
            }
        """
        enriched_row = dict(org_row)

        # Unpack phones if serialized
        phones = enriched_row.get("phones")
        if isinstance(phones, str) and phones.strip().startswith("["):
            try:
                enriched_row["phones"] = json.loads(phones)
            except Exception:
                pass

        # Unpack locations if serialized or nested
        locations = enriched_row.get("locations")
        if isinstance(locations, str) and locations.strip().startswith("["):
            try:
                locations = json.loads(locations)
                enriched_row["locations"] = locations
            except Exception:
                pass
        if isinstance(locations, list) and locations:
            first_loc = locations[0]
            if isinstance(first_loc, dict):
                enriched_row.setdefault("city", first_loc.get("city"))
                enriched_row.setdefault("formatted_address", first_loc.get("formatted_address") or first_loc.get("address"))
                enriched_row.setdefault("latitude", first_loc.get("latitude") or first_loc.get("lat"))
                enriched_row.setdefault("longitude", first_loc.get("longitude") or first_loc.get("lng"))

        # Map email reachability
        if not enriched_row.get("emails"):
            if enriched_row.get("email_verification_status") in ("COMPLETED", "VERIFIED") or enriched_row.get("verified_email"):
                enriched_row["emails"] = [f"info@{enriched_row.get('primary_domain', 'domain.com')}"]

        sources = enriched_row.get("contributing_sources") or ["REGISTRY"]
        if isinstance(sources, str):
            sources = [sources]

        tax_id = enriched_row.get("statutory_tax_id")
        has_tax = bool(tax_id and str(tax_id).strip())
        id_conf = float(enriched_row.get("identity_confidence") or 1.0)

        # 1. Compute Bayesian Quality Score (0-100)
        quality_eval = bayesian_quality_engine.compute_entity_quality_score(
            entity_data=enriched_row,
            entity_type="organization",
            contributing_sources=sources,
        )
        quality_score = int(quality_eval.get("data_quality_score", 0))

        # 2. Compute Bayesian Trust Score (0.0-1.0)
        trust_score = self.compute_trust_score(
            contributing_sources=sources,
            identity_confidence=id_conf,
            has_statutory_id=has_tax,
        )

        # 3. Check Compliance & Sanctions Lists
        domain = enriched_row.get("primary_domain") or ""
        name = enriched_row.get("legal_name") or enriched_row.get("display_name") or ""
        is_suppressed = False
        suppression_reason = None

        if domain and ComplianceManager.is_suppressed(domain):
            is_suppressed = True
            suppression_reason = f"Domain {domain} present in compliance suppression list"
        elif tax_id and ComplianceManager.is_suppressed(tax_id):
            is_suppressed = True
            suppression_reason = f"Tax ID {tax_id} present in compliance suppression list"
        elif name and ComplianceManager.is_suppressed(name):
            is_suppressed = True
            suppression_reason = f"Legal name {name} present in compliance suppression list"

        # 4. Mandatory Certification Gate Rule:
        # Quality >= 80, Trust >= 0.8500, Sanctions CLEAR
        is_certified = (quality_score >= 80 and trust_score >= 0.8500 and not is_suppressed)
        
        quarantine_reasons = []
        if quality_score < 80:
            quarantine_reasons.append(f"Quality score {quality_score} < 80")
        if trust_score < 0.8500:
            quarantine_reasons.append(f"Trust score {trust_score:.4f} < 0.8500")
        if is_suppressed:
            quarantine_reasons.append(suppression_reason or "Sanction/Compliance suppressed")

        gov_status = "APPROVED" if is_certified else "QUARANTINED"
        q_reason = "; ".join(quarantine_reasons) if quarantine_reasons else None

        return {
            "data_quality_score": quality_score,
            "trust_score": trust_score,
            "is_suppressed": is_suppressed,
            "is_certified": is_certified,
            "governance_status": gov_status,
            "quarantine_reason": q_reason,
            "score_breakdown": quality_eval.get("score_breakdown", {}),
        }


trust_engine = TrustAndGovernanceEngine()
