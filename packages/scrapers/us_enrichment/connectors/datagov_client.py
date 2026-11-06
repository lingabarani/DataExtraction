"""
OneExtraction — Data.gov Federal Open Data Catalog Client
==========================================================
Source: https://api.data.gov
Coverage: Cross-agency open federal datasets, educational establishments
Requires: DATA_GOV_API_KEY
"""

import logging
from typing import Any, Dict, List, Optional
import requests
from ..config.settings import settings

logger = logging.getLogger("oneextraction.datagov_client")


class DataGovClient:
    """Production client for Data.gov API endpoints."""

    BASE_URL = "https://api.data.gov"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or settings.DATA_GOV_API_KEY
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction/2.0 (DataGov Pipeline; contact=compliance@oneextraction.internal)",
            "Accept": "application/json",
        })

    def get_data(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Queries Data.gov API endpoint with api_key."""
        query_params = dict(params or {})
        if self.api_key:
            query_params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.get(url, params=query_params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Data.gov API request failed for %s: %s", url, e)
            return {"results": []}

    def get_educational_institutions(self, state: Optional[str] = "CA", limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves higher educational institutions and universities registered on data.gov.
        Returns canonical business dictionaries.
        """
        params = {
            "fields": "id,school.name,school.city,school.state,school.zip,school.school_url",
            "per_page": min(100, limit),
        }
        if state:
            params["school.state"] = state.upper()

        raw = self.get_data("ed/collegescorecard/v1/schools", params)
        institutions: List[Dict[str, Any]] = []

        for item in raw.get("results", []):
            inst_id = item.get("id")
            name = item.get("school.name")
            if not inst_id or not name:
                continue

            institutions.append({
                "source": "data_gov",
                "company_id": f"ed_inst_{inst_id}",
                "name": name,
                "city": item.get("school.city"),
                "state_code": item.get("school.state"),
                "zip_code": item.get("school.zip"),
                "website_url": item.get("school.school_url"),
                "country": "United States",
                "industry": "Colleges, Universities, and Professional Schools",
                "sub_industry": "Higher Education",
                "data_quality_score": 80,
            })

        return institutions
