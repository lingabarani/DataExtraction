"""
US Census County Business Patterns (CBP) Connector
Source: https://api.census.gov/data/{year}/cbp
Coverage: ~8M+ US business establishments
Provides: NAICS 6-digit code, employee size bands, annual payroll, ZIP-level granularity.
Requires CENSUS_DATA_API_KEY (free from api.census.gov/data/key_signup.html).
"""

import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..models.company import USCanonicalCompany, USAddress
from ..models.source_record import SourceProvenanceRecord, RawSourcePayload

CBP_BASE_URL = "https://api.census.gov/data/{year}/cbp"
LATEST_YEAR = "2022"

# Employee size band codes
EMP_SIZE_MAP = {
    "1": (1, 4, "1 to 4 employees"),
    "2": (5, 9, "5 to 9 employees"),
    "3": (10, 19, "10 to 19 employees"),
    "4": (20, 49, "20 to 49 employees"),
    "5": (50, 99, "50 to 99 employees"),
    "6": (100, 249, "100 to 249 employees"),
    "7": (250, 499, "250 to 499 employees"),
    "8": (500, 999, "500 to 999 employees"),
    "9": (1000, None, "1,000+ employees"),
}

US_STATES = [
    "01", "02", "04", "05", "06", "08", "09", "10", "11", "12",
    "13", "15", "16", "17", "18", "19", "20", "21", "22", "23",
    "24", "25", "26", "27", "28", "29", "30", "31", "32", "33",
    "34", "35", "36", "37", "38", "39", "40", "41", "42", "44",
    "45", "46", "47", "48", "49", "50", "51", "53", "54", "55", "56",
]

NAICS_INDUSTRY_LABELS = {
    "11": "Agriculture, Forestry, Fishing and Hunting",
    "21": "Mining, Quarrying, and Oil and Gas Extraction",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing", "32": "Manufacturing", "33": "Manufacturing",
    "42": "Wholesale Trade",
    "44": "Retail Trade", "45": "Retail Trade",
    "48": "Transportation and Warehousing", "49": "Transportation and Warehousing",
    "51": "Information Technology and Media",
    "52": "Finance and Insurance",
    "53": "Real Estate and Rental and Leasing",
    "54": "Professional, Scientific, and Technical Services",
    "55": "Management of Companies and Enterprises",
    "56": "Administrative and Support Services",
    "61": "Educational Services",
    "62": "Health Care and Social Assistance",
    "71": "Arts, Entertainment, and Recreation",
    "72": "Accommodation and Food Services",
    "81": "Other Services (except Public Administration)",
    "92": "Public Administration",
}


class CensusCBPClient:
    """
    Fetches county-level and ZIP-level NAICS + employee band data from US Census CBP API.
    Primarily used to enrich company records with industry codes and headcount bands.
    """

    SOURCE_KEY = "CENSUS_CBP"
    SOURCE_NAME = "US Census County Business Patterns"

    def __init__(self, api_key: Optional[str] = None, rate_limit_rps: float = 2.0):
        self.api_key = api_key or ""
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json",
        })

    def _get(self, url: str, params: Dict[str, Any]) -> List[List[str]]:
        time.sleep(self.delay)
        if self.api_key:
            params["key"] = self.api_key
        try:
            r = self.session.get(url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def fetch_by_naics_and_state(
        self,
        naics_code: str,
        state_fips: Optional[str] = None,
        year: str = LATEST_YEAR,
        max_records: int = 1000,
    ) -> List[RawSourcePayload]:
        """
        Fetches CBP establishments by 6-digit NAICS code and optionally state FIPS.
        Returns raw payloads. Note: CBP gives aggregate counts, not individual company names.
        Used primarily for industry + headcount enrichment.
        """
        url = CBP_BASE_URL.format(year=year)
        params: Dict[str, Any] = {
            "get": "NAICS2017_LABEL,EMPSZES,EMPSZES_LABEL,ESTAB,EMP",
            "NAICS2017": naics_code,
        }
        if state_fips:
            params["for"] = f"county:*"
            params["in"] = f"state:{state_fips}"
        else:
            params["for"] = "us:*"

        rows = self._get(url, params)
        if not rows or len(rows) < 2:
            return []

        headers = rows[0]
        payloads = []
        now = datetime.now(timezone.utc).isoformat()

        for i, row in enumerate(rows[1:min(len(rows), max_records + 1)]):
            record = dict(zip(headers, row))
            payloads.append(RawSourcePayload(
                source=self.SOURCE_KEY,
                source_record_id=f"cbp_{naics_code}_{i}",
                source_url=url,
                raw_data=record,
                retrieved_at=now,
            ))

        return payloads

    def fetch_all_naics_summary(
        self,
        state_fips: Optional[str] = None,
        year: str = LATEST_YEAR,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetches a summary of all NAICS sectors for enrichment lookups.
        Returns dict keyed by NAICS 2-digit prefix.
        """
        url = CBP_BASE_URL.format(year=year)
        params: Dict[str, Any] = {
            "get": "NAICS2017,NAICS2017_LABEL,ESTAB,EMP",
            "NAICS2017": "*",
        }
        if state_fips:
            params["for"] = f"state:{state_fips}"
        else:
            params["for"] = "us:*"

        rows = self._get(url, params)
        result = {}
        if rows and len(rows) > 1:
            headers = rows[0]
            for row in rows[1:]:
                rec = dict(zip(headers, row))
                naics = rec.get("NAICS2017", "")
                if naics:
                    result[naics] = rec
        return result

    def get_employee_band(self, naics_code: str, state_fips: Optional[str] = None) -> Dict[str, Any]:
        """Returns typical employee band for a given NAICS code."""
        payloads = self.fetch_by_naics_and_state(
            naics_code=naics_code,
            state_fips=state_fips,
            max_records=10,
        )
        if not payloads:
            return {"min": None, "max": None, "source": None}
        # Return median-ish from first record
        raw = payloads[0].raw_data
        empszes = str(raw.get("EMPSZES", ""))
        band = EMP_SIZE_MAP.get(empszes)
        if band:
            return {"min": band[0], "max": band[1], "source": band[2]}
        return {"min": None, "max": None, "source": None}


def get_naics_industry_label(naics: str) -> str:
    """Get industry label from NAICS 2-digit prefix."""
    if not naics:
        return "Professional Services"
    prefix = str(naics)[:2]
    return NAICS_INDUSTRY_LABELS.get(prefix, "Professional Services")


census_cbp_client = CensusCBPClient()
