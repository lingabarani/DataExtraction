"""
DataExtraction — Autonomous Freshness & SLA Revalidation Engine
==============================================================
Calculates mathematical continuous exponential freshness decay for Master B2B entities.
Detects overdue SLA intervals and orchestrates autonomous revalidation sweeps.

Mathematical Formula:
    F(t) = exp(-lambda * delta_t)
    where delta_t is days elapsed, lambda = ln(2) / HalfLife_Days

Dimension SLAs & Half-Lives:
    - Website:    30 Days  (lambda = 0.023105)
    - Email:      90 Days  (lambda = 0.007702)
    - Executive:  90 Days  (lambda = 0.007702)
    - Domain:     90 Days  (lambda = 0.007702)
    - Maps:      180 Days  (lambda = 0.003851)
    - Registry:  365 Days  (lambda = 0.001899)
"""

import math
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("dataextraction.domain.freshness_engine")

# Calibrated decay constants
LN2 = math.log(2.0)
DECAY_RATES: Dict[str, float] = {
    "website":   LN2 / 30.0,   # ~0.023105
    "email":     LN2 / 90.0,   # ~0.007702
    "executive": LN2 / 90.0,   # ~0.007702
    "domain":    LN2 / 90.0,   # ~0.007702
    "maps":      LN2 / 180.0,  # ~0.003851
    "registry":  LN2 / 365.0,  # ~0.001899
}

DIMENSION_WEIGHTS: Dict[str, float] = {
    "website":   0.25,
    "email":     0.25,
    "executive": 0.20,
    "domain":    0.15,
    "maps":      0.10,
    "registry":  0.05,
}

REVALIDATION_THRESHOLD = 0.7000  # Below 0.70 triggers automatic reharvest


class FreshnessEngine:
    """
    Computes mathematical freshness decay and identifies SLA violations.
    """

    @staticmethod
    def _days_since(ts: Optional[datetime], now: datetime) -> float:
        if ts is None:
            return 365.0  # Treat missing as maximum default decay
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = (now - ts).total_seconds() / 86400.0
        return max(0.0, delta)

    def calculate_decay(self, dimension: str, last_verified: Optional[datetime], now: Optional[datetime] = None) -> float:
        """Calculates exponential freshness score for a specific dimension."""
        now_dt = now or datetime.now(timezone.utc)
        days = self._days_since(last_verified, now_dt)
        lam = DECAY_RATES.get(dimension, DECAY_RATES["email"])
        score = math.exp(-lam * days)
        return round(min(1.0, max(0.0, score)), 4)

    def evaluate_organization_freshness(self, org_row: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Evaluates multidimensional freshness and revalidation triggers for an organization.
        Returns:
            {
                "composite_freshness": float (0.0 - 1.0),
                "is_stale": bool,
                "is_overdue": bool,
                "dimension_scores": dict,
                "overdue_dimensions": list[str],
                "recommended_actions": list[str]
            }
        """
        now_dt = now or datetime.now(timezone.utc)
        
        # Calculate dimensional freshness
        f_website   = self.calculate_decay("website", org_row.get("website_last_verified_at") or org_row.get("last_verified_at"), now_dt)
        f_email     = self.calculate_decay("email", org_row.get("email_last_verified_at") or org_row.get("last_verified_at"), now_dt)
        f_executive = self.calculate_decay("executive", org_row.get("executive_last_verified_at") or org_row.get("last_verified_at"), now_dt)
        f_domain    = self.calculate_decay("domain", org_row.get("domain_last_verified_at") or org_row.get("last_verified_at"), now_dt)
        f_maps      = self.calculate_decay("maps", org_row.get("maps_last_verified_at") or org_row.get("last_verified_at"), now_dt)
        f_registry  = self.calculate_decay("registry", org_row.get("registry_last_verified_at") or org_row.get("last_verified_at"), now_dt)

        # Composite score
        composite = (
            DIMENSION_WEIGHTS["website"]   * f_website +
            DIMENSION_WEIGHTS["email"]     * f_email +
            DIMENSION_WEIGHTS["executive"] * f_executive +
            DIMENSION_WEIGHTS["domain"]    * f_domain +
            DIMENSION_WEIGHTS["maps"]      * f_maps +
            DIMENSION_WEIGHTS["registry"]  * f_registry
        )
        composite = round(min(1.0, max(0.0, composite)), 4)

        # Next verification timestamp check
        next_verif = org_row.get("next_verification_at")
        if next_verif and next_verif.tzinfo is None:
            next_verif = next_verif.replace(tzinfo=timezone.utc)
        
        is_calendar_overdue = bool(next_verif and next_verif <= now_dt)
        is_decay_stale = bool(composite < REVALIDATION_THRESHOLD)
        is_overdue = is_calendar_overdue or is_decay_stale

        # Overdue dimensions
        overdue_dims = []
        rec_actions = []
        if f_website < REVALIDATION_THRESHOLD:
            overdue_dims.append("website")
            rec_actions.append("TRIGGER_AGENT_7_CRAWL")
        if f_email < REVALIDATION_THRESHOLD:
            overdue_dims.append("email")
            rec_actions.append("TRIGGER_AGENT_7_SMTP")
        if f_executive < REVALIDATION_THRESHOLD:
            overdue_dims.append("executive")
            rec_actions.append("TRIGGER_AGENT_4_PEOPLE_GRAPH")
        if f_domain < REVALIDATION_THRESHOLD:
            overdue_dims.append("domain")
            rec_actions.append("TRIGGER_AGENT_2_DNS")
        if f_maps < REVALIDATION_THRESHOLD:
            overdue_dims.append("maps")
            rec_actions.append("TRIGGER_AGENT_2_PLACES")
        if f_registry < REVALIDATION_THRESHOLD:
            overdue_dims.append("registry")
            rec_actions.append("TRIGGER_AGENT_1_FILINGS")

        return {
            "composite_freshness": composite,
            "is_stale": is_decay_stale,
            "is_overdue": is_overdue,
            "dimension_scores": {
                "website": f_website,
                "email": f_email,
                "executive": f_executive,
                "domain": f_domain,
                "maps": f_maps,
                "registry": f_registry,
            },
            "overdue_dimensions": overdue_dims,
            "recommended_actions": list(set(rec_actions)),
        }


freshness_engine = FreshnessEngine()
