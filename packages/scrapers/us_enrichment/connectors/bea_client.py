"""
OneExtraction — Bureau of Economic Analysis (BEA) API Client
=============================================================
Source: https://apps.bea.gov/api/data
Coverage: Regional Economic Accounts, Gross Domestic Product by Industry
Requires: BEA_DATA_API_KEY
"""

import logging
from typing import Any, Dict, List, Optional
import requests
from ..config.settings import settings

logger = logging.getLogger("oneextraction.bea_client")


class BEAClient:
    """Production client for Bureau of Economic Analysis (BEA) Data API."""

    BASE_URL = "https://apps.bea.gov/api/data"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or settings.BEA_DATA_API_KEY
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction/2.0 (Economic Analysis Pipeline; contact=compliance@oneextraction.internal)",
            "Accept": "application/json",
        })

    def get_data(self, dataset_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes a GetData call against BEA API.
        """
        query_params = dict(params or {})
        query_params.update({
            "UserID": self.api_key,
            "method": "GetData",
            "datasetname": dataset_name,
            "ResultFormat": "JSON",
        })

        try:
            resp = self.session.get(self.BASE_URL, params=query_params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("BEA API request failed: %s", e)
            return {"BEAAPI": {"Results": {"Error": str(e)}}}

    def get_regional_gdp_by_industry(
        self,
        geo_fips: str = "STATE",
        line_code: str = "1",
        year: str = "2023",
    ) -> List[Dict[str, Any]]:
        """
        Queries Regional Gross Domestic Product by State.
        """
        params = {
            "TableName": "SAGDP2N",
            "LineCode": line_code,
            "GeoFIPS": geo_fips,
            "Year": year,
        }
        raw = self.get_data("Regional", params)
        results = []

        data_items = raw.get("BEAAPI", {}).get("Results", {}).get("Data", [])
        if isinstance(data_items, list):
            for row in data_items:
                results.append({
                    "source": "bea",
                    "fips": row.get("GeoFips"),
                    "geo_name": row.get("GeoName"),
                    "industry_title": row.get("Description"),
                    "gdp_value": row.get("DataValue"),
                    "year": row.get("TimePeriod"),
                    "unit": row.get("CL_UNIT"),
                })

        return results
