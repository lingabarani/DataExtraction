"""
CMS Healthcare NPI Registry Connector (Ported & Enhanced from FORGE dataforge).
Source: https://npiregistry.cms.hhs.gov/api/
Coverage: 7M+ US healthcare providers, medical practices, doctors, and healthcare organization officers.
Provides: NPI number, Organization/Provider Legal Name, Practice Address, City, State, Zip,
          Primary Phone, Gender, Credential, Healthcare Specialty Taxonomy.
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

NPI_API_URL = "https://npiregistry.cms.hhs.gov/api/"

# NPI Taxonomy → Standard Industry Map
TAXONOMY_INDUSTRY_MAP = {
    "207Q00000X": "Family Medicine",
    "207R00000X": "Internal Medicine",
    "122300000X": "Dentistry",
    "111N00000X": "Chiropractic",
    "152W00000X": "Optometry",
    "282N00000X": "Hospitals & Medical Centers",
    "261QP2300X": "Primary Care Clinics",
    "363A00000X": "Physician Assistants",
}

if HAS_BOTASAURUS:
    @bt_request(cache=True, parallel=4, output=None)
    def fetch_npi_registry_botasaurus(request: BtRequest, params: Dict[str, Any]) -> Dict[str, Any]:
        """Botasaurus @request decorated fetcher for CMS NPI Registry."""
        headers = {
            "User-Agent": "OneExtraction-B2B-Research/1.0 (healthcare POC)",
            "Accept": "application/json",
        }
        response = request.get(NPI_API_URL, params=params, headers=headers)
        if response.status_code == 200:
            return response.json()
        return {}


class NPIClient:
    """
    Fetches healthcare business and executive data from the CMS NPI Registry.
    Queries organization (enumeration_type=NPI-2) or individual practice (enumeration_type=NPI-1).
    """

    SOURCE_KEY = "CMS_NPI"
    SOURCE_NAME = "CMS National Provider Identifier Registry"

    def __init__(self, rate_limit_rps: float = 3.0):
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Research/1.0 (healthcare POC)",
            "Accept": "application/json",
        })

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute GET request to CMS NPI API."""
        if HAS_BOTASAURUS:
            try:
                res = fetch_npi_registry_botasaurus(params)
                if res:
                    return res
            except Exception:
                pass

        time.sleep(self.delay)
        try:
            r = self.session.get(NPI_API_URL, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    def fetch_providers(
        self,
        city: Optional[str] = None,
        state: Optional[str] = None,
        taxonomy_description: Optional[str] = None,
        enumeration_type: str = "NPI-2",  # NPI-2 = Organizations, NPI-1 = Individuals
        max_records: int = 200,
    ) -> List[RawSourcePayload]:
        """
        Fetches healthcare organization or individual practice records by city/state/taxonomy.
        """
        params: Dict[str, Any] = {
            "version": "2.1",
            "enumeration_type": enumeration_type,
            "limit": min(100, max_records),
        }
        if city:
            params["city"] = city
        if state:
            params["state"] = state.upper()
        if taxonomy_description:
            params["taxonomy_description"] = taxonomy_description

        data = self._get(params)
        results = data.get("results", []) or []
        now = datetime.now(timezone.utc).isoformat()

        payloads = []
        for item in results[:max_records]:
            number = str(item.get("number", "")).strip()
            payloads.append(RawSourcePayload(
                source=self.SOURCE_KEY,
                source_record_id=f"NPI_{number}",
                source_url=f"https://npiregistry.cms.hhs.gov/provider-details/{number}",
                raw_data=item,
                retrieved_at=now,
            ))

        return payloads

    def normalize(self, payload: RawSourcePayload) -> Optional[USCanonicalCompany]:
        """Normalize a CMS NPI Registry payload into USCanonicalCompany."""
        raw = payload.raw_data
        now = datetime.now(timezone.utc).isoformat()

        number = str(raw.get("number", "")).strip()
        basic = raw.get("basic", {}) or {}
        addresses = raw.get("addresses", []) or []
        taxonomies = raw.get("taxonomies", []) or []

        # Organization or Individual Name
        legal_name = (basic.get("organization_name") or basic.get("name") or "").strip()
        first_name = basic.get("first_name", "").strip()
        last_name = basic.get("last_name", "").strip()
        credential = basic.get("credential", "").strip()

        if not legal_name and (first_name or last_name):
            legal_name = f"{first_name} {last_name}".strip()
            if credential:
                legal_name += f", {credential}"

        if not legal_name:
            return None

        # Primary Location Address
        loc_addr = {}
        for addr in addresses:
            if addr.get("address_purpose") == "LOCATION":
                loc_addr = addr
                break
        if not loc_addr and addresses:
            loc_addr = addresses[0]

        street1 = loc_addr.get("address_1", "") or ""
        street2 = loc_addr.get("address_2", "") or ""
        street = f"{street1} {street2}".strip() if street2 else street1
        city = loc_addr.get("city", "") or ""
        state_code = loc_addr.get("state", "") or ""
        zip_code = (loc_addr.get("postal_code", "") or "")[:5]
        phone_raw = loc_addr.get("telephone_number", "") or ""

        address = USAddress(
            street=street or None,
            city=city or None,
            state=_state_code_to_name(state_code),
            state_code=state_code or None,
            zip_code=zip_code or "",
            country="United States",
        )

        # Primary Taxonomy / Specialty
        primary_tax = ""
        tax_desc = ""
        for tax in taxonomies:
            if tax.get("primary"):
                primary_tax = tax.get("code", "")
                tax_desc = tax.get("desc", "")
                break
        if not tax_desc and taxonomies:
            tax_desc = taxonomies[0].get("desc", "")
            primary_tax = taxonomies[0].get("code", "")

        industry = tax_desc or "Healthcare & Medical Services"
        naics_code = "621111"

        # Phones
        phones = []
        clean_ph = _clean_phone(phone_raw)
        if clean_ph:
            phones.append(USPhoneItem(value=clean_ph, source=self.SOURCE_KEY, type="OFFICE"))

        from ..pipeline.deduplication import generate_us_company_id
        company_id = generate_us_company_id(
            ein=None,
            legal_name=legal_name,
            state=state_code,
        )

        prov = SourceProvenanceRecord(
            source=self.SOURCE_KEY,
            source_record_id=f"NPI_{number}",
            source_url=payload.source_url,
            retrieved_at=now,
        )

        company = USCanonicalCompany(
            company_id=company_id,
            legal_name=legal_name.upper(),
            trade_name=legal_name,
            normalized_name=_normalize_name(legal_name),
            entity_type="ORGANIZATION" if raw.get("enumeration_type") == "NPI-2" else "PRACTICE",
            industry=industry,
            naics_code=naics_code,
            phone=clean_ph,
            phones=phones,
            address=address,
            source_records=[prov],
            source_count=1,
            last_verified_at=now,
        )

        # Attach provider officer candidate if individual
        if first_name or last_name:
            title = f"Practitioner ({credential})" if credential else "Medical Officer"
            company._exec_candidates = [{  # type: ignore[attr-defined]
                "name": f"{first_name} {last_name}".strip(),
                "title": title,
                "phone": clean_ph,
                "source": self.SOURCE_KEY,
            }]

        return company

    def normalize_batch(self, payloads: List[RawSourcePayload]) -> List[USCanonicalCompany]:
        """Normalize batch of NPI raw payloads."""
        companies = []
        for p in payloads:
            try:
                c = self.normalize(p)
                if c and c.legal_name:
                    companies.append(c)
            except Exception:
                continue
        return companies


def _clean_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+1{digits}" if digits else None


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    suffixes = [" LLC", " INC", " CORP", " PC", " PLLC", " PA", " MD", " DO", " DDS", " DMD"]
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


npi_client = NPIClient()
