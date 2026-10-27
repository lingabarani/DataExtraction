"""
ProPublica IRS 990 Nonprofit Explorer Connector
Source: https://projects.propublica.org/nonprofits/api/v2/
Coverage: 1.5M+ IRS-registered nonprofits (universities, hospitals, foundations, charities)
Provides: Organization name, EIN, address, revenue, employee count,
          and Named Officers/Directors with titles and compensation.
No API key required.
"""

import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..models.company import USCanonicalCompany, USAddress, USEmailItem
from ..models.source_record import SourceProvenanceRecord, RawSourcePayload

BASE_URL = "https://projects.propublica.org/nonprofits/api/v2"
SEARCH_URL = f"{BASE_URL}/search.json"
ORG_URL = f"{BASE_URL}/organizations/{{ein}}.json"

NONPROFIT_NAICS = "813"
NONPROFIT_INDUSTRY_MAP = {
    "Education": "611110",
    "Healthcare": "621111",
    "Human services": "624110",
    "Community improvement": "813410",
    "Arts and culture": "711110",
    "Environment": "541620",
    "International": "813212",
    "Religion": "813110",
    "Unknown": "813990",
}


class ProPublica990Client:
    """
    Fetches nonprofit organization data and executive officers from ProPublica's
    IRS 990 Nonprofit Explorer API.
    """

    SOURCE_KEY = "PROPUBLICA_990"
    SOURCE_NAME = "ProPublica IRS 990 Nonprofit Explorer"

    def __init__(self, rate_limit_rps: float = 3.0):
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json",
        })

    def _get(self, url: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        time.sleep(self.delay)
        try:
            r = self.session.get(url, params=params or {}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {}

    def search_nonprofits(
        self,
        query: str = "",
        state: Optional[str] = None,
        ntee_code: Optional[str] = None,
        max_records: int = 500,
    ) -> List[RawSourcePayload]:
        """
        Searches for nonprofits matching query and/or state/NTEE code.
        Returns raw payloads for normalization.
        """
        params: Dict[str, Any] = {"q": query or "*", "page": 0}
        if state:
            params["state[id]"] = state.upper()
        if ntee_code:
            params["ntee[id]"] = ntee_code

        payloads = []
        total_fetched = 0

        while total_fetched < max_records:
            data = self._get(SEARCH_URL, params)
            orgs = data.get("organizations", []) or []
            if not orgs:
                break

            for org in orgs:
                if total_fetched >= max_records:
                    break
                ein = str(org.get("ein", "")).strip()
                payloads.append(RawSourcePayload(
                    source=self.SOURCE_KEY,
                    source_record_id=ein or f"pp_{total_fetched}",
                    source_url=ORG_URL.format(ein=ein) if ein else SEARCH_URL,
                    raw_data=org,
                ))
                total_fetched += 1

            total_pages = data.get("num_pages", 1) or 1
            if params["page"] + 1 >= total_pages:
                break
            params["page"] += 1

        return payloads

    def fetch_org_detail(self, ein: str) -> Dict[str, Any]:
        """Fetches detailed organization data including 990 filings and officers."""
        return self._get(ORG_URL.format(ein=ein))

    def normalize(
        self,
        payload: RawSourcePayload,
        fetch_detail: bool = False,
    ) -> Optional[USCanonicalCompany]:
        """Normalize a ProPublica nonprofit payload to USCanonicalCompany."""
        raw = payload.raw_data
        now = datetime.now(timezone.utc).isoformat()

        org = raw
        if fetch_detail and payload.raw_data.get("ein"):
            detail = self.fetch_org_detail(str(payload.raw_data["ein"]))
            org = detail.get("organization", raw) or raw

        legal_name = (org.get("name") or org.get("strName") or "").strip()
        if not legal_name:
            return None

        ein_raw = str(org.get("ein", "") or "").strip().replace("-", "")
        ein_formatted = f"{ein_raw[:2]}-{ein_raw[2:]}" if len(ein_raw) >= 3 else ein_raw or None

        # Address
        city = org.get("city") or org.get("strCity") or ""
        state_code = org.get("state") or org.get("strState") or ""
        zip_code = org.get("zipcode") or org.get("strZip") or ""
        address = USAddress(
            city=city,
            state=_state_code_to_name(state_code),
            state_code=state_code,
            zip_code=str(zip_code)[:5] if zip_code else "",
            country="United States",
        )

        # Industry from NTEE code
        ntee = org.get("ntee_code") or org.get("nteeCode") or ""
        industry, naics_code = _ntee_to_industry(ntee)

        # Employee count from revenue/expenses proxy
        employee_min, employee_max, employee_src = None, None, None
        num_employees = org.get("num_employees") or org.get("totEmp")
        if num_employees:
            try:
                n = int(num_employees)
                employee_min, employee_max, employee_src = _bucket_employees(n)
            except (ValueError, TypeError):
                pass

        # Financials
        revenue = org.get("totrevenue") or org.get("revenue_amount") or 0

        from ..pipeline.deduplication import generate_us_company_id
        company_id = generate_us_company_id(
            ein=ein_formatted,
            legal_name=legal_name,
            state=state_code,
        )

        prov = SourceProvenanceRecord(
            source=self.SOURCE_KEY,
            source_record_id=ein_raw or legal_name,
            source_url=payload.source_url,
            retrieved_at=now,
        )

        company = USCanonicalCompany(
            company_id=company_id,
            legal_name=legal_name.upper(),
            trade_name=legal_name,
            normalized_name=_normalize_name(legal_name),
            ein=ein_formatted,
            entity_type="NONPROFIT",
            industry=industry,
            naics_code=naics_code,
            employee_count_min=employee_min,
            employee_count_max=employee_max,
            employee_count_source=employee_src,
            address=address,
            source_records=[prov],
            source_count=1,
            last_verified_at=now,
        )

        # Extract officers from 990 filing data
        _extract_990_officers(company, org, self.SOURCE_KEY)

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


def _extract_990_officers(company: USCanonicalCompany, org: Dict, source_key: str) -> None:
    """Extract officers/directors from IRS 990 data."""
    candidates = getattr(company, "_exec_candidates", [])
    # 990 filings store officers in 'officers' list
    officers = org.get("officers", []) or []
    for officer in officers:
        name = officer.get("name") or officer.get("personName") or ""
        title = officer.get("title") or officer.get("titleTxt") or "Officer"
        compensation = officer.get("compensation") or officer.get("reportableCompFromOrg") or 0
        if name and name.strip():
            candidates.append({
                "name": name.strip(),
                "title": title.strip(),
                "source": source_key,
                "compensation": compensation,
            })
    company._exec_candidates = candidates  # type: ignore[attr-defined]


def _ntee_to_industry(ntee: str) -> tuple:
    """Convert NTEE code to (industry label, NAICS code)."""
    if not ntee:
        return ("Nonprofits and Associations", "813990")
    prefix = ntee[0].upper() if ntee else "Z"
    ntee_map = {
        "A": ("Arts, Culture, and Humanities", "711110"),
        "B": ("Education", "611110"),
        "C": ("Environment and Animals", "541620"),
        "D": ("Animal-Related", "541620"),
        "E": ("Health — General and Rehabilitative", "621111"),
        "F": ("Mental Health and Crisis Intervention", "621420"),
        "G": ("Diseases, Disorders, Medical Disciplines", "621111"),
        "H": ("Medical Research", "541711"),
        "I": ("Crime and Legal-Related", "922190"),
        "J": ("Employment", "561310"),
        "K": ("Food, Agriculture, and Nutrition", "311"),
        "L": ("Housing and Shelter", "531311"),
        "M": ("Public Safety, Disaster Preparedness", "922160"),
        "N": ("Recreation and Sports", "713940"),
        "O": ("Youth Development", "813410"),
        "P": ("Human Services — Multipurpose and Other", "624110"),
        "Q": ("International, Foreign Affairs", "813212"),
        "R": ("Civil Rights, Social Action, Advocacy", "813319"),
        "S": ("Community Improvement, Capacity Building", "813410"),
        "T": ("Philanthropy, Voluntarism, and Grantmaking", "813211"),
        "U": ("Science and Technology Research", "541712"),
        "V": ("Social Science Research", "541720"),
        "W": ("Public, Societal Benefit — Multipurpose", "923"),
        "X": ("Religion-Related, Spiritual Development", "813110"),
        "Y": ("Mutual and Membership Benefit Organizations", "813910"),
        "Z": ("Unknown, Unclassified", "813990"),
    }
    return ntee_map.get(prefix, ("Nonprofits and Associations", "813990"))


def _bucket_employees(n: int) -> tuple:
    if n <= 4:
        return (1, 4, "1 to 4 employees")
    if n <= 9:
        return (5, 9, "5 to 9 employees")
    if n <= 19:
        return (10, 19, "10 to 19 employees")
    if n <= 49:
        return (20, 49, "20 to 49 employees")
    if n <= 99:
        return (50, 99, "50 to 99 employees")
    if n <= 249:
        return (100, 249, "100 to 249 employees")
    if n <= 499:
        return (250, 499, "250 to 499 employees")
    if n <= 999:
        return (500, 999, "500 to 999 employees")
    return (1000, None, "1,000+ employees")


def _normalize_name(name: str) -> str:
    suffixes = [" INC", " LLC", " CORP", " LTD", " FOUNDATION", " FUND",
                " ASSOCIATION", " SOCIETY", " INSTITUTE", " CENTER"]
    n = name.upper().strip()
    for s in suffixes:
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


propublica_client = ProPublica990Client()
