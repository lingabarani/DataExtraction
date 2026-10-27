"""
DataExtraction — Bayesian Data Quality & Field-Level Lineage Engine
===================================================================
Provides principled probabilistic data fusion and quality scoring for
Apollo.io / ZoomInfo scale knowledge graph entities.

Mathematical Foundations:
  1. Source Authority Priors:
     Pre-calibrated credibility weights reflecting regulatory rigor.
  2. Bayesian Corroboration:
     Multi-source agreement updates posterior probability of truth:
     P(True | S_1, ..., S_k) = 1 - \\prod_{i=1}^k (1 - P(S_i))
  3. Entropy / Conflict Detection:
     Quantifies informational divergence when sources dispute attributes.
  4. Composite Enterprise Quality Metric (0 - 100):
     Measures completeness, verification certainty, geospatial precision,
     and corroboration.
"""

import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("dataextraction.quality.bayesian")

# Pre-calibrated source authority priors P(Source Is Accurate)
DEFAULT_SOURCE_AUTHORITIES: Dict[str, float] = {
    "GLEIF_LEI": 0.99,
    "SEC_EDGAR": 0.98,
    "SAM_GOV": 0.95,
    "IRS_990": 0.94,
    "CMS_NPI": 0.93,
    "STATE_REGISTRY": 0.92,
    "LINKEDIN": 0.90,
    "OPENSTREETMAP": 0.88,
    "GOOGLE_MAPS": 0.85,
    "YELLOWPAGES": 0.70,
    "DIRECTORY_CRAWLER": 0.65,
    "GENERIC_WEB": 0.50,
}


class BayesianQualityEngine:
    """
    Probabilistic data quality scoring and field-level lineage arbiter.
    """

    def __init__(self, source_authorities: Optional[Dict[str, float]] = None):
        self.authorities = dict(DEFAULT_SOURCE_AUTHORITIES)
        if source_authorities:
            self.authorities.update(source_authorities)

    def get_source_authority(self, source_name: str) -> float:
        """
        Returns calibrated prior probability for a given data source.
        """
        src_upper = str(source_name).strip().upper()
        # Prefix matching (e.g. "SEC_EDGAR_BULK" -> "SEC_EDGAR")
        for key, weight in self.authorities.items():
            if key in src_upper:
                return weight
        return 0.60

    def compute_corroborated_confidence(self, sources: List[str]) -> float:
        """
        Calculates posterior probability of truth under independent source observations:
        P = 1 - Prod(1 - P(S_i))
        """
        if not sources:
            return 0.50

        prob_error = 1.0
        for src in set(sources):
            p = self.get_source_authority(src)
            prob_error *= (1.0 - p)

        posterior = 1.0 - prob_error
        # Clamp to realistic ceiling [0.0, 0.999]
        return round(min(0.999, max(0.1, posterior)), 4)

    def should_accept_field_update(
        self,
        existing_val: Any,
        existing_source: Optional[str],
        existing_weight: Optional[float],
        incoming_val: Any,
        incoming_source: str,
        incoming_weight: Optional[float] = None,
    ) -> Tuple[bool, float, str]:
        """
        Field-level lineage arbitration rule:
        Returns (should_accept, resulting_weight, reason)
        """
        if incoming_val is None or str(incoming_val).strip() == "":
            return False, existing_weight or 0.0, "incoming_value_empty"

        if existing_val is None or str(existing_val).strip() == "":
            w = incoming_weight or self.get_source_authority(incoming_source)
            return True, w, "initial_value_assignment"

        w_existing = existing_weight if existing_weight is not None else self.get_source_authority(existing_source or "")
        w_incoming = incoming_weight if incoming_weight is not None else self.get_source_authority(incoming_source)

        # Identical value: corroboration reinforcement
        if str(existing_val).strip().lower() == str(incoming_val).strip().lower():
            combined_w = 1.0 - ((1.0 - w_existing) * (1.0 - w_incoming))
            return True, round(combined_w, 4), "corroborated_identical_value"

        # Disagreement: Higher authority strictly wins
        if w_incoming >= w_existing:
            return True, w_incoming, f"higher_authority_override ({w_incoming} >= {w_existing})"

        return False, w_existing, f"lower_authority_rejected ({w_incoming} < {w_existing})"

    def compute_entity_quality_score(
        self,
        entity_data: Dict[str, Any],
        entity_type: str = "organization",
        contributing_sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Computes multi-dimensional Bayesian data quality score (0 - 100).
        """
        sources = contributing_sources or []
        breakdown: Dict[str, int] = {}

        if entity_type == "organization":
            # 1. Statutory & Legal Identity (Max 30 pts)
            tax_id = entity_data.get("statutory_tax_id") or entity_data.get("ein") or entity_data.get("rfc")
            legal_name = entity_data.get("legal_name") or entity_data.get("name")
            primary_domain = entity_data.get("primary_domain") or entity_data.get("domain")

            ident_score = 0
            if legal_name and len(str(legal_name).strip()) >= 3:
                ident_score += 10
            if tax_id and len(str(tax_id).strip()) >= 6:
                ident_score += 15
            if primary_domain and "." in str(primary_domain):
                ident_score += 5
            breakdown["identity_completeness"] = ident_score

            # 2. Contact Intelligence & Reachability (Max 25 pts)
            contact_score = 0
            emails = entity_data.get("emails") or []
            if isinstance(emails, str):
                emails = [emails]
            if emails:
                contact_score += 15
            phones = entity_data.get("phones") or []
            if isinstance(phones, str):
                phones = [phones]
            if phones:
                contact_score += 10
            breakdown["contact_intelligence"] = contact_score

            # 3. Geospatial Precision (Max 20 pts)
            geo_score = 0
            if entity_data.get("latitude") and entity_data.get("longitude"):
                geo_score += 15
            if entity_data.get("formatted_address") or entity_data.get("city"):
                geo_score += 5
            breakdown["geospatial_precision"] = geo_score

            # 4. Multi-Source Corroboration (Max 15 pts)
            unique_sources = len(set(sources))
            if unique_sources >= 3:
                corroboration = 15
            elif unique_sources == 2:
                corroboration = 10
            elif unique_sources == 1:
                corroboration = 5
            else:
                corroboration = 2
            breakdown["source_corroboration"] = corroboration

            # 5. Firmographic Depth (Max 10 pts)
            firm_score = 0
            if entity_data.get("primary_industry_naics") or entity_data.get("naics_code"):
                firm_score += 5
            if entity_data.get("employee_count_min") or entity_data.get("annual_revenue_usd"):
                firm_score += 5
            breakdown["firmographic_depth"] = firm_score

        else:
            # Person Entity Scoring
            ident_score = 0
            full_name = entity_data.get("full_name") or entity_data.get("name")
            if full_name and len(str(full_name).strip()) >= 3:
                ident_score += 20
            if entity_data.get("primary_linkedin_url"):
                ident_score += 15
            breakdown["identity_completeness"] = ident_score

            contact_score = 0
            email = entity_data.get("primary_email") or entity_data.get("email")
            if email and "@" in str(email):
                contact_score += 25
            breakdown["contact_intelligence"] = contact_score

            career_score = 0
            if entity_data.get("current_primary_title") or entity_data.get("title"):
                career_score += 15
            if entity_data.get("current_primary_org_id") or entity_data.get("company_id"):
                career_score += 15
            breakdown["career_verifiability"] = career_score

            corroboration = 10 if len(set(sources)) >= 2 else 5
            breakdown["source_corroboration"] = corroboration

        total_score = min(100, max(0, sum(breakdown.values())))
        confidence = self.compute_corroborated_confidence(sources)

        return {
            "data_quality_score": total_score,
            "bayesian_confidence": confidence,
            "corroborated_sources_count": len(set(sources)),
            "score_breakdown": breakdown,
        }


# Global singleton instance
bayesian_quality_engine = BayesianQualityEngine()

__all__ = [
    "DEFAULT_SOURCE_AUTHORITIES",
    "BayesianQualityEngine",
    "bayesian_quality_engine",
]
