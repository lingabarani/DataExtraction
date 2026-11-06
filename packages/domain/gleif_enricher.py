"""
DataExtraction — Domain GLEIF LEI Enricher
===========================================
Enterprise Global Legal Entity Identifier (GLEIF) Foundation Service.
Implements:
  1. ISO 17442 LEI syntax and MOD 97-10 check-digit validation.
  2. Multi-tier confidence scoring for company-to-LEI matching:
     - Exact LEI match: 1.0 confidence
     - Name + Postal Code match: 0.95 confidence
     - Name-only fuzzy match: 0.70 - 0.90 confidence (quarantine candidate)
     - Ambiguous or sub-threshold matches: rejected
  3. Integration with GleifEnrichmentClient for remote directory resolution.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from packages.domain.normalizer import clean_legal_suffixes
from packages.scrapers.us_enrichment.connectors.gleif_client import (
    GleifEnrichmentClient,
    gleif_client,
)

logger = logging.getLogger("dataextraction.domain.gleif_enricher")


def validate_lei_checksum(lei: Optional[str]) -> bool:
    """
    Validate ISO 17442 standard 20-character LEI format and MOD 97-10 checksum (ISO 7064).
    Characters are mapped: A=10, B=11, ..., Z=35.
    The checksum must satisfy: numeric_value % 97 == 1.
    """
    if not lei:
        return False
    s = str(lei).strip().upper()
    if len(s) != 20 or not s.isalnum():
        return False

    # Convert letters to digits (A -> 10, Z -> 35)
    digits = []
    for char in s:
        if char.isdigit():
            digits.append(char)
        elif "A" <= char <= "Z":
            digits.append(str(ord(char) - ord("A") + 10))
        else:
            return False

    num_str = "".join(digits)
    try:
        return int(num_str) % 97 == 1
    except (ValueError, OverflowError):
        return False


class GLEIFEnricher:
    """
    Core Domain Service for GLEIF LEI identification, validation, and golden record enrichment.
    """

    def __init__(self, client: Optional[GleifEnrichmentClient] = None):
        self.client = client or gleif_client

    def enrich_entity(
        self,
        company_name: Optional[str] = None,
        lei: Optional[str] = None,
        country: str = "US",
        postal_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Enriches organization data using GLEIF registry.
        Evaluates match confidence:
          - >= 0.95: Auto-enrich
          - 0.70 - 0.94: Quarantine for human review
          - < 0.70: Distinct entity / no match
        """
        exact_lei = str(lei).strip().upper() if lei else None
        if exact_lei and len(exact_lei) == 20:
            result = self.client.lookup_by_lei(exact_lei)
            if result:
                return {
                    "matched": True,
                    "confidence": 1.0,
                    "action": "AUTO_ENRICH",
                    "lei_data": result,
                    "rationale": "Exact ISO 17442 LEI match",
                }

        if not company_name:
            return {
                "matched": False,
                "confidence": 0.0,
                "action": "NO_MATCH",
                "rationale": "No company name or LEI supplied",
            }

        candidates = self.client.search_by_name(
            company_name=company_name,
            country=country,
            postal_code=postal_code,
            limit=5,
        )

        if not candidates:
            return {
                "matched": False,
                "confidence": 0.0,
                "action": "NO_MATCH",
                "rationale": "No candidates found in GLEIF directory",
            }

        best_cand = candidates[0]
        score = float(best_cand.get("match_score", 0.0))

        if score >= 0.95:
            action = "AUTO_ENRICH"
        elif score >= 0.70:
            action = "QUARANTINE_REVIEW"
        else:
            action = "NO_MATCH"

        return {
            "matched": action in ("AUTO_ENRICH", "QUARANTINE_REVIEW"),
            "confidence": score,
            "action": action,
            "lei_data": best_cand,
            "rationale": f"Candidate score {score:.2f} classified as {action}",
        }


# Singleton instance
gleif_enricher = GLEIFEnricher()

__all__ = [
    "validate_lei_checksum",
    "GLEIFEnricher",
    "gleif_enricher",
]

