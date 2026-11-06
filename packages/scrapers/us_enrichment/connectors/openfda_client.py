"""
OneExtraction — openFDA Life Sciences & Medical Device Registry Client
=======================================================================
Source: https://api.fda.gov
Coverage: Regulated medical device establishments, drug labelers, food/drug recalls
Requires: OPENFDA_API_KEY
"""

import logging
import time
from typing import Any, Dict, List, Optional
import requests
from ..config.settings import settings

logger = logging.getLogger("oneextraction.openfda_client")


class OpenFDAClient:
    """Production client for FDA public data endpoints."""

    BASE_URL = "https://api.fda.gov"

    def __init__(self, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key or settings.OPENFDA_API_KEY
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction/2.0 (FDA Medical Device Pipeline; contact=compliance@oneextraction.internal)",
            "Accept": "application/json",
        })

    def get_data(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Executes paginated queries against openFDA endpoints."""
        query_params = dict(params or {})
        if self.api_key:
            query_params["api_key"] = self.api_key

        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        target_limit = int(query_params.pop("limit", 100))
        results: List[Dict[str, Any]] = []
        skip = 0

        while len(results) < target_limit:
            fetch_limit = min(100, target_limit - len(results))
            page_params = dict(query_params)
            page_params["limit"] = fetch_limit
            page_params["skip"] = skip

            try:
                resp = self.session.get(url, params=page_params, timeout=self.timeout)
                if resp.status_code == 404:
                    break
                resp.raise_for_status()
                data = resp.json()
                items = data.get("results", [])
                if not items:
                    break
                results.extend(items)
                skip += len(items)
                if len(items) < fetch_limit:
                    break
            except requests.RequestException as e:
                logger.warning("openFDA request notice (url=%s, skip=%d): %s", url, skip, e)
                break

        return {"results": results, "total": len(results)}

    def get_device_establishments(self, state: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Extracts medical device establishments registered with the FDA.
        Returns canonical business dictionaries.
        """
        search_query = "status_code:1"
        if state:
            search_query += f' AND establishment_type:"{state}"'

        raw = self.get_data("device/registrationlisting.json", params={"search": search_query, "limit": limit})
        records: List[Dict[str, Any]] = []

        for item in raw.get("results", []):
            reg = item.get("registration", {})
            owner = reg.get("owner_operator", {})
            reg_num = str(reg.get("registration_number") or reg.get("fein") or item.get("k_number", ""))
            if not reg_num:
                continue

            name = owner.get("owner_operator_name") or reg.get("name") or "Medical Facility"
            state_code = reg.get("state_code") or owner.get("state_code")
            city = reg.get("city") or owner.get("city")
            zip_code = reg.get("postal_code") or owner.get("postal_code")

            records.append({
                "source": "openfda",
                "company_id": f"fda_{reg_num}",
                "name": name,
                "legal_name": owner.get("owner_operator_name"),
                "city": city,
                "state": state_code,
                "state_code": state_code,
                "zip_code": zip_code,
                "country": "United States",
                "industry": "Medical Devices & Supplies",
                "sub_industry": "FDA Regulated Life Sciences",
                "data_quality_score": 75,
            })

        return records
