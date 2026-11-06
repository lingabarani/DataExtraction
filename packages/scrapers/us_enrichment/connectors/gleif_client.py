"""
DataExtraction — GLEIF LEI API Enrichment Client
=================================================
Source: https://api.gleif.org/api/v1/
Coverage: Global Legal Entity Identifier (LEI) directory (ISO 17442).
Provides: Canonical Legal Name, Registered Address, Jurisdiction, Registration Status,
          Managing LOU, Initial Registration Date, and Validation Authority Details.

Features:
  1. Exponential backoff and jittered retry strategy using EnterpriseHttpClient.
  2. Multi-attribute entity matching (Name, Country, Postal Code).
  3. Non-destructive enrichment: routes ambiguous / low-confidence matches to review.
  4. Returns standardized enrichment payload with raw API response and audit timestamps.
"""

import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from packages.infrastructure.http_client import get_http_client
from packages.pipeline.normalizer import clean_legal_suffixes

logger = logging.getLogger("dataextraction.enrichment.gleif")

GLEIF_API_BASE = "https://api.gleif.org/api/v1"
GLEIF_LEI_LOOKUP_URL = f"{GLEIF_API_BASE}/lei-records"


class GleifEnrichmentClient:
    """
    Client for querying the Global Legal Entity Identifier Foundation (GLEIF) REST API.
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.http = get_http_client()

    def lookup_by_lei(self, lei: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves canonical entity details for an exact 20-character LEI.
        """
        clean_lei = str(lei).strip().upper()
        if len(clean_lei) != 20:
            logger.warning("Invalid LEI format: %s (must be 20 alphanumeric characters)", lei)
            return None

        url = f"{GLEIF_LEI_LOOKUP_URL}/{clean_lei}"
        try:
            resp = self.http.get(url, timeout=self.timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            return self._parse_gleif_record(data.get("data", {}))
        except Exception as err:
            logger.error("GLEIF lookup error for LEI %s: %s", clean_lei, err)
            return None

    def search_by_name(
        self,
        company_name: str,
        country: str = "US",
        postal_code: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Searches GLEIF records by legal name and country filter.
        """
        if not company_name or not company_name.strip():
            return []

        norm_name = clean_legal_suffixes(company_name) or company_name.strip()
        c_code = str(country).strip().upper()[:2] if country else "US"

        params = {
            "filter[entity.legalName]": norm_name,
            "page[size]": min(limit, 10),
        }
        if c_code:
            params["filter[entity.legalAddress.country]"] = c_code

        try:
            resp = self.http.get(
                GLEIF_LEI_LOOKUP_URL,
                params=params,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.warning("GLEIF search non-200 status %d: %s", resp.status_code, resp.text[:200])
                return []

            payload = resp.json()
            records = payload.get("data", [])
            results = []
            for item in records:
                parsed = self._parse_gleif_record(item)
                if parsed:
                    # Score confidence
                    parsed_score = self._compute_match_confidence(
                        query_name=norm_name,
                        candidate_name=parsed.get("legal_name", ""),
                        query_postal=postal_code,
                        candidate_postal=parsed.get("postal_code"),
                    )
                    parsed["match_confidence"] = parsed_score
                    results.append(parsed)

            # Sort by match confidence descending
            results.sort(key=lambda x: x["match_confidence"], reverse=True)
            return results
        except Exception as err:
            logger.error("GLEIF search exception for '%s': %s", company_name, err)
            return []

    def _parse_gleif_record(self, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extracts structured fields from a GLEIF JSON:API record.
        """
        if not data:
            return None

        lei = data.get("id") or (data.get("attributes", {}).get("lei"))
        attrs = data.get("attributes", {})
        entity = attrs.get("entity", {})
        reg = attrs.get("registration", {})

        legal_name = entity.get("legalName", {}).get("name")
        legal_addr = entity.get("legalAddress", {})
        head_addr = entity.get("headquartersAddress", {})

        return {
            "lei": lei,
            "legal_name": legal_name,
            "normalized_name": clean_legal_suffixes(legal_name),
            "jurisdiction": entity.get("jurisdiction"),
            "entity_status": entity.get("status"),
            "registration_status": reg.get("status"),
            "initial_registration_date": reg.get("initialRegistrationDate"),
            "last_update_date": reg.get("lastUpdateDate"),
            "managing_lou": reg.get("managingLou"),
            "country": legal_addr.get("country") or head_addr.get("country"),
            "city": legal_addr.get("city") or head_addr.get("city"),
            "postal_code": legal_addr.get("postalCode") or head_addr.get("postalCode"),
            "raw_payload": data,
            "enriched_at": datetime.now(timezone.utc).isoformat(),
            "source": "GLEIF_LEI",
        }

    def _compute_match_confidence(
        self,
        query_name: str,
        candidate_name: str,
        query_postal: Optional[str] = None,
        candidate_postal: Optional[str] = None,
    ) -> float:
        """
        Computes multi-signal matching score between query and candidate.
        """
        import difflib
        q_norm = clean_legal_suffixes(query_name) or ""
        c_norm = clean_legal_suffixes(candidate_name) or ""

        name_ratio = difflib.SequenceMatcher(None, q_norm, c_norm).ratio()
        score = name_ratio * 0.85

        if query_postal and candidate_postal:
            clean_qp = str(query_postal)[:5]
            clean_cp = str(candidate_postal)[:5]
            if clean_qp == clean_cp:
                score += 0.15

        return round(min(score, 1.0), 3)


# Singleton client
gleif_client = GleifEnrichmentClient()

__all__ = [
    "GleifEnrichmentClient",
    "gleif_client",
]
