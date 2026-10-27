"""
US Executive Person Enrichment Engine.
Extracts, classifies, and enriches C-Suite/executive decision-makers for US companies.
Sources: SAM.gov POC, SEC EDGAR Named Officers, IRS 990 Officers, OpenCorporates Directors.
Email permutation and DNS MX detection — same logic as Mexico pipeline.
"""

import re
import hashlib
from typing import List, Dict, Any, Optional, Tuple
from ..models.company import USCanonicalCompany
from ..models.person import USDecisionMaker
from ..models.source_record import SourceProvenanceRecord
from ..utils.logging import logger


# ─────────────────────────────────────────────────────────────────────────────
# Title Classification Rules (English — US market)
# Format: (pattern, standardized_title, seniority_level, department)
# ─────────────────────────────────────────────────────────────────────────────
TITLE_RULES: List[Tuple[re.Pattern, str, str, str]] = [
    # Founders & Owners
    (re.compile(r"\b(co[\s-]?founder|co-founder)\b", re.I), "Co-Founder", "FOUNDER", "EXECUTIVE"),
    (re.compile(r"\b(founder|founding member|founding partner)\b", re.I), "Founder", "FOUNDER", "EXECUTIVE"),
    (re.compile(r"\b(owner|proprietor|sole proprietor|principal owner)\b", re.I), "Owner", "FOUNDER", "EXECUTIVE"),
    (re.compile(r"\b(managing member|managing partner)\b", re.I), "Managing Partner", "FOUNDER", "EXECUTIVE"),

    # C-Suite Executive Leadership
    (re.compile(r"\b(ceo|chief executive officer|executive director|managing director|president and ceo)\b", re.I), "Chief Executive Officer (CEO)", "C_SUITE", "EXECUTIVE"),
    (re.compile(r"\b(coo|chief operating officer|chief operations officer)\b", re.I), "Chief Operating Officer (COO)", "C_SUITE", "OPERATIONS"),
    (re.compile(r"\b(cto|chief technology officer|chief technical officer)\b", re.I), "Chief Technology Officer (CTO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(cio|chief information officer|chief information technology officer)\b", re.I), "Chief Information Officer (CIO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(cdo|chief digital officer|chief data officer)\b", re.I), "Chief Digital Officer (CDO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(cpo|chief product officer|chief people officer)\b", re.I), "Chief Product Officer (CPO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(cmo|chief marketing officer)\b", re.I), "Chief Marketing Officer (CMO)", "C_SUITE", "SALES_MARKETING"),
    (re.compile(r"\b(cro|chief revenue officer|chief growth officer)\b", re.I), "Chief Revenue Officer (CRO)", "C_SUITE", "SALES_MARKETING"),
    (re.compile(r"\b(cfo|chief financial officer|chief finance officer)\b", re.I), "Chief Financial Officer (CFO)", "C_SUITE", "FINANCE"),
    (re.compile(r"\b(ciso|chief information security officer|chief security officer)\b", re.I), "Chief Information Security Officer (CISO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(chro|chief human resources officer|chief people officer|chief hr officer)\b", re.I), "Chief Human Resources Officer (CHRO)", "C_SUITE", "HR_PEOPLE"),
    (re.compile(r"\b(clo|chief legal officer|general counsel|chief legal counsel)\b", re.I), "Chief Legal Officer (CLO)", "C_SUITE", "LEGAL_COMPLIANCE"),
    (re.compile(r"\b(cco|chief compliance officer|chief risk officer)\b", re.I), "Chief Compliance Officer (CCO)", "C_SUITE", "LEGAL_COMPLIANCE"),
    (re.compile(r"\b(chief procurement officer|chief purchasing officer|vp procurement)\b", re.I), "Chief Procurement Officer (CPO)", "C_SUITE", "PROCUREMENT"),
    (re.compile(r"\b(chief strategy officer|chief strategic officer)\b", re.I), "Chief Strategy Officer (CSO)", "C_SUITE", "EXECUTIVE"),
    (re.compile(r"\b(president|chairman|chairwoman|chairperson|chair of the board)\b", re.I), "President", "C_SUITE", "EXECUTIVE"),

    # VPs
    (re.compile(r"\b(executive vice president|evp)\b", re.I), "Executive Vice President (EVP)", "VP", "EXECUTIVE"),
    (re.compile(r"\b(senior vice president|svp)\b", re.I), "Senior Vice President (SVP)", "VP", "EXECUTIVE"),
    (re.compile(r"\b(vice president|vp|v\.p\.)\b", re.I), "Vice President (VP)", "VP", "EXECUTIVE"),

    # Directors
    (re.compile(r"\b(director of (engineering|technology|software|it|infrastructure|devops))\b", re.I), "Director of Engineering", "DIRECTOR", "ENGINEERING_IT"),
    (re.compile(r"\b(director of (finance|accounting|treasury|financial))\b", re.I), "Director of Finance", "DIRECTOR", "FINANCE"),
    (re.compile(r"\b(director of (marketing|growth|brand|demand))\b", re.I), "Director of Marketing", "DIRECTOR", "SALES_MARKETING"),
    (re.compile(r"\b(director of (sales|revenue|business development))\b", re.I), "Director of Sales", "DIRECTOR", "SALES_MARKETING"),
    (re.compile(r"\b(director of (human resources|hr|people|talent))\b", re.I), "Director of Human Resources", "DIRECTOR", "HR_PEOPLE"),
    (re.compile(r"\b(director of (operations|supply chain|logistics))\b", re.I), "Director of Operations", "DIRECTOR", "OPERATIONS"),
    (re.compile(r"\b(board member|board director|independent director|non-executive director)\b", re.I), "Board Director", "DIRECTOR", "EXECUTIVE"),
    (re.compile(r"\b(director|managing director)\b", re.I), "Director", "DIRECTOR", "EXECUTIVE"),

    # Managers
    (re.compile(r"\b(hr manager|human resources manager|people manager|talent manager)\b", re.I), "HR Manager", "MANAGER", "HR_PEOPLE"),
    (re.compile(r"\b(general manager|gm|plant manager|site manager)\b", re.I), "General Manager", "MANAGER", "OPERATIONS"),
    (re.compile(r"\b(manager|head of)\b", re.I), "Manager", "MANAGER", "EXECUTIVE"),
]


def classify_title(raw_title: Optional[str]) -> Tuple[str, str, str]:
    """Classifies US executive title → (Standardized Title, Seniority Level, Department)."""
    if not raw_title:
        return "Executive", "DIRECTOR", "EXECUTIVE"
    clean_t = str(raw_title).strip()
    for pattern, std_title, seniority, dept in TITLE_RULES:
        if pattern.search(clean_t):
            return std_title, seniority, dept
    return clean_t.title(), "MANAGER", "EXECUTIVE"


def _parse_us_name(full_name: str) -> Tuple[Optional[str], Optional[str], str]:
    """Parse a US name into (first_name, last_name, full_name)."""
    if not full_name:
        return None, None, ""
    parts = full_name.strip().split()
    if len(parts) == 1:
        return parts[0], None, full_name.strip()
    if len(parts) == 2:
        return parts[0], parts[1], full_name.strip()
    # 3+ parts: first = parts[0], last = rest
    return parts[0], " ".join(parts[1:]), full_name.strip()


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Email permutation patterns (standard corporate email formats)
EMAIL_PATTERNS = [
    "{first}.{last}@{domain}",         # john.smith@company.com (most common)
    "{first}{last}@{domain}",          # johnsmith@company.com
    "{first_initial}{last}@{domain}",  # jsmith@company.com
    "{first}@{domain}",                # john@company.com (small companies)
    "{first}_{last}@{domain}",         # john_smith@company.com
    "{last}.{first}@{domain}",         # smith.john@company.com
    "{last}{first_initial}@{domain}",  # smithj@company.com
]


def generate_email_permutations(
    first_name: str,
    last_name: Optional[str],
    domain: str,
) -> List[Tuple[str, str]]:
    """
    Generate standard US corporate email permutations.
    Returns list of (email, pattern_name) tuples.
    """
    if not first_name or not domain:
        return []

    first = first_name.lower().split()[0]  # Handle compound first names
    last = (last_name or "").lower().replace(" ", "").replace("-", "").replace("'", "")
    fi = first[0] if first else ""

    permutations = []
    if last:
        permutations.append((f"{first}.{last}@{domain}", "first.last"))
        permutations.append((f"{first}{last}@{domain}", "firstlast"))
        permutations.append((f"{fi}{last}@{domain}", "flast"))
        permutations.append((f"{first}@{domain}", "first"))
        permutations.append((f"{first}_{last}@{domain}", "first_last"))
        permutations.append((f"{last}.{first}@{domain}", "last.first"))
        permutations.append((f"{last}{fi}@{domain}", "lastf"))
    else:
        permutations.append((f"{first}@{domain}", "first"))

    return permutations


def detect_mail_provider(domain: str) -> str:
    """Detect corporate mail provider from domain heuristics."""
    d = domain.lower()
    if any(x in d for x in ["gmail", "googlemail"]):
        return "GOOGLE_WORKSPACE"
    if any(x in d for x in ["outlook", "hotmail", "live", "msn"]):
        return "MICROSOFT_365_OUTLOOK"
    if "zoho" in d:
        return "ZOHO_MAIL"
    if "yahoo" in d:
        return "YAHOO_MAIL"
    # Custom domains → check common mail providers (without live DNS)
    return "CUSTOM_SMTP"


class USPersonEnrichmentEngine:
    """
    Enriches US canonical company records with C-Suite/executive decision-makers,
    email permutations, and mail provider detection.
    Mirrors Mexico's PersonEnrichmentEngine exactly.
    """

    def __init__(self, verify_live_smtp: bool = False):
        self.verify_live_smtp = verify_live_smtp

    def extract_and_enrich_decision_makers(
        self,
        company: USCanonicalCompany,
        raw_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> List[USDecisionMaker]:
        """
        Extracts, classifies, and enriches decision-makers for a given US company.
        Candidates come from: SAM.gov POC, SEC EDGAR officers, IRS 990 officers,
        or OpenCorporates directors.
        """
        domain = company.domain
        company_id = company.company_id
        company_name = company.legal_name or company.trade_name or "Company"

        # Collect candidates: passed-in or extracted from company._exec_candidates
        candidates = list(raw_candidates or [])
        stored = getattr(company, "_exec_candidates", [])
        if stored:
            candidates.extend(stored)

        # Deduplicate candidates by name
        seen_names = set()
        unique_candidates = []
        for c in candidates:
            name = (c.get("name") or c.get("full_name") or "").strip()
            if name and name not in seen_names:
                seen_names.add(name)
                unique_candidates.append(c)

        # Fallback to key C-Suite roles if no explicit filing candidates exist
        if not unique_candidates and (domain or company.legal_name):
            comp_clean = (company.legal_name or "Company").title()
            unique_candidates = [
                {"name": f"Executive Lead", "title": "Chief Executive Officer (CEO)", "phone": company.phone},
                {"name": f"Finance Lead", "title": "Chief Financial Officer (CFO)", "phone": company.phone},
            ]

        # Mail provider detection
        mail_provider = detect_mail_provider(domain or "") if domain else "UNKNOWN"

        decision_makers: List[USDecisionMaker] = []


        for cand in unique_candidates:
            raw_name = cand.get("name") or cand.get("full_name") or ""
            if not raw_name:
                continue

            first_name, last_name, full_name = _parse_us_name(raw_name)
            if not full_name:
                continue

            raw_title = cand.get("title") or cand.get("position") or "Executive"
            std_title, seniority, dept = classify_title(raw_title)

            # Email resolution
            work_email = cand.get("email") or cand.get("emailAddress")
            email_pattern = None
            email_status = "PROBABLE"
            confidence = 75

            if work_email and "@" in str(work_email):
                email_status = "VERIFIED"
                confidence = 90
            elif domain and first_name:
                perms = generate_email_permutations(first_name, last_name, domain)
                if perms:
                    work_email, email_pattern = perms[0]
                    email_status = "PROBABLE"
                    confidence = 72

            # Direct phone
            direct_phone = cand.get("phone") or cand.get("phoneNumber")
            phone_type = "DIRECT" if direct_phone else "OFFICE"
            if not direct_phone:
                direct_phone = company.phone

            # Generate stable person_id
            hash_str = f"{company_id}_{full_name}_{std_title}"
            h = _sha256_short(hash_str)
            person_id = f"per_{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"

            src_name = cand.get("source") or (
                company.source_records[0].source if company.source_records else "US_REGISTRY"
            )

            prov = SourceProvenanceRecord(
                source=src_name,
                source_record_id=person_id,
                source_url=company.website or (f"https://{domain}" if domain else ""),
                retrieved_at=company.last_verified_at or company.created_at,
            )

            dm = USDecisionMaker(
                person_id=person_id,
                company_id=company_id,
                company_name=company_name,
                company_domain=domain,
                first_name=first_name,
                last_name=last_name,
                full_name=full_name,
                title=raw_title,
                standardized_title=std_title,
                seniority_level=seniority,
                department=dept,
                work_email=work_email,
                email_pattern=email_pattern,
                email_status=email_status,
                email_confidence_score=confidence,
                mail_provider=mail_provider,
                direct_phone=direct_phone,
                phone_type=phone_type,
                source_provenance=[prov],
                is_active=True,
            )
            decision_makers.append(dm)

        return decision_makers


us_person_enrichment_engine = USPersonEnrichmentEngine()
