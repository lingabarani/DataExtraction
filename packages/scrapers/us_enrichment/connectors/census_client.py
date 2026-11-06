"""
OneExtraction — US Census Bureau API Client
===========================================
Source: https://api.census.gov/data
Coverage: County Business Patterns, Economic Census, Demographic Profiles
Requires: CENSUS_DATA_API_KEY
"""

import logging
import time
from typing import Any, Dict, List, Optional
import requests
from ..config.settings import settings

logger = logging.getLogger("oneextraction.census_client")


class CensusClient:
    """Production client for the US Census Bureau Data API."""

    BASE_URL = "https://api.census.gov/data"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or settings.CENSUS_DATA_API_KEY
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction/2.0 (Federal Registry Pipeline; contact=compliance@oneextraction.internal)",
            "Accept": "application/json",
        })

    def get_data(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[List[List[str]]]:
        """Executes a GET query against Census Bureau data endpoint."""
        query_params = dict(params or {})
        if self.api_key:
            query_params["key"] = self.api_key

        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url, params=query_params, timeout=self.timeout)
                if resp.status_code == 204:
                    return None
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, list) and len(data) > 1:
                    return data
                return None
            except requests.RequestException as e:
                logger.warning("Census API attempt %d/%d failed for %s: %s", attempt, max_retries, url, e)
                if attempt == max_retries:
                    logger.error("Census API request permanently failed: %s", e)
                    return None
                time.sleep(1.5 * attempt)
        return None

    def get_county_business_patterns(
        self,
        year: str = "2022",
        state: Optional[str] = None,
        naics: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieves County Business Patterns (CBP) establishments.
        Variables: ESTAB (Number of Establishments), EMP (Number of Employees), PAYANN (Annual Payroll in $1,000)
        """
        get_vars = "ESTAB,EMP,PAYANN,NAICS2017,NAME"
        params = {"get": get_vars, "for": f"state:{state}" if state else "us:*"}
        if naics:
            params["NAICS2017"] = naics

        raw = self.get_data(f"{year}/cbp", params=params)
        if not raw or len(raw) < 2:
            return []

        headers = [h.strip() for h in raw[0]]
        results = []
        for row in raw[1:]:
            record = dict(zip(headers, row))
            results.append({
                "source": "census_cbp",
                "state_code": record.get("state"),
                "state_name": record.get("NAME"),
                "naics_code": record.get("NAICS2017"),
                "establishment_count": int(record.get("ESTAB") or 0),
                "employee_count": int(record.get("EMP") or 0),
                "annual_payroll_k": float(record.get("PAYANN") or 0.0),
                "year": year,
            })
        return results
