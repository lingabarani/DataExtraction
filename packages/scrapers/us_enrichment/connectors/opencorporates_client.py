"""
OpenCorporates Business Registry Connector
Source: https://api.opencorporates.com/v0.4/
Coverage: All 50 US states + DC business registrations
Provides: Company name, state, registration date, status, entity type,
          and officer/director names and roles from state filings.
Free tier: 500 requests/day without key. Rate limit enforced below.
"""

import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..models.company import USCanonicalCompany, USAddress
from ..models.source_record import SourceProvenanceRecord, RawSourcePayload

BASE_URL = "https://api.opencorporates.com/v0.4"
COMPANY_SEARCH_URL = f"{BASE_URL}/companies/search"
COMPANY_DETAIL_URL = f"{BASE_URL}/companies/us_{{state}}/{{company_number}}"

US_STATE_JURISDICTIONS = [
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
]

ENTITY_TYPE_MAP = {
    "private-limited-guarant-nsc-limited-exemption": "NONPROFIT",
    "private-unlimited": "CORPORATION",
    "private-limited-shares": "LLC",
    "llc": "LLC",
    "corporation": "CORPORATION",
    "limited-partnership": "PARTNERSHIP",
    "general-partnership": "PARTNERSHIP",
    "sole-trader": "SOLE_PROPRIETOR",
    "nonprofit": "NONPROFIT",
    "cooperative": "COOPERATIVE",
}


class OpenCorporatesClient:
    """
    Fetches US company registrations and officer data from OpenCorporates.
    Searches by industry keyword and/or jurisdiction (state).
    """

    SOURCE_KEY = "OPENCORPORATES"
    SOURCE_NAME = "OpenCorporates Business Registry"

    def __init__(self, api_key: Optional[str] = None, rate_limit_rps: float = 1.0):
        self.api_key = api_key or ""
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json",
        })

    def _get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        time.sleep(self.delay)
        if self.api_key:
            params["api_token"] = self.api_key
        try:
            r = self.session.get(url, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    def search_companies(
        self,
        query: str = "",
        jurisdiction_code: Optional[str] = None,
        company_type: Optional[str] = None,
        current_status: str = "Active",
        max_records: int = 500,
    ) -> List[RawSourcePayload]:
        """
        Searches OpenCorporates for US company registrations.
        Returns raw payloads for normalization.
        """
        params: Dict[str, Any] = {
            "q": query if query else "Inc",
            "country_code": "us",
            "per_page": 30,
            "page": 1,
        }
        if jurisdiction_code:
            params["jurisdiction_code"] = f"us_{jurisdiction_code.lower()}"
        if current_status:
            params["current_status"] = current_status
        if company_type:
            params["company_type"] = company_type

        payloads = []
        total_fetched = 0
        now = datetime.now(timezone.utc).isoformat()

        while total_fetched < max_records:
            data = self._get(COMPANY_SEARCH_URL, params)
            results = data.get("results", {}) or {}
            companies = results.get("companies", []) or []
            if not companies:
                break

            for entry in companies:
                if total_fetched >= max_records:
                    break
                company = entry.get("company", {}) or {}
                name = company.get("name", "").strip()
                if not name:
                    continue
                payloads.append(RawSourcePayload(
                    source=self.SOURCE_KEY,
                    source_record_id=str(company.get("company_number") or f"oc_{total_fetched}"),
                    source_url=company.get("opencorporates_url", COMPANY_SEARCH_URL),
                    raw_data=company,
                    retrieved_at=now,
                ))
                total_fetched += 1

            page_meta = results.get("page", 1)
            total_pages = results.get("total_pages", 1) or 1
            if page_meta >= total_pages:
                break
            params["page"] += 1

        return payloads

    def normalize(self, payload: RawSourcePayload) -> Optional[USCanonicalCompany]:
        """Normalize an OpenCorporates company record to USCanonicalCompany."""
        raw = payload.raw_data
        now = datetime.now(timezone.utc).isoformat()

        legal_name = (raw.get("name") or "").strip()
        if not legal_name:
            return None

        jurisdiction = raw.get("jurisdiction_code", "") or ""
        state_code = jurisdiction.replace("us_", "").upper() if jurisdiction.startswith("us_") else ""

        registered_address = raw.get("registered_address", {}) or {}
        city = registered_address.get("locality") or registered_address.get("city") or ""
        zip_code = registered_address.get("postal_code") or registered_address.get("postal_code") or ""
        street = registered_address.get("street_address") or ""

        address = USAddress(
            street=street or None,
            city=city or None,
            state=_state_code_to_name(state_code),
            state_code=state_code or None,
            zip_code=str(zip_code)[:5] if zip_code else None,
            country="United States",
        )

        # Entity type
        raw_type = (raw.get("company_type") or "").lower().strip()
        entity_type = ENTITY_TYPE_MAP.get(raw_type, "CORPORATION")
        if "llc" in raw_type or "limited liability" in raw_type:
            entity_type = "LLC"
        elif "nonprofit" in raw_type or "non-profit" in raw_type or "foundation" in legal_name.lower():
            entity_type = "NONPROFIT"

        # State of incorporation
        state_of_inc = raw.get("incorporation_date") and state_code

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

        company = USCanonicalCompany(
            company_id=company_id,
            legal_name=legal_name.upper(),
            trade_name=legal_name,
            normalized_name=_normalize_name(legal_name),
            entity_type=entity_type,
            state_of_incorporation=state_code or None,
            address=address,
            source_records=[prov],
            source_count=1,
            last_verified_at=now,
        )

        # Extract officers
        _extract_officers(company, raw, self.SOURCE_KEY)

        return company

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


def _extract_officers(company: USCanonicalCompany, raw: Dict, source_key: str) -> None:
    """Extract officer/director names from OpenCorporates company data."""
    candidates = getattr(company, "_exec_candidates", [])
    officers = raw.get("officers", []) or []
    for officer in officers:
        o = officer.get("officer", officer) if "officer" in officer else officer
        name = o.get("name") or ""
        position = o.get("position") or "Officer"
        if name and name.strip():
            candidates.append({
                "name": name.strip(),
                "title": position.strip(),
                "source": source_key,
            })
    company._exec_candidates = candidates  # type: ignore[attr-defined]


def _normalize_name(name: str) -> str:
    n = name.upper().strip()
    for s in [" LLC", " INC", " CORP", " LTD", " LP", " LLP", " DBA", " CO",
              " COMPANY", " INCORPORATED", " LIMITED", " CORPORATION"]:
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


opencorporates_client = OpenCorporatesClient()
