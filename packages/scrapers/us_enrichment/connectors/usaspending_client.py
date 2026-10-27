"""
USASpending.gov Award Recipients Connector
Source: https://api.usaspending.gov/api/v2/
Coverage: 3M+ federal contract and grant award records
Provides: Recipient company name, EIN, NAICS, city/state, award amounts.
Excellent for discovering non-SAM.gov registered vendors.
No API key required.
"""

import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..models.company import USCanonicalCompany, USAddress
from ..models.source_record import SourceProvenanceRecord, RawSourcePayload

try:
    from botasaurus.request import request as bt_request, Request as BtRequest
    HAS_BOTASAURUS = True
except ImportError:
    HAS_BOTASAURUS = False

BASE_URL = "https://api.usaspending.gov/api/v2"
RECIPIENT_SEARCH_URL = f"{BASE_URL}/recipient/"
AWARD_SEARCH_URL = f"{BASE_URL}/search/spending_by_award/"
NAICS_SEARCH_URL = f"{BASE_URL}/autocomplete/naics/"
BULK_DOWNLOAD_URL = f"{BASE_URL}/bulk_download/awards/"

if HAS_BOTASAURUS:
    @bt_request(cache=True, parallel=4, output=None)
    def fetch_usaspending_awards_botasaurus(request: BtRequest, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Botasaurus @request decorated fetcher for USASpending awards."""
        headers = {
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            response = request.post(AWARD_SEARCH_URL, data=json.dumps(payload), headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {}




class USASpendingClient:
    """
    Fetches company data from USASpending.gov federal contract and grant awards.
    Uses the award spending search endpoint to enumerate unique recipients.
    """

    SOURCE_KEY = "USASPENDING"
    SOURCE_NAME = "USASpending.gov Federal Award Recipients"

    def __init__(self, rate_limit_rps: float = 2.0):
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _post(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Executes POST request with Botasaurus caching when available."""
        if HAS_BOTASAURUS and url == AWARD_SEARCH_URL:
            try:
                res = fetch_usaspending_awards_botasaurus(payload)
                if res:
                    return res
            except Exception:
                pass

        time.sleep(self.delay)
        try:
            r = self.session.post(url, json=payload, timeout=20)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}


    def _get(self, url: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        time.sleep(self.delay)
        try:
            r = self.session.get(url, params=params or {}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    def fetch_award_recipients(
        self,
        naics_code: Optional[str] = None,
        state_code: Optional[str] = None,
        award_type: str = "contracts",  # contracts, grants, loans, idvs
        fiscal_year: int = 2024,
        max_records: int = 1000,
    ) -> List[RawSourcePayload]:
        """
        Fetches award recipients by NAICS code and/or state.
        Returns raw payloads for normalization.
        """
        filters: Dict[str, Any] = {
            "time_period": [{"start_date": f"{fiscal_year - 1}-10-01", "end_date": f"{fiscal_year}-09-30"}],
            "award_type_codes": self._award_type_codes(award_type),
        }
        if naics_code:
            filters["naics_codes"] = {"require": [naics_code]}
        if state_code:
            filters["recipient_locations"] = [{"country": "USA", "state": state_code}]

        fields = [
            "Award ID", "Recipient Name", "recipient_id", "Recipient UEI",
            "Recipient DUNS", "Recipient State Province", "Recipient City Name",
            "Recipient Zip Code", "NAICS Code", "NAICS Description",
            "Award Amount", "primary_place_of_performance_state_code",
        ]

        payload = {
            "filters": filters,
            "fields": fields,
            "page": 1,
            "limit": min(100, max_records),
            "sort": "Award Amount",
            "order": "desc",
            "subawards": False,
        }

        raw_payloads: List[RawSourcePayload] = []
        total_fetched = 0
        now = datetime.now(timezone.utc).isoformat()

        while total_fetched < max_records:
            data = self._post(AWARD_SEARCH_URL, payload)
            results = data.get("results", []) or []
            if not results:
                break

            for award in results:
                if total_fetched >= max_records:
                    break
                recipient_name = award.get("Recipient Name", "").strip()
                if not recipient_name:
                    continue
                raw_payloads.append(RawSourcePayload(
                    source=self.SOURCE_KEY,
                    source_record_id=award.get("recipient_id") or f"usas_{total_fetched}",
                    source_url=AWARD_SEARCH_URL,
                    raw_data=award,
                    retrieved_at=now,
                ))
                total_fetched += 1

            page_meta = data.get("page_metadata", {}) or {}
            if not page_meta.get("has_next_page", False):
                break
            payload["page"] += 1

        return raw_payloads

    def normalize(self, payload: RawSourcePayload) -> Optional[USCanonicalCompany]:
        """Normalize a USASpending award recipient to USCanonicalCompany."""
        raw = payload.raw_data
        now = datetime.now(timezone.utc).isoformat()

        legal_name = (raw.get("Recipient Name") or raw.get("recipient_name") or "").strip()
        if not legal_name:
            return None

        state_code = (raw.get("Recipient State Province") or raw.get("recipient_state") or "").strip()
        city = (raw.get("Recipient City Name") or raw.get("recipient_city") or "").strip()
        zip_code = str(raw.get("Recipient Zip Code") or raw.get("recipient_zip") or "")[:5]

        naics_code = str(raw.get("NAICS Code") or raw.get("naics_code") or "").strip()
        naics_desc = raw.get("NAICS Description") or raw.get("naics_description") or ""
        industry = naics_desc or _naics_prefix_industry(naics_code)

        address = USAddress(
            city=city or None,
            state=_state_code_to_name(state_code),
            state_code=state_code or None,
            zip_code=zip_code or None,
            country="United States",
        )

        uei = raw.get("Recipient UEI") or raw.get("recipient_uei") or ""

        from ..pipeline.deduplication import generate_us_company_id
        company_id = generate_us_company_id(
            ein=None,
            legal_name=legal_name,
            state=state_code,
        )

        prov = SourceProvenanceRecord(
            source=self.SOURCE_KEY,
            source_record_id=payload.source_record_id,
            source_url=payload.source_url,
            retrieved_at=now,
        )

        return USCanonicalCompany(
            company_id=company_id,
            legal_name=legal_name.upper(),
            trade_name=legal_name,
            normalized_name=_normalize_name(legal_name),
            uei=uei or None,
            entity_type="CORPORATION",
            industry=industry or None,
            naics_code=naics_code or None,
            address=address,
            source_records=[prov],
            source_count=1,
            last_verified_at=now,
        )

    def normalize_batch(self, payloads: List[RawSourcePayload]) -> List[USCanonicalCompany]:
        companies = []
        for payload in payloads:
            try:
                c = self.normalize(payload)
                if c and c.legal_name:
                    companies.append(c)
            except Exception:
                continue
        return companies

    def _award_type_codes(self, award_type: str) -> List[str]:
        type_map = {
            "contracts": ["A", "B", "C", "D"],
            "grants": ["02", "03", "04", "05"],
            "loans": ["07", "08"],
            "idvs": ["IDV_A", "IDV_B", "IDV_C", "IDV_D", "IDV_E"],
        }
        return type_map.get(award_type, ["A", "B", "C", "D"])


def _naics_prefix_industry(naics: str) -> str:
    labels = {
        "11": "Agriculture", "21": "Mining", "22": "Utilities",
        "23": "Construction", "31": "Manufacturing", "32": "Manufacturing",
        "33": "Manufacturing", "42": "Wholesale", "44": "Retail", "45": "Retail",
        "48": "Transportation", "49": "Transportation", "51": "Information Technology",
        "52": "Finance", "53": "Real Estate", "54": "Professional Services",
        "55": "Management", "56": "Administrative Services", "61": "Education",
        "62": "Healthcare", "71": "Arts and Entertainment", "72": "Hospitality",
        "81": "Other Services", "92": "Government",
    }
    return labels.get(str(naics)[:2], "Professional Services")


def _normalize_name(name: str) -> str:
    n = name.upper().strip()
    for s in [" LLC", " INC", " CORP", " LTD", " LP", " LLP", " DBA", " CO"]:
        if n.endswith(s):
            n = n[:-len(s)].strip()
    return n


def _state_code_to_name(code: str) -> str:
    STATE_MAP = {
        "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
        "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
        "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
        "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
        "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
        "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
        "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
        "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
        "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
        "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
        "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
        "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
        "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    }
    return STATE_MAP.get(str(code).upper(), code)


usaspending_client = USASpendingClient()
