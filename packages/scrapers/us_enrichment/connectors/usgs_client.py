"""
OneExtraction — USGS Water Resources API Client
================================================
Source: https://waterservices.usgs.gov/nwis
Coverage: Water resources monitoring facilities, site metadata, streamflow
Requires: USGS_WATER_API_KEY (optional parameter for elevated quota)
"""

import logging
from typing import Any, Dict, List, Optional
import requests
from ..config.settings import settings

logger = logging.getLogger("oneextraction.usgs_client")


class USGSClient:
    """Production client for USGS NWIS water services."""

    BASE_URL = "https://waterservices.usgs.gov/nwis"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or settings.USGS_WATER_API_KEY
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction/2.0 (Water Facilities Pipeline; contact=compliance@oneextraction.internal)",
            "Accept": "application/json",
        })

    def get_data(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Queries USGS NWIS REST endpoint."""
        query_params = dict(params or {})
        query_params["format"] = "json"
        if self.api_key:
            query_params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.get(url, params=query_params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("USGS API request failed for %s: %s", url, e)
            return {"value": {"timeSeries": []}}

    def get_monitoring_facilities(self, state_code: str = "ca", limit: int = 50) -> List[Dict[str, Any]]:
        """
        Extracts active water monitoring site facilities.
        """
        params = {
            "stateCd": state_code.lower(),
            "siteStatus": "active",
            "hasDataTypeCd": "iv",
        }
        raw = self.get_data("iv/", params)
        facilities: List[Dict[str, Any]] = []

        series = raw.get("value", {}).get("timeSeries", [])[:limit]
        for item in series:
            source_info = item.get("sourceInfo", {})
            site_code_info = source_info.get("siteCode", [{}])[0]
            site_id = site_code_info.get("value")
            site_name = source_info.get("siteName")
            geo = source_info.get("geoLocation", {}).get("geogLocation", {})

            if site_id and site_name:
                facilities.append({
                    "source": "usgs",
                    "company_id": f"usgs_site_{site_id}",
                    "name": site_name,
                    "city": source_info.get("siteProperty", [{}])[0].get("value") if source_info.get("siteProperty") else None,
                    "state_code": state_code.upper(),
                    "latitude": float(geo.get("latitude")) if geo.get("latitude") is not None else None,
                    "longitude": float(geo.get("longitude")) if geo.get("longitude") is not None else None,
                    "industry": "Water Supply & Irrigation Systems",
                    "sub_industry": "USGS Monitoring Facility",
                })

        return facilities
