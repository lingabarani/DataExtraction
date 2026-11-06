"""
OneExtraction — Bureau of Labor Statistics (BLS) API Client
============================================================
Source: https://api.bls.gov/publicAPI/v2/timeseries/data/
Coverage: Occupational employment, wages, inflation, labor dynamics
Requires: BLS_API_KEY
"""

import logging
from typing import Any, Dict, List, Optional
import requests
from ..config.settings import settings

logger = logging.getLogger("oneextraction.bls_client")


class BLSClient:
    """Production client for Bureau of Labor Statistics (BLS) v2 timeseries API."""

    BASE_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or settings.BLS_API_KEY
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction/2.0 (Labor Statistics Pipeline; contact=compliance@oneextraction.internal)",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def get_data(self, series_ids: List[str], start_year: int, end_year: int) -> Dict[str, Any]:
        """
        Queries BLS time series data for specified series IDs.
        """
        payload: Dict[str, Any] = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if self.api_key:
            payload["registrationkey"] = self.api_key

        try:
            resp = self.session.post(self.BASE_URL, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("BLS API request failed: %s", e)
            return {"status": "REQUEST_FAILED", "message": [str(e)], "Results": {}}

    def get_industry_employment_series(
        self,
        series_ids: Optional[List[str]] = None,
        start_year: int = 2022,
        end_year: int = 2024,
    ) -> List[Dict[str, Any]]:
        """
        Pulls standardized employment benchmark observations.
        Default: CEU0000000001 (Total Nonfarm Employment, Seasonally Adjusted)
        """
        target_series = series_ids or ["CEU0000000001"]
        raw = self.get_data(target_series, start_year, end_year)
        results = []

        series_data = raw.get("Results", {}).get("series", [])
        for s in series_data:
            s_id = s.get("seriesID")
            for item in s.get("data", []):
                results.append({
                    "source": "bls",
                    "series_id": s_id,
                    "year": item.get("year"),
                    "period": item.get("period"),
                    "period_name": item.get("periodName"),
                    "value": float(item.get("value") or 0.0),
                    "footnotes": [f.get("text") for f in item.get("footnotes", []) if f.get("text")],
                })

        return results
