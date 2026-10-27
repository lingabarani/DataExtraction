"""
SAM.gov Entity Information API Connector
Source: https://api.sam.gov/entity-information/v3/entities
Coverage: 700,000+ active US federal government vendors
Provides: Legal name, EIN, CAGE code, UEI, NAICS, address, phone, website,
          Point of Contact (POC) name, email, and title — the richest open US source
          for company + executive contact data.
No API key required for basic entity data in public mode.
"""

import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..models.company import USCanonicalCompany, USAddress, USPhoneItem, USEmailItem
from ..models.person import USDecisionMaker
from ..models.source_record import SourceProvenanceRecord, RawSourcePayload

try:
    from botasaurus.request import request as bt_request, Request as BtRequest
    HAS_BOTASAURUS = True
except ImportError:
    HAS_BOTASAURUS = False

BASE_URL = "https://api.sam.gov/entity-information/v3/entities"

if HAS_BOTASAURUS:
    @bt_request(cache=True, parallel=4, output=None)
    def fetch_sam_entities_botasaurus(request: BtRequest, params: Dict[str, Any]) -> Dict[str, Any]:
        """Botasaurus @request decorated fetcher for SAM.gov entities with caching and parallel execution."""
        headers = {
            "User-Agent": "OneExtraction-B2B-Pipeline/1.0 (research POC)",
            "Accept": "application/json",
        }
        response = request.get(BASE_URL, params=params, headers=headers)
        if response.status_code == 200:
            return response.json()
        return {}


# NAICS → Industry label map (abbreviated — see full in classifier)
NAICS_INDUSTRY_MAP = {
    "541511": "Custom Computer Programming Services",
    "541512": "Computer Systems Design Services",
    "541519": "Other Computer Related Services",
    "541330": "Engineering Services",
    "541611": "Administrative Management Consulting",
    "561110": "Office Administrative Services",
    "238220": "Plumbing, Heating, and Air-Conditioning Contractors",
    "336413": "Aircraft Parts and Auxiliary Equipment",
    "332119": "Metal Crown, Closure, and Other Metal Stamping",
    "611430": "Professional and Management Development Training",
    "621111": "Offices of Physicians (except Mental Health Specialists)",
    "522110": "Commercial Banking",
    "236220": "Commercial and Institutional Building Construction",
    "484121": "General Freight Trucking, Long-Distance, Truckload",
    "811310": "Commercial and Industrial Machinery Repair and Maintenance",
    "517311": "Wired Telecommunications Carriers",
    "541820": "Public Relations Agencies",
    "561320": "Temporary Help Services",
    "721110": "Hotels and Motels (except Casino Hotels)",
    "722511": "Full-Service Restaurants",
}

EMPLOYEE_BAND_MAP = {
    "A": (1, 4, "1 to 4 employees"),
    "B": (5, 9, "5 to 9 employees"),
    "C": (10, 19, "10 to 19 employees"),
    "D": (20, 49, "20 to 49 employees"),
    "E": (50, 99, "50 to 99 employees"),
    "F": (100, 249, "100 to 249 employees"),
    "G": (250, 499, "250 to 499 employees"),
    "H": (500, 999, "500 to 999 employees"),
    "I": (1000, 4999, "1,000 to 4,999 employees"),
    "J": (5000, 9999, "5,000 to 9,999 employees"),
    "K": (10000, None, "10,000+ employees"),
}


class SamGovClient:
    """
    Fetches company and executive Point-of-Contact data from the SAM.gov Entity API.
    Uses public mode (no API key for basic fields). Paginates up to max_records.
    """

    SOURCE_KEY = "SAM_GOV"
    SOURCE_NAME = "SAM.gov Federal Vendor Registry"

    def __init__(self, api_key: Optional[str] = None, rate_limit_rps: float = 1.0):
        self.api_key = api_key or ""
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Pipeline/1.0 (research POC)",
            "Accept": "application/json",
        })

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute GET request to SAM.gov API with rate limiting and Botasaurus caching."""
        if self.api_key:
            params["api_key"] = self.api_key
        if HAS_BOTASAURUS:
            try:
                res = fetch_sam_entities_botasaurus(params)
                if res:
                    return res
            except Exception:
                pass

        time.sleep(self.delay)
        try:
            r = self.session.get(BASE_URL, params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            return {}
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                time.sleep(5)
            return {}
        except Exception:
            return {}


    def fetch_entities(
        self,
        naics_code: Optional[str] = None,
        state: Optional[str] = None,
        entity_type: str = "2~3",   # 2=Business, 3=Non-Federal Government
        max_records: int = 1000,
    ) -> List[RawSourcePayload]:
        """
        Fetches entity records from SAM.gov.
        Filters by NAICS code and/or state if provided.
        Returns raw payloads for normalization.
        """
        params: Dict[str, Any] = {
            "registrationStatus": "A",       # Active registrations only
            "purposeOfRegistrationCode": "Z2",  # All awards
            "entityEFTIndicator": "",
            "samExtractCode": "1",
            "size": 10,
            "page": 0,
        }
        if naics_code:
            params["naicsCode"] = naics_code
        if state:
            params["physicalAddressProvinceOrStateCode"] = state

        raw_payloads: List[RawSourcePayload] = []
        total_fetched = 0

        while total_fetched < max_records:
            data = self._get(params)
            entities = data.get("entityData", []) or []
            if not entities:
                break

            for entity in entities:
                if total_fetched >= max_records:
                    break
                raw_payloads.append(RawSourcePayload(
                    source=self.SOURCE_KEY,
                    source_record_id=entity.get("entityRegistration", {}).get("ueiSAM", f"sam_{total_fetched}"),
                    source_url=f"{BASE_URL}?ueiSAM={entity.get('entityRegistration', {}).get('ueiSAM', '')}",
                    raw_data=entity,
                ))
                total_fetched += 1

            total_in_page = len(entities)
            if total_in_page < params["size"]:
                break
            params["page"] += 1

        return raw_payloads

    def normalize(self, payload: RawSourcePayload) -> Optional[USCanonicalCompany]:
        """
        Normalize a SAM.gov entity payload to USCanonicalCompany.
        Extracts company fields + Point of Contact as decision-maker candidate.
        """
        raw = payload.raw_data
        now = datetime.now(timezone.utc).isoformat()

        reg = raw.get("entityRegistration", {}) or {}
        core = raw.get("coreData", {}) or {}
        assertions = raw.get("assertions", {}) or {}
        pocs = raw.get("pointsOfContact", {}) or {}

        # ── Entity Identity ────────────────────────────────────────
        uei = reg.get("ueiSAM", "")
        cage_code = reg.get("cageCode", "")
        legal_name = reg.get("legalBusinessName", "") or ""
        dba_name = reg.get("dbaName") or reg.get("tradeName") or legal_name

        # EIN from financial information
        financial = core.get("financialInformation", {}) or {}
        ein_raw = financial.get("usTaxNumber", "") or ""
        ein = ein_raw.replace("-", "").strip() if ein_raw else None
        ein_formatted = f"{ein[:2]}-{ein[2:]}" if ein and len(ein) >= 3 else ein_raw or None

        # ── Entity Type ───────────────────────────────────────────
        biz_types = assertions.get("goodsAndServices", {}) or {}
        entity_structure = reg.get("entityStructureCode", "")
        entity_type_map = {
            "2L": "LLC", "8H": "LLC", "ZZ": "CORPORATION",
            "8I": "SOLE_PROPRIETOR", "X6": "PARTNERSHIP",
            "CY": "NONPROFIT", "2J": "PARTNERSHIP",
        }
        entity_type = entity_type_map.get(entity_structure, "CORPORATION")

        # ── Address ───────────────────────────────────────────────
        addr_data = core.get("physicalAddress", {}) or {}
        address = USAddress(
            street=addr_data.get("addressLine1") or addr_data.get("streetAddress"),
            city=addr_data.get("city"),
            state=_state_code_to_name(addr_data.get("stateOrProvinceCode", "")),
            state_code=addr_data.get("stateOrProvinceCode", ""),
            zip_code=addr_data.get("zipCode", ""),
            country="United States",
        )

        # ── Phones & Emails ───────────────────────────────────────
        phones = []
        emails = []
        phone_val = ""

        # Extract from POC data
        govt_poc = pocs.get("governmentBusinessPOC", {}) or {}
        elec_poc = pocs.get("electronicBusinessPOC", {}) or {}

        for poc_block in [govt_poc, elec_poc]:
            if isinstance(poc_block, dict):
                ph = poc_block.get("phoneNumber", "") or poc_block.get("usPhone", "")
                if ph:
                    clean_ph = _clean_phone(ph)
                    if clean_ph:
                        phones.append(USPhoneItem(value=clean_ph, source=self.SOURCE_KEY, type="OFFICE"))
                        if not phone_val:
                            phone_val = clean_ph

        # ── NAICS / Industry ──────────────────────────────────────
        naics_list = assertions.get("goodsAndServices", {})
        if isinstance(naics_list, dict):
            naics_list = naics_list.get("naicsCode", []) or []
        naics_code = ""
        if naics_list and isinstance(naics_list, list):
            for n in naics_list:
                if isinstance(n, dict) and n.get("isPrimary"):
                    naics_code = str(n.get("naicsCode", ""))
                    break
            if not naics_code and naics_list:
                first = naics_list[0]
                naics_code = str(first.get("naicsCode", "") if isinstance(first, dict) else first)
        industry = NAICS_INDUSTRY_MAP.get(naics_code, _naics_to_generic_industry(naics_code))

        # ── Website ───────────────────────────────────────────────
        website_raw = core.get("entityURL", "") or reg.get("entityURL", "") or ""
        website = _clean_url(website_raw)
        domain = _extract_domain(website)

        # ── Build unique ID ───────────────────────────────────────
        fp_key = (uei or legal_name + (address.state_code or "")).upper().strip()
        from ..pipeline.deduplication import generate_us_company_id
        company_id = generate_us_company_id(
            ein=ein_formatted,
            legal_name=legal_name,
            state=address.state_code or address.state or "",
        )

        prov = SourceProvenanceRecord(
            source=self.SOURCE_KEY,
            source_record_id=uei or legal_name,
            source_url=payload.source_url,
            retrieved_at=now,
        )

        # ── State of incorporation ─────────────────────────────────
        soi = reg.get("stateOfIncorporationCode", "") or address.state_code or ""

        company = USCanonicalCompany(
            company_id=company_id,
            legal_name=legal_name.upper() if legal_name else None,
            trade_name=dba_name or legal_name,
            normalized_name=_normalize_company_name(legal_name),
            ein=ein_formatted,
            entity_type=entity_type,
            cage_code=cage_code or None,
            uei=uei or None,
            state_of_incorporation=soi or None,
            website=website or None,
            domain=domain or None,
            industry=industry or None,
            naics_code=naics_code or None,
            phone=phone_val or None,
            phones=phones,
            emails=emails,
            address=address,
            source_records=[prov],
            source_count=1,
            last_verified_at=now,
        )

        # ── Attach POC as raw executive candidate ─────────────────
        _attach_poc_candidates(company, pocs, self.SOURCE_KEY)

        return company

    def normalize_batch(self, payloads: List[RawSourcePayload]) -> List[USCanonicalCompany]:
        """Normalize a batch of raw SAM.gov payloads."""
        companies = []
        for payload in payloads:
            try:
                c = self.normalize(payload)
                if c and c.legal_name:
                    companies.append(c)
            except Exception:
                continue
        return companies


def _attach_poc_candidates(company: USCanonicalCompany, pocs: Dict, source_key: str) -> None:
    """Extract Points of Contact from SAM.gov and attach as raw executive candidates."""
    poc_slots = [
        ("governmentBusinessPOC", "Government Business POC"),
        ("electronicBusinessPOC", "Electronic Business POC"),
        ("governmentBusinessAlternatePOC", "Alternate Government POC"),
        ("pastPerformancePOC", "Past Performance POC"),
    ]
    candidates = getattr(company, "_exec_candidates", [])
    for slot_key, slot_label in poc_slots:
        poc = pocs.get(slot_key)
        if not poc or not isinstance(poc, dict):
            continue
        first = poc.get("firstName", "") or ""
        last = poc.get("lastName", "") or ""
        full = f"{first} {last}".strip()
        if not full:
            continue
        title = poc.get("title") or slot_label
        phone = poc.get("phoneNumber") or poc.get("usPhone") or company.phone
        email_addr = poc.get("emailAddress") or poc.get("email")
        if email_addr:
            company.emails.append(USEmailItem(value=email_addr, source=source_key))
        candidates.append({
            "name": full,
            "title": title,
            "phone": _clean_phone(phone) if phone else None,
            "email": email_addr,
            "source": source_key,
        })
    company._exec_candidates = candidates  # type: ignore[attr-defined]


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


def _normalize_company_name(name: str) -> str:
    if not name:
        return ""
    suffixes = [" LLC", " INC", " CORP", " LTD", " LP", " LLP", " PC",
                " PLLC", " DBA", " CO", " COMPANY", " INCORPORATED",
                " LIMITED", " CORPORATION", " GROUP", " HOLDINGS", " SERVICES"]
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


def _naics_to_generic_industry(naics: str) -> str:
    if not naics or len(naics) < 2:
        return "Professional Services"
    prefix = naics[:2]
    prefix_map = {
        "11": "Agriculture, Forestry, Fishing",
        "21": "Mining, Quarrying, Oil and Gas",
        "22": "Utilities",
        "23": "Construction",
        "31": "Manufacturing", "32": "Manufacturing", "33": "Manufacturing",
        "42": "Wholesale Trade",
        "44": "Retail Trade", "45": "Retail Trade",
        "48": "Transportation and Warehousing", "49": "Transportation and Warehousing",
        "51": "Information Technology and Media",
        "52": "Finance and Insurance",
        "53": "Real Estate and Rental",
        "54": "Professional, Scientific, and Technical Services",
        "55": "Management of Companies",
        "56": "Administrative and Support Services",
        "61": "Educational Services",
        "62": "Health Care and Social Assistance",
        "71": "Arts, Entertainment, and Recreation",
        "72": "Accommodation and Food Services",
        "81": "Other Services",
        "92": "Public Administration",
    }
    return prefix_map.get(prefix, "Professional Services")


sam_gov_client = SamGovClient()
