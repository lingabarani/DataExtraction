"""
SEC EDGAR Company Filing Connector
Source: https://data.sec.gov/submissions/CIK{cik}.json
        https://efts.sec.gov/LATEST/search-index?q=...
Coverage: All SEC-reporting public companies (~10,000+)
Provides: Legal name, CIK, SIC code, state, address, fiscal year end,
          Named Executive Officers (CEO/CFO/COO/CTO/Board) from 10-K and DEF 14A filings.
No API key required. Rate limit: 10 req/sec max (we use 5).
"""

import re
import time
import json
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from ..models.company import USCanonicalCompany, USAddress, USPhoneItem
from ..models.source_record import SourceProvenanceRecord, RawSourcePayload

try:
    from config_manager import config_manager
except ImportError:
    import sys
    from pathlib import Path
    _BOTA = Path(__file__).resolve().parent.parent.parent.parent
    if str(_BOTA) not in sys.path:
        sys.path.insert(0, str(_BOTA))
    from config_manager import config_manager

try:
    from botasaurus.request import request as bt_request, Request as BtRequest
    HAS_BOTASAURUS = True
except ImportError:
    HAS_BOTASAURUS = False

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?q=%22Named+Executive+Officers%22&dateRange=custom&startdt=2023-01-01&enddt=2024-12-31&forms=DEF+14A"

if HAS_BOTASAURUS:
    @bt_request(cache=True, parallel=4, output=None)
    def fetch_sec_submission_botasaurus(request: BtRequest, cik: str) -> Dict[str, Any]:
        """Botasaurus @request decorated fetcher for SEC submissions with caching and parallel execution."""
        cik_padded = str(cik).zfill(10)
        url = SUBMISSIONS_URL.format(cik=cik_padded)
        headers = {"User-Agent": config_manager.get_sec_user_agent()}
        response = request.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return {}


SIC_INDUSTRY_MAP = {
    "7372": "Prepackaged Software",
    "7371": "Computer Programming, Data Processing",
    "7374": "Computer Processing and Data Preparation",
    "3674": "Semiconductors and Related Devices",
    "3577": "Computer Peripheral Equipment",
    "3669": "Communications Equipment",
    "6022": "State Commercial Banks",
    "6020": "National Commercial Banks",
    "6159": "Federal-sponsored Credit Agencies",
    "2836": "Pharmaceutical Preparations",
    "2830": "Drugs",
    "8011": "Offices of Physicians",
    "8062": "Hospital",
    "1731": "Electrical Work Contractors",
    "1521": "General Building Contractors",
    "5411": "Grocery Stores",
    "5912": "Drug Stores and Proprietary Stores",
    "5211": "Lumber and Building Material Dealers",
    "4812": "Telephone Communications",
    "4911": "Electric Services",
    "1311": "Crude Petroleum and Natural Gas",
    "5812": "Eating Places",
}


class EdgarClient:
    """
    Fetches company data and Named Executive Officers from SEC EDGAR.
    Uses the company_tickers.json endpoint to get all public companies,
    then fetches submissions for each to extract executive names.
    """

    SOURCE_KEY = "SEC_EDGAR"
    SOURCE_NAME = "SEC EDGAR Company Filings"

    def __init__(self, rate_limit_rps: float = 5.0):
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config_manager.get_sec_user_agent(),
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json",
        })

    def _get(self, url: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        time.sleep(self.delay)
        try:
            r = self.session.get(url, params=params, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            return {}
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                time.sleep(10)
            return {}
        except Exception:
            return {}

    def fetch_company_tickers(self, max_companies: int = 5000) -> List[RawSourcePayload]:
        """
        Fetches the SEC master company list (all public companies with CIK + ticker).
        Returns raw payloads for further submission fetching.
        """
        data = self._get(COMPANY_TICKERS_URL)
        now = datetime.now(timezone.utc).isoformat()
        payloads = []
        for i, (idx, entry) in enumerate(data.items()):
            if i >= max_companies:
                break
            cik_str = str(entry.get("cik_str", "")).zfill(10)
            payloads.append(RawSourcePayload(
                source=self.SOURCE_KEY,
                source_record_id=f"CIK{cik_str}",
                source_url=SUBMISSIONS_URL.format(cik=cik_str),
                raw_data={
                    "cik": cik_str,
                    "ticker": entry.get("ticker", ""),
                    "title": entry.get("title", ""),
                },
                retrieved_at=now,
            ))
        return payloads

    def fetch_submissions(self, cik: str) -> Dict[str, Any]:
        """Fetches full submission data for a given CIK using Botasaurus caching/parallel request if available."""
        cik_padded = str(cik).zfill(10)
        if HAS_BOTASAURUS:
            try:
                res = fetch_sec_submission_botasaurus(cik_padded)
                if res:
                    return res
            except Exception:
                pass
        return self._get(SUBMISSIONS_URL.format(cik=cik_padded))


    def extract_executives_from_filing_text(self, text: str) -> List[Dict[str, str]]:
        """
        Parses Named Executive Officers section from 10-K/DEF 14A text.
        Returns list of {name, title} dicts.
        """
        executives = []
        seen = set()

        # Pattern 1: "Name, Title" table patterns from proxy filings
        patterns = [
            re.compile(
                r"([A-Z][a-z]+(?: [A-Z][a-z.]+){1,3})[,\s]+(?:age \d+[,\s]+)?("
                r"(?:Chief|President|Chairman|Chief Executive|Chief Financial|"
                r"Chief Operating|Chief Technology|Chief Marketing|Chief Legal|"
                r"Chief Human|Chief Revenue|Chief Strategy|Chief Information|"
                r"Chief Security|Executive Vice President|Senior Vice President|"
                r"Vice President|Director|Treasurer|Secretary|General Counsel)"
                r"[^,\n]{0,80})",
                re.MULTILINE
            ),
            # CEO/CFO labels
            re.compile(
                r"([A-Z][a-z]+(?: [A-Z][a-z.]+){1,3})\s*\n\s*(CEO|CFO|COO|CTO|CMO|CHRO|CLO|CRO|CSO|CIO|CDO|EVP|SVP)",
                re.MULTILINE
            ),
        ]

        for pattern in patterns:
            for m in pattern.finditer(text[:50000]):
                name = m.group(1).strip()
                title = m.group(2).strip()
                if name and title and name not in seen and len(name) > 4:
                    seen.add(name)
                    executives.append({"name": name, "title": title, "source": self.SOURCE_KEY})

        return executives[:10]  # Cap at 10 per company

    def normalize_submission(
        self,
        submission: Dict[str, Any],
        ticker_payload: Optional[RawSourcePayload] = None,
    ) -> Optional[USCanonicalCompany]:
        """Normalize a EDGAR submissions response to USCanonicalCompany."""
        if not submission:
            return None

        now = datetime.now(timezone.utc).isoformat()

        cik = str(submission.get("cik", "")).zfill(10)
        legal_name = (submission.get("name") or "").strip()
        if not legal_name:
            return None

        sic = str(submission.get("sic", "") or "")
        industry = SIC_INDUSTRY_MAP.get(sic, _sic_to_industry(sic))
        state_code = submission.get("stateOfIncorporation", "") or ""
        phone_raw = submission.get("phone", "") or ""

        # Address
        addresses = submission.get("addresses", {}) or {}
        biz_addr = addresses.get("business", {}) or {}
        address = USAddress(
            street=biz_addr.get("street1"),
            city=biz_addr.get("city"),
            state=_state_code_to_name(biz_addr.get("stateOrCountry", "")),
            state_code=biz_addr.get("stateOrCountry", ""),
            zip_code=biz_addr.get("zipCode", ""),
            country="United States",
        )

        # Website
        website = submission.get("website") or ""
        domain = _extract_domain(website)

        # Phone
        phones = []
        if phone_raw:
            clean_ph = _clean_phone(phone_raw)
            if clean_ph:
                phones.append(USPhoneItem(value=clean_ph, source=self.SOURCE_KEY, type="OFFICE"))

        from ..pipeline.deduplication import generate_us_company_id
        company_id = generate_us_company_id(
            ein=None,
            legal_name=legal_name,
            state=biz_addr.get("stateOrCountry", ""),
            cik=cik,
        )

        prov = SourceProvenanceRecord(
            source=self.SOURCE_KEY,
            source_record_id=f"CIK{cik}",
            source_url=SUBMISSIONS_URL.format(cik=cik),
            retrieved_at=now,
        )

        company = USCanonicalCompany(
            company_id=company_id,
            legal_name=legal_name.upper(),
            trade_name=legal_name,
            normalized_name=_normalize_company_name(legal_name),
            cik=cik,
            sic_code=sic or None,
            state_of_incorporation=state_code or None,
            website=website or None,
            domain=domain or None,
            industry=industry or None,
            phone=phones[0].value if phones else None,
            phones=phones,
            address=address,
            source_records=[prov],
            source_count=1,
            last_verified_at=now,
        )

        return company

    def normalize_batch(
        self,
        ticker_payloads: List[RawSourcePayload],
        fetch_submissions: bool = True,
    ) -> List[USCanonicalCompany]:
        """
        Normalizes a batch of company ticker payloads.
        Optionally fetches full submissions for each CIK.
        """
        companies = []
        for payload in ticker_payloads:
            try:
                if fetch_submissions:
                    submission = self.fetch_submissions(payload.raw_data.get("cik", ""))
                    company = self.normalize_submission(submission, ticker_payload=payload)
                else:
                    # Use minimal data from ticker list
                    company = USCanonicalCompany(
                        company_id=f"us_edgar_{payload.raw_data.get('cik', '')}",
                        legal_name=payload.raw_data.get("title", "").upper(),
                        trade_name=payload.raw_data.get("title", ""),
                        normalized_name=_normalize_company_name(payload.raw_data.get("title", "")),
                        cik=payload.raw_data.get("cik", ""),
                        source_records=[SourceProvenanceRecord(
                            source=self.SOURCE_KEY,
                            source_record_id=f"CIK{payload.raw_data.get('cik', '')}",
                            source_url=payload.source_url,
                            retrieved_at=payload.retrieved_at,
                        )],
                        source_count=1,
                        last_verified_at=payload.retrieved_at,
                    )
                if company and company.legal_name:
                    companies.append(company)
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
    return None


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


def _normalize_company_name(name: str) -> str:
    suffixes = [" LLC", " INC", " CORP", " LTD", " LP", " LLP", " PC",
                " PLLC", " CO", " COMPANY", " INCORPORATED", " LIMITED",
                " CORPORATION", " GROUP", " HOLDINGS"]
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


def _sic_to_industry(sic: str) -> str:
    if not sic:
        return "Professional Services"
    try:
        code = int(sic)
    except ValueError:
        return "Professional Services"
    if 100 <= code <= 999:
        return "Agriculture, Forestry, Mining"
    if 1000 <= code <= 1499:
        return "Mining"
    if 1500 <= code <= 1799:
        return "Construction"
    if 2000 <= code <= 3999:
        return "Manufacturing"
    if 4000 <= code <= 4999:
        return "Transportation, Communications, Utilities"
    if 5000 <= code <= 5199:
        return "Wholesale Trade"
    if 5200 <= code <= 5999:
        return "Retail Trade"
    if 6000 <= code <= 6999:
        return "Finance, Insurance, Real Estate"
    if 7000 <= code <= 8999:
        return "Services"
    if 9000 <= code <= 9999:
        return "Public Administration"
    return "Other"


edgar_client = EdgarClient()
