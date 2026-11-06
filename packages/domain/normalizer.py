"""
DataExtraction — Domain Normalizer
==================================
High-throughput data cleaning, unicode transforms, and standard corporate entity normalization.
Maps raw records from external statutory, scraping, and vendor sources into unified domain models.

Supported sources:
  - INTERNAL_JSON   : internal JSON graph representations
  - CSV             : raw batch tabular exports
  - PDL             : People Data Labs API format
  - SEC             : SEC EDGAR financial disclosures
  - APOLLO          : Apollo.io CRM/API exports
  - ZOOMINFO        : ZoomInfo enterprise exports
  - OSM             : OpenStreetMap geospatial entities
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tldextract
    _EXTRACTOR = tldextract.TLDExtract(
        cache_dir=str(Path.home() / ".cache" / "tldextract"),
        include_psl_private_domains=True
    )
except ImportError:
    _EXTRACTOR = None


# ─────────────────────────────────────────────────────────────────────────────
# General Cleaning Helpers
# ─────────────────────────────────────────────────────────────────────────────

def clean_string(value: Optional[Any]) -> Optional[str]:
    """Strip whitespace, normalize unicode, return None for empty values."""
    if value is None:
        return None
    v = str(value).strip()
    return v if v else None

_clean = clean_string


def to_int(value: Optional[Any]) -> Optional[int]:
    """Safely coerce integer values."""
    if value is None or value == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return None

_to_int = to_int


def to_float(value: Optional[Any]) -> Optional[float]:
    """Safely coerce float values."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None

_to_float = to_float


def to_bool(value: Optional[Any]) -> Optional[bool]:
    """Safely coerce boolean flags."""
    if value is None or value == "":
        return None
    v = str(value).strip().lower()
    if v in ("true", "1", "yes", "t", "y"):
        return True
    if v in ("false", "0", "no", "f", "n"):
        return False
    return None

_to_bool = to_bool


def utc_now_iso() -> str:
    """Return ISO 8601 formatted UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()

_now = utc_now_iso


def as_json_string(value: Optional[Any]) -> str:
    """Safely serialize input object to JSON string."""
    if value is None:
        return "[]"
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return "[]"
        if (v.startswith("{") and v.endswith("}")) or (v.startswith("[") and v.endswith("]")):
            try:
                json.loads(v)
                return v
            except Exception:
                pass
        return json.dumps([v])
    try:
        return json.dumps(value)
    except Exception:
        return "[]"

_as_json = as_json_string


# ─────────────────────────────────────────────────────────────────────────────
# Legal Suffix Normalization
# ─────────────────────────────────────────────────────────────────────────────

# Comprehensive terminal legal suffix patterns for US, MX, Commonwealth, and Europe.
LEGAL_SUFFIX_PATTERNS = [
    # Multi-token Mexican corporate regimes
    r"S\.?\s*A\.?\s*B\.?\s*DE\s*C\.?\s*V\.?",
    r"S\.?\s*A\.?\s*DE\s*C\.?\s*V\.?",
    r"S\.?\s*DE\s*R\.?\s*L\.?\s*DE\s*C\.?\s*V\.?",
    r"S\.?\s*P\.?\s*R\.?\s*DE\s*R\.?\s*L\.?",
    r"S\.?\s*DE\s*R\.?\s*L\.?",
    r"S\.?\s*A\.?\s*S\.?",
    r"S\.?\s*A\.?",
    r"S\.?\s*C\.?",
    r"S\.?\s*R\.?\s*L\.?",
    # Multi-token US / Commonwealth
    r"PVT\.?\s*LTD\.?",
    r"PRIVATE\s*LIMITED",
    r"PUBLIC\s*LIMITED\s*COMPANY",
    r"LIMITED\s*LIABILITY\s*COMPANY",
    r"LIMITED\s*PARTNERSHIP",
    r"&\s*CO\.?",
    r"LTD\.?\s*CO\.?",
    r"L\.?\s*L\.?\s*C\.?",
    r"L\.?\s*L\.?\s*P\.?",
    r"L\.?\s*P\.?",
    r"P\.?\s*C\.?",
    r"P\.?\s*L\.?\s*L\.?\s*C\.?",
    r"INC\.?",
    r"INCORPORATED",
    r"CORP\.?",
    r"CORPORATION",
    r"LIMITED",
    r"LTD\.?",
    r"CO\.?",
    # European / Global
    r"G\.?\s*M\.?\s*B\.?\s*H\.?",
    r"A\.?\s*G\.?",
    r"S\.?\s*E\.?",
    r"B\.?\s*V\.?",
    r"N\.?\s*V\.?",
    r"SPA",
    r"SARL",
]

_LEGAL_SUFFIX_REGEX = re.compile(
    r"(?:[\s,\.\-_/]+(?:" + "|".join(LEGAL_SUFFIX_PATTERNS) + r"))+$",
    re.IGNORECASE,
)


def clean_legal_suffixes(name: Optional[str]) -> Optional[str]:
    """
    Remove terminal legal entity suffixes while preserving the base corporate name.
    
    Supports US (Inc, LLC, Corp, LLP), Mexico (S.A. de C.V., S.A.B. de C.V., S. de R.L.),
    Commonwealth (Ltd, Pvt Ltd), and European regimes (GmbH, AG, SE).

    Only removes suffixes when they occur as terminal tokens; inner or leading occurrences
    (e.g., 'Incorporate Global Inc.', 'Company Global Ltd') are preserved.

    Returns:
        Cleaned, uppercase normalized corporate name, or None if input is empty.
    """
    if name is None:
        return None
    s = str(name).strip()
    if not s:
        return None

    cleaned = _LEGAL_SUFFIX_REGEX.sub("", s).strip()
    cleaned = re.sub(r"[\s,\.\-_/]+$", "", cleaned).strip()

    return cleaned.upper() if cleaned else s.strip().upper()


def clean_domain(website_or_domain: Optional[Any]) -> Optional[str]:
    """Extract registered domain from a URL or domain string using tldextract."""
    if not website_or_domain:
        return None
    d = str(website_or_domain).strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = re.sub(r"^www\.", "", d)
    d = d.split("/")[0].split("?")[0].split(":")[0].strip()

    if not d or "." not in d:
        return None

    if _EXTRACTOR is not None:
        ext = _EXTRACTOR(d)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"

    parts = [p for p in d.split(".") if p]
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"

    return d or None

_clean_domain = clean_domain


# ─────────────────────────────────────────────────────────────────────────────
# Normalization Implementations
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_company_internal_json(raw: dict) -> dict:
    addr = raw.get("address") or {}
    postal = clean_string(addr.get("postal_code") or raw.get("postal_code"))
    c_id = clean_string(raw.get("id") or raw.get("company_id"))
    name = clean_string(raw.get("name") or raw.get("company_name") or raw.get("legal_name"))
    legal_name = clean_string(raw.get("legal_name") or name)
    state = clean_string(addr.get("state") or raw.get("state"))
    state_code = clean_string(addr.get("state_code") or raw.get("state_code") or state)
    return {
        "id": c_id,
        "name": name,
        "company_name": name,
        "legal_name": legal_name,
        "domain": clean_domain(raw.get("domain") or raw.get("website")),
        "website": clean_string(raw.get("website") or raw.get("domain")),
        "industry": clean_string(raw.get("industry")),
        "employee_count": to_int(raw.get("employee_count")),
        "revenue_range": clean_string(raw.get("revenue_range")),
        "street_address": clean_string(addr.get("street") or raw.get("street_address")),
        "city": clean_string(addr.get("city") or raw.get("city")),
        "state": state,
        "state_code": state_code,
        "postal_code": postal,
        "country": clean_string(addr.get("country") or raw.get("country") or "US"),
        "phone": clean_string(raw.get("phone")),
        "tax_id": clean_string(raw.get("tax_id") or raw.get("ein") or raw.get("rfc")),
        "ein": clean_string(raw.get("ein")),
        "rfc": clean_string(raw.get("rfc")),
        "normalized_name": clean_legal_suffixes(name),
        "source": "INTERNAL_JSON",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }


def _normalize_company_csv(raw: dict) -> dict:
    name = raw.get("Company") or raw.get("company_name") or raw.get("name") or raw.get("Account Name")
    website = raw.get("Website") or raw.get("website") or raw.get("domain") or raw.get("Company Website")
    return {
        "company_name": clean_string(name),
        "legal_name": None,
        "domain": clean_domain(website),
        "website": clean_string(website),
        "industry": clean_string(raw.get("Industry") or raw.get("industry")),
        "employee_count": to_int(raw.get("Employees") or raw.get("employee_count") or raw.get("Num Employees")),
        "revenue_range": clean_string(raw.get("Annual Revenue") or raw.get("revenue_range") or raw.get("Revenue")),
        "street_address": clean_string(raw.get("Street") or raw.get("street_address") or raw.get("Address")),
        "city": clean_string(raw.get("City") or raw.get("city")),
        "state": clean_string(raw.get("State") or raw.get("state")),
        "postal_code": clean_string(raw.get("Postal Code") or raw.get("postal_code") or raw.get("Zip")),
        "country": clean_string(raw.get("Country") or raw.get("country") or "US"),
        "phone": clean_string(raw.get("Phone") or raw.get("Company Phone") or raw.get("phone")),
        "tax_id": clean_string(raw.get("Tax ID") or raw.get("tax_id") or raw.get("EIN")),
        "ein": clean_string(raw.get("EIN") or raw.get("ein")),
        "rfc": clean_string(raw.get("RFC") or raw.get("rfc")),
        "normalized_name": clean_legal_suffixes(name),
        "source": "CSV",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }


def _normalize_company_sec(raw: dict) -> dict:
    name = raw.get("company_name") or raw.get("name")
    st_inc = clean_string(raw.get("state_of_incorporation") or raw.get("state_incorporation") or raw.get("stateOfIncorporation"))
    st_code = clean_string(raw.get("state_code") or raw.get("state") or st_inc)
    c_id = clean_string(raw.get("id") or raw.get("company_id") or raw.get("cik"))
    return {
        "id": c_id,
        "name": clean_string(name),
        "company_name": clean_string(name),
        "legal_name": clean_string(name),
        "cik": clean_string(raw.get("cik")),
        "sic_code": clean_string(raw.get("sic") or raw.get("sic_code")),
        "state_code": st_code,
        "state_of_incorporation": st_inc,
        "domain": clean_domain(raw.get("website") or raw.get("domain")),
        "website": clean_string(raw.get("website")),
        "industry": clean_string(raw.get("sic_description") or raw.get("industry")),
        "employee_count": to_int(raw.get("employee_count")),
        "revenue_range": clean_string(raw.get("revenue_range")),
        "street_address": clean_string(raw.get("street_address")),
        "city": clean_string(raw.get("city")),
        "state": clean_string(raw.get("state") or st_code),
        "postal_code": clean_string(raw.get("postal_code")),
        "country": clean_string(raw.get("country") or "US"),
        "phone": clean_string(raw.get("phone")),
        "tax_id": clean_string(raw.get("ein") or raw.get("tax_id")),
        "ein": clean_string(raw.get("ein")),
        "rfc": None,
        "normalized_name": clean_legal_suffixes(name),
        "source": "SEC",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }


def normalize_company(raw: dict, source: str) -> dict:
    """
    Standardize a raw company record from any supported source into the domain schema.
    """
    src = (source or "INTERNAL_JSON").upper().strip()
    if src == "INTERNAL_JSON":
        return _normalize_company_internal_json(raw)
    elif src in ("CSV", "GENERIC_CSV"):
        return _normalize_company_csv(raw)
    elif src == "SEC":
        return _normalize_company_sec(raw)
    else:
        # Default fallback
        return _normalize_company_internal_json(raw)


def normalize_person(raw: dict, source: str) -> dict:
    """
    Standardize a raw person record from any supported source into the domain schema.
    """
    first = clean_string(raw.get("first_name") or raw.get("First Name") or raw.get("given_name"))
    last = clean_string(raw.get("last_name") or raw.get("Last Name") or raw.get("family_name"))
    full = clean_string(raw.get("full_name") or raw.get("Name"))
    if not full and (first or last):
        full = f"{first or ''} {last or ''}".strip() or None

    raw_title = clean_string(raw.get("title") or raw.get("Title") or raw.get("job_title"))
    norm_title = normalize_executive_title_heuristic(raw_title)

    return {
        "first_name": first,
        "last_name": last,
        "full_name": full,
        "email": clean_string(raw.get("email") or raw.get("Email")),
        "phone": clean_string(raw.get("phone") or raw.get("Phone")),
        "title": raw_title,
        "standardized_title": norm_title["standardized_title"],
        "seniority_level": norm_title["seniority_level"],
        "department": norm_title["department"],
        "company_name": clean_string(raw.get("company_name") or raw.get("Company")),
        "normalized_company_name": clean_legal_suffixes(raw.get("company_name") or raw.get("Company")),
        "linkedin_url": clean_string(raw.get("linkedin_url") or raw.get("LinkedIn")),
        "source": source.upper() if source else "INTERNAL_JSON",
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }


def supported_sources() -> List[str]:
    """Return all formally supported data sources."""
    return ["INTERNAL_JSON", "CSV", "PDL", "SEC", "APOLLO", "ZOOMINFO", "OSM"]


# ─────────────────────────────────────────────────────────────────────────────
# Executive Title & Seniority Classification (Agent 4)
# ─────────────────────────────────────────────────────────────────────────────

SENIORITY_PATTERNS = [
    (r"\b(chief\s+executive\s+officer|ceo)\b", "C_SUITE"),
    (r"\b(chief\s+technology\s+officer|cto)\b", "C_SUITE"),
    (r"\b(chief\s+operating\s+officer|coo)\b", "C_SUITE"),
    (r"\b(chief\s+financial\s+officer|cfo)\b", "C_SUITE"),
    (r"\b(chief\s+information\s+officer|cio)\b", "C_SUITE"),
    (r"\b(chief\s+security\s+officer|ciso)\b", "C_SUITE"),
    (r"\b(chief\s+marketing\s+officer|cmo)\b", "C_SUITE"),
    (r"\b(chief\s+revenue\s+officer|cro)\b", "C_SUITE"),
    (r"\b(chief\s+people\s+officer|cpo)\b", "C_SUITE"),
    (r"\b(co-founder|founder|founding\s+partner)\b", "FOUNDER"),
    (r"\b(owner|proprietor|co-owner|socio\s+fundador)\b", "OWNER"),
    (r"\b(executive\s+vice\s+president|evp)\b", "VP"),
    (r"\b(senior\s+vice\s+president|svp)\b", "VP"),
    (r"\b(vice\s+president|vp|avp)\b", "VP"),
    (r"\b(chief|c-suite|csuite)\b", "C_SUITE"),
    (r"(?<!vice\s)(?<!vice-)\bpresident\b", "C_SUITE"),
    (r"\b(managing\s+director|senior\s+director|director|head\s+of)\b", "DIRECTOR"),
    (r"\b(general\s+manager|senior\s+manager|manager|team\s+lead|lead|supervisor)\b", "MANAGER"),
    (r"\b(engineer|developer|analyst|specialist|associate|consultant|technician|intern)\b", "STAFF"),
]

DEPARTMENT_PATTERNS = [
    (r"\b(software|engineer|developer|architect|devops|sre|systems|data|cloud|infrastructure|tech|technology|ai|ml)\b", "ENGINEERING"),
    (r"\b(product|ux|ui|design|designer)\b", "PRODUCT"),
    (r"\b(sales|account\s+executive|bdr|sdr|revenue|commercial|business\s+development|partnerships)\b", "SALES"),
    (r"\b(marketing|growth|brand|seo|content|communications|pr|demand)\b", "MARKETING"),
    (r"\b(finance|financial|accounting|controller|treasurer|audit|tax|cfo)\b", "FINANCE"),
    (r"\b(hr|human\s+resources|people|talent|recruiting|recruiter|culture)\b", "HR"),
    (r"\b(legal|counsel|general\s+counsel|attorney|lawyer|compliance|regulatory)\b", "LEGAL"),
    (r"\b(operations|operating|coo|logistics|supply\s+chain|procurement|facilities)\b", "OPERATIONS"),
    (r"\b(support|customer\s+success|customer\s+service|client\s+services)\b", "CUSTOMER_SUCCESS"),
    (r"\b(ceo|coo|president|founder|owner|partner|executive)\b", "EXECUTIVE"),
]


def normalize_executive_title_heuristic(title: Optional[str]) -> Dict[str, Any]:
    """
    Deterministic rule-based title standardizer for seniority and department classification.
    """
    if not title or not str(title).strip():
        return {
            "raw_title": None,
            "standardized_title": None,
            "seniority_level": "STAFF",
            "department": "OTHER",
            "confidence": 0.50,
            "method": "deterministic_fallback",
        }

    raw = str(title).strip()
    low = raw.lower()

    # 1. Seniority matching
    seniority = "STAFF"
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, low):
            seniority = level
            break

    # 2. Department matching
    department = "OTHER"
    for pattern, dept in DEPARTMENT_PATTERNS:
        if re.search(pattern, low):
            department = dept
            break

    # Clean standardized title presentation
    clean_title = re.sub(r"\s+", " ", raw).strip()
    clean_title = clean_title.title() if clean_title.isupper() or clean_title.islower() else clean_title

    confidence = 0.90 if seniority != "STAFF" and department != "OTHER" else 0.70

    return {
        "raw_title": raw,
        "standardized_title": clean_title,
        "seniority_level": seniority,
        "department": department,
        "confidence": confidence,
        "method": "deterministic_fallback",
    }


TITLE_SYSTEM_PROMPT = """You are the Executive Talent & Organizational Taxonomy Specialist for OneExtraction.
Standardize the given executive job title into canonical seniority and department.

Allowed Seniority Levels:
- "C_SUITE": CEO, CTO, CFO, COO, CIO, CISO, CMO, CRO, President, Chief officers
- "FOUNDER": Founder, Co-Founder, Founding Partner
- "OWNER": Owner, Proprietor, Sole Owner
- "VP": Executive VP, Senior VP, Vice President, AVP
- "DIRECTOR": Managing Director, Senior Director, Director, Head of
- "MANAGER": General Manager, Senior Manager, Manager, Team Lead, Supervisor
- "STAFF": Individual contributors, Engineers, Analysts, Associates

Allowed Departments:
- "EXECUTIVE", "ENGINEERING", "PRODUCT", "SALES", "MARKETING", "FINANCE", "HR", "LEGAL", "OPERATIONS", "CUSTOMER_SUCCESS", "OTHER"

Output strictly valid JSON:
{
  "standardized_title": "Clean, formatted professional title",
  "seniority_level": "C_SUITE" | "FOUNDER" | "OWNER" | "VP" | "DIRECTOR" | "MANAGER" | "STAFF",
  "department": "DEPARTMENT_NAME",
  "confidence": 0.95
}
"""


async def normalize_executive_title_llm(
    title: Optional[str],
    company_name: Optional[str] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    Classifies job title using Ollama LLaMA 3.1:8B with instant deterministic fallback.
    """
    if not title or not str(title).strip():
        return normalize_executive_title_heuristic(title)

    raw = str(title).strip()

    try:
        from packages.infrastructure.ollama_client import ollama_client
        if ollama_client and ollama_client.is_available():
            prompt = f"Executive Title: \"{raw}\""
            if company_name:
                prompt += f" at Company: \"{company_name}\""

            res = await ollama_client.generate_structured(
                prompt=prompt,
                system=TITLE_SYSTEM_PROMPT,
                timeout=timeout,
            )
            if isinstance(res, dict) and "seniority_level" in res:
                seniority = str(res.get("seniority_level")).upper().strip()
                department = str(res.get("department")).upper().strip()
                valid_sen = {"C_SUITE", "FOUNDER", "OWNER", "VP", "DIRECTOR", "MANAGER", "STAFF"}
                valid_dept = {"EXECUTIVE", "ENGINEERING", "PRODUCT", "SALES", "MARKETING", "FINANCE", "HR", "LEGAL", "OPERATIONS", "CUSTOMER_SUCCESS", "OTHER"}

                if seniority in valid_sen:
                    return {
                        "raw_title": raw,
                        "standardized_title": str(res.get("standardized_title", raw)),
                        "seniority_level": seniority,
                        "department": department if department in valid_dept else "OTHER",
                        "confidence": float(res.get("confidence", 0.95)),
                        "method": "ollama_llama3.1:8b",
                    }
    except Exception:
        pass

    return normalize_executive_title_heuristic(raw)


def normalize_executive_title(
    title: Optional[str],
    sync: bool = True,
    company_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Synchronous entry point for executive title normalization.
    """
    return normalize_executive_title_heuristic(title)


async def normalize_executive_titles_batch(
    titles: List[str],
    concurrency: int = 5,
) -> List[Dict[str, Any]]:
    """
    Batch processes a collection of executive titles asynchronously.
    """
    if not titles:
        return []

    sem = asyncio.Semaphore(concurrency)

    async def _bound(t):
        async with sem:
            return await normalize_executive_title_llm(t)

    return await asyncio.gather(*[_bound(t) for t in titles])


# ─────────────────────────────────────────────────────────────────────────────
# Industry & NAICS Taxonomy Classification (Agent 5)
# ─────────────────────────────────────────────────────────────────────────────

INDUSTRY_TAXONOMY = [
    (r"\b(software|saas|app|cloud|cyber|artificial\s+intelligence|machine\s+learning|data\s+analytics|it\s+services)\b", "Computer Software", "5415", "Information Technology"),
    (r"\b(healthcare|health|hospital|clinic|medical|pharma|pharmaceutical|biotech|biotechnology|nursing)\b", "Healthcare", "6211", "Health Care"),
    (r"\b(bank|banking|finance|financial|investment|fintech|insurance|wealth|capital|private\s+equity)\b", "Banking and Finance", "5221", "Financials"),
    (r"\b(manufacturing|factory|industrial|machining|fabrication|assembly|metals|plastics|automotive)\b", "Industrial Manufacturing & Transformation", "3320", "Industrials"),
    (r"\b(defense|federal|contractor|aerospace|military|government\s+contract)\b", "Federal Contractor", "9281", "Industrials"),
    (r"\b(retail|ecommerce|e-commerce|consumer|apparel|fashion|store|goods|shop)\b", "Retail", "4481", "Consumer Discretionary"),
    (r"\b(energy|solar|oil|gas|renewable|petroleum|utilities|power|wind)\b", "Energy", "2211", "Energy"),
    (r"\b(education|university|college|school|academic|training|edtech)\b", "Education", "6113", "Consumer Discretionary"),
    (r"\b(real\s+estate|property|realty|leasing|commercial\s+property)\b", "Real Estate", "5312", "Real Estate"),
    (r"\b(telecom|telecommunications|wireless|broadband|networking|cellular)\b", "Telecommunications", "5173", "Communication Services"),
    (r"\b(construction|builder|building|architecture|civil\s+engineering)\b", "Construction", "2362", "Industrials"),
    (r"\b(nonprofit|non-profit|ngo|charity|association|foundation)\b", "Nonprofits and Associations", "8132", "Other"),
    (r"\b(consulting|advisory|legal\s+services|accounting\s+services|professional\s+services)\b", "Professional Services", "5411", "Professional, Scientific, and Technical Services"),
]


def classify_industry_heuristic(text: Optional[str]) -> Dict[str, Any]:
    """
    Deterministic rule-based industry classifier into standardized industry, NAICS, and sector.
    """
    if not text or not str(text).strip():
        return {
            "raw_input": None,
            "standardized_industry": "Other",
            "naics_code": "9999",
            "sector": "Other",
            "confidence": 0.50,
            "method": "deterministic_fallback",
        }

    raw = str(text).strip()
    low = raw.lower()

    for pattern, ind_name, naics, sector in INDUSTRY_TAXONOMY:
        if re.search(pattern, low):
            return {
                "raw_input": raw,
                "standardized_industry": ind_name,
                "naics_code": naics,
                "sector": sector,
                "confidence": 0.88,
                "method": "deterministic_fallback",
            }

    return {
        "raw_input": raw,
        "standardized_industry": raw.title() if len(raw) <= 50 else "Other",
        "naics_code": "9999",
        "sector": "Other",
        "confidence": 0.60,
        "method": "deterministic_fallback",
    }


INDUSTRY_SYSTEM_PROMPT = """You are the Industrial Taxonomy & NAICS Classification Specialist for OneExtraction.
Map the given business description or industry phrase into a standardized industry vertical, NAICS code, and sector.

Target Industries:
- "Computer Software", "Healthcare", "Banking and Finance", "Industrial Manufacturing & Transformation",
  "Federal Contractor", "Retail", "Energy", "Education", "Real Estate", "Telecommunications",
  "Construction", "Nonprofits and Associations", "Professional Services"

Output strictly valid JSON:
{
  "standardized_industry": "Exact Target Industry Name",
  "naics_code": "4-digit NAICS code or null",
  "sector": "Broad industry sector",
  "confidence": 0.95
}
"""


async def classify_industry_llm(
    raw_text: Optional[str],
    company_name: Optional[str] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """
    Classifies company business activity using Ollama LLaMA 3.1:8B with deterministic failover.
    """
    if not raw_text or not str(raw_text).strip():
        return classify_industry_heuristic(raw_text)

    raw = str(raw_text).strip()

    try:
        from packages.infrastructure.ollama_client import ollama_client
        if ollama_client and ollama_client.is_available():
            prompt = f"Business Activity / Description: \"{raw}\""
            if company_name:
                prompt += f" for Company: \"{company_name}\""

            res = await ollama_client.generate_structured(
                prompt=prompt,
                system=INDUSTRY_SYSTEM_PROMPT,
                timeout=timeout,
            )
            if isinstance(res, dict) and "standardized_industry" in res:
                return {
                    "raw_input": raw,
                    "standardized_industry": str(res.get("standardized_industry")),
                    "naics_code": str(res.get("naics_code")) if res.get("naics_code") else None,
                    "sector": str(res.get("sector", "Other")),
                    "confidence": float(res.get("confidence", 0.92)),
                    "method": "ollama_llama3.1:8b",
                }
    except Exception:
        pass

    return classify_industry_heuristic(raw)


def classify_industry(
    text: Optional[str],
    sync: bool = True,
    company_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Synchronous entry point for industry classification.
    """
    return classify_industry_heuristic(text)


async def classify_industries_batch(
    texts: List[str],
    concurrency: int = 5,
) -> List[Dict[str, Any]]:
    """
    Batch processes a collection of industry descriptions asynchronously.
    """
    if not texts:
        return []

    sem = asyncio.Semaphore(concurrency)

    async def _bound(t):
        async with sem:
            return await classify_industry_llm(t)

    return await asyncio.gather(*[_bound(t) for t in texts])

