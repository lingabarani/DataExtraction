"""
OneExtraction — U.S. Energy Information Administration (EIA) API Client
========================================================================
Source: https://api.eia.gov/v2
Coverage: Commercial & Industrial Energy, Electricity Retail Sales & Utilities
Requires: EIA_API_KEY
"""

import logging
from typing import Any, Dict, List, Optional
import requests
from ..config.settings import settings

logger = logging.getLogger("oneextraction.eia_client")


class EIAClient:
    """Production client for EIA v2 API."""

    BASE_URL = "https://api.eia.gov/v2"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or settings.EIA_API_KEY
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction/2.0 (Energy Facilities Pipeline; contact=compliance@oneextraction.internal)",
            "Accept": "application/json",
        })

    def get_data(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Queries EIA v2 API endpoint."""
        query_params = dict(params or {})
        if self.api_key:
            query_params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.get(url, params=query_params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("EIA API request failed for %s: %s", url, e)
            return {"response": {"data": [], "error": str(e)}}

    def get_commercial_electricity_providers(self, state: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retrieves retail electricity provider data and utility metrics.
        """
        params: Dict[str, Any] = {
            "frequency": "monthly",
            "data[0]": "price",
            "data[1]": "revenue",
            "data[2]": "sales",
            "facets[sectorid][]": "COM",  # Commercial sector
            "length": limit,
        }
        if state:
            params["facets[stateid][]"] = state.upper()

        raw = self.get_data("electricity/retail-sales/data/", params)
        results = []

        data_rows = raw.get("response", {}).get("data", [])
        for row in data_rows:
            results.append({
                "source": "eia",
                "state": row.get("stateid"),
                "state_description": row.get("stateDescription"),
                "sector": row.get("sectorDescription"),
                "period": row.get("period"),
                "price_cents_per_kwh": float(row.get("price") or 0.0),
                "revenue_thousand_dollars": float(row.get("revenue") or 0.0),
                "sales_mwh": float(row.get("sales") or 0.0),
            })

        return results
