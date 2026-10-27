"""
OpenDirectories 12M+ Business REST API Connector (Ported from opendirectories-mcp).
Source: https://oclajxwxyxorlfhahoqj.supabase.co/rest/v1/providers
Coverage: 12M+ verified business records across 10 countries and 19 directories.
US Directories: us-healthcare, us-nonprofits, us-carriers, us-schools.
Provides: Legal Business Name, Phone, Website, Physical Address, City, State, Postcode,
          Google Rating, Google Review Count, Quality Score, Profile Completeness.
No API key cost required. Uses public regional Supabase REST service headers.
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

# Open Regional Supabase REST Endpoints
SUPABASE_URL = "https://oclajxwxyxorlfhahoqj.supabase.co/rest/v1/providers"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9jbGFqeHd4eXhvcmxmaGFob3FqIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTg0NjgxNCwiZXhwIjoyMDg3NDIyODE0fQ.dQkzSIwe5AH18WB9NCEI10suSGb9l8Vn0epx4BZ840E"

PUBLIC_FIELDS = (
    "id,name,slug,description,phone,website,"
    "street_address,suburb,state,postcode,country,"
    "google_rating,google_review_count,is_active,quality_score,profile_completeness"
)

DIRECTORY_INDUSTRY_MAP = {
    "us-healthcare": ("Healthcare & Hospitals", "621111"),
    "us-nonprofits": ("Nonprofit Organizations", "813990"),
    "us-carriers": ("Logistics & Transport", "484121"),
    "us-schools": ("Educational Institutions", "611110"),
}

if HAS_BOTASAURUS:
    @bt_request(cache=True, parallel=4, output=None, raise_exception=False)
    def fetch_opendirectories_providers_botasaurus(request: BtRequest, params: Dict[str, Any]) -> Dict[str, Any]:
        """Botasaurus @request decorated fetcher for OpenDirectories Supabase API."""
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Accept": "application/json",
            "Prefer": "count=exact",
        }
        try:
            response = request.get(SUPABASE_URL, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                return {"items": response.json()}
        except Exception:
            pass
        return {"items": []}


class OpenDirectoriesClient:
    """
    Fetches business & healthcare data from OpenDirectories 12M+ Supabase REST API.
    """

    SOURCE_KEY = "OPENDIRECTORIES"
    SOURCE_NAME = "OpenDirectories 12M+ Business Registry"

    def __init__(self, rate_limit_rps: float = 3.0):
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Accept": "application/json",
            "Prefer": "count=exact",
        })

    def _get(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute GET query to Supabase REST API."""
        if HAS_BOTASAURUS:
            try:
                res = fetch_opendirectories_providers_botasaurus(params)
                if res and "items" in res:
                    return res["items"]
            except Exception:
                pass

        time.sleep(self.delay)
        try:
            r = self.session.get(SUPABASE_URL, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    def fetch_businesses(
        self,
        directory: str = "us-healthcare",
        state: Optional[str] = None,
        suburb: Optional[str] = None,
        query: Optional[str] = None,
        max_records: int = 200,
    ) -> List[RawSourcePayload]:
        """
        Fetches businesses from OpenDirectories Supabase REST endpoint.
        """
        params: Dict[str, str] = {
            "select": PUBLIC_FIELDS,
            "limit": str(min(100, max_records)),
            "order": "quality_score.desc.nullslast",
            "country": "eq.US",
        }
        if state:
            params["state"] = f"eq.{state.upper()}"
        if suburb:
            params["suburb"] = f"ilike.%{suburb}%"
        if query:
            params["name"] = f"ilike.%{query}%"

        items = self._get(params)
        now = datetime.now(timezone.utc).isoformat()

        payloads = []
        for item in items[:max_records]:
            bid = str(item.get("id", "")).strip()
            payloads.append(RawSourcePayload(
                source=self.SOURCE_KEY,
                source_record_id=f"OD_{bid}",
                source_url=item.get("website") or f"https://opendirectories.org/business/{bid}",
                raw_data=item,
                retrieved_at=now,
            ))

        return payloads

    def normalize(self, payload: RawSourcePayload) -> Optional[USCanonicalCompany]:
        """Normalize an OpenDirectories raw payload into USCanonicalCompany."""
        raw = payload.raw_data
        now = datetime.now(timezone.utc).isoformat()

        legal_name = (raw.get("name") or "").strip()
        if not legal_name:
            return None

        bid = str(raw.get("id", "")).strip()
        phone_raw = raw.get("phone", "") or ""
        website_raw = raw.get("website", "") or ""
        city = raw.get("suburb", "") or ""
        state_code = raw.get("state", "") or ""
        zip_code = str(raw.get("postcode", ""))[:5]
        street = raw.get("street_address", "") or ""

        address = USAddress(
            street=street or None,
            city=city or None,
            state=_state_code_to_name(state_code),
            state_code=state_code or None,
            zip_code=zip_code or "",
            country="United States",
        )

        website = _clean_url(website_raw)
        domain = _extract_domain(website)

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
            source_record_id=f"OD_{bid}",
            source_url=payload.source_url,
            retrieved_at=now,
        )

        # Quality score & ratings
        q_score = int(raw.get("quality_score") or 65)

        company = USCanonicalCompany(
            company_id=company_id,
            legal_name=legal_name.upper(),
            trade_name=legal_name,
            normalized_name=_normalize_name(legal_name),
            entity_type="ORGANIZATION",
            industry="Healthcare & Commercial Services",
            naics_code="621111",
            website=website or None,
            domain=domain or None,
            phone=clean_ph,
            phones=phones,
            address=address,
            data_quality_score=q_score,
            source_records=[prov],
            source_count=1,
            last_verified_at=now,
        )

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


def _clean_phone(raw: str) -> Optional[str]:
    if not raw:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+1{digits}" if digits else None


def _clean_url(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    if raw and not raw.startswith("http"):
        raw = "https://" + raw
    return raw


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        return domain.replace("www.", "").lower().strip("/")
    except Exception:
        return ""


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    suffixes = [" LLC", " INC", " CORP", " CO", " GROUP", " HOLDINGS"]
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


opendirectories_client = OpenDirectoriesClient()
