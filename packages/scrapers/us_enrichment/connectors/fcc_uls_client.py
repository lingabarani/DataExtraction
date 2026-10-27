"""
FCC Universal Licensing System (ULS) Telecom Connector (Ported from FORGE dataforge).
Source: https://data.fcc.gov/api/license-view/
Coverage: 3M+ FCC wireless, telecom, broadcasting, and spectrum license holders.
Provides: Licensee Name, Call Sign, License Service Code, Address, City, State, Zip, Contact Officer.
No API key required.
"""

import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..models.company import USCanonicalCompany, USAddress, USPhoneItem
from ..models.source_record import SourceProvenanceRecord, RawSourcePayload

try:
    from botasaurus.request import request as bt_request, Request as BtRequest
    HAS_BOTASAURUS = True
except ImportError:
    HAS_BOTASAURUS = False

FCC_API_URL = "https://data.fcc.gov/api/license-view/licenses/search"

if HAS_BOTASAURUS:
    @bt_request(cache=True, parallel=4, output=None)
    def fetch_fcc_licenses_botasaurus(request: BtRequest, params: Dict[str, Any]) -> Dict[str, Any]:
        """Botasaurus @request decorated fetcher for FCC ULS API."""
        headers = {
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json",
        }
        try:
            response = request.get(FCC_API_URL, params=params, headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {}



class FCCULSClient:
    """
    Fetches telecom, wireless, and broadcasting license holders from the FCC ULS API.
    """

    SOURCE_KEY = "FCC_ULS"
    SOURCE_NAME = "FCC Universal Licensing System"

    def __init__(self, rate_limit_rps: float = 3.0):
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json",
        })

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if HAS_BOTASAURUS:
            try:
                res = fetch_fcc_licenses_botasaurus(params)
                if res:
                    return res
            except Exception:
                pass

        time.sleep(self.delay)
        try:
            r = self.session.get(FCC_API_URL, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    def fetch_licenses(
        self,
        searchValue: str = "Telecom",
        state: Optional[str] = None,
        max_records: int = 200,
    ) -> List[RawSourcePayload]:
        """Searches for FCC telecom license holders by keyword/state."""
        params: Dict[str, Any] = {
            "searchValue": searchValue,
            "format": "json",
            "pageSize": min(100, max_records),
        }
        if state:
            params["state"] = state.upper()

        data = self._get(params)
        licenses_data = data.get("Licenses", {}) or {}
        licenses = licenses_data.get("License", []) or []
        now = datetime.now(timezone.utc).isoformat()

        payloads = []
        for item in licenses[:max_records]:
            call_sign = str(item.get("callsign", "")).strip()
            payloads.append(RawSourcePayload(
                source=self.SOURCE_KEY,
                source_record_id=f"FCC_{call_sign}" if call_sign else f"FCC_{len(payloads)}",
                source_url=f"https://wireless2.fcc.gov/UlsApp/UlsSearch/license.jsp?licKey={item.get('licKey', '')}",
                raw_data=item,
                retrieved_at=now,
            ))

        return payloads

    def normalize(self, payload: RawSourcePayload) -> Optional[USCanonicalCompany]:
        raw = payload.raw_data
        now = datetime.now(timezone.utc).isoformat()

        legal_name = (raw.get("licName") or raw.get("licenseeName") or "").strip()
        if not legal_name:
            return None

        call_sign = str(raw.get("callsign", "")).strip()
        category = raw.get("categoryDesc", "") or "Telecommunications & Wireless"
        status = raw.get("statusDesc", "") or "Active"

        city = raw.get("city", "") or ""
        state_code = raw.get("state", "") or ""
        zip_code = str(raw.get("zip", ""))[:5]

        address = USAddress(
            city=city or None,
            state=_state_code_to_name(state_code),
            state_code=state_code or None,
            zip_code=zip_code or "",
            country="United States",
        )

        from ..pipeline.deduplication import generate_us_company_id
        company_id = generate_us_company_id(
            ein=None,
            legal_name=legal_name,
            state=state_code,
        )

        prov = SourceProvenanceRecord(
            source=self.SOURCE_KEY,
            source_record_id=f"FCC_{call_sign}",
            source_url=payload.source_url,
            retrieved_at=now,
        )

        company = USCanonicalCompany(
            company_id=company_id,
            legal_name=legal_name.upper(),
            trade_name=legal_name,
            normalized_name=_normalize_name(legal_name),
            entity_type="CORPORATION",
            industry="Telecommunications & Wireless",
            naics_code="517311",
            address=address,
            source_records=[prov],
            source_count=1,
            last_verified_at=now,
        )

        # Contact officer
        contact_name = raw.get("contactName", "")
        if contact_name:
            company._exec_candidates = [{  # type: ignore[attr-defined]
                "name": contact_name,
                "title": "License Contact / Officer",
                "phone": None,
                "source": self.SOURCE_KEY,
            }]

        return company

    def normalize_batch(self, payloads: List[RawSourcePayload]) -> List[USCanonicalCompany]:
        companies = []
        for p in payloads:
            try:
                c = self.normalize(p)
                if c and c.legal_name:
                    companies.append(c)
            except Exception:
                continue
        return companies


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    suffixes = [" LLC", " INC", " CORP", " CO", " TELECOM", " WIRELESS"]
    n = name.upper().strip()
    for s in suffixes:
        if n.endswith(s):
            n = n[: -len(s)].strip()
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
    return STATE_MAP.get(code.upper(), code)


fcc_uls_client = FCCULSClient()
