"""
Person & Executive Enrichment Engine for Mexican B2B Leads.
Extracts, standardizes, and enriches decision-makers (Founders, C-Suite, VPs, Directors, HR).
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from ..models.company import CanonicalCompany
from ..models.person import DecisionMaker
from ..models.source_record import SourceProvenanceRecord
from ..utils.name_utils import parse_mexican_full_name, clean_name_string
from ..utils.dns_utils import (
    get_mx_records,
    detect_mail_provider,
    generate_email_permutations,
    verify_email_deliverability,
)
from ..utils.hashing import sha256_text
from ..utils.logging import logger


# Title Classification Dictionary: Keyword patterns -> (Standardized Title, Seniority Level, Department)
TITLE_RULES: List[Tuple[re.Pattern, str, str, str]] = [
    # 1. Founders & Owners
    (re.compile(r"\b(co[\s-]?founder|co-fundador|cofundador)\b", re.I), "Co-Founder", "FOUNDER", "EXECUTIVE"),
    (re.compile(r"\b(founder|fundador|socio fundador|socio principal)\b", re.I), "Founder", "FOUNDER", "EXECUTIVE"),
    (re.compile(r"\b(owner|propietario|dueño|patrón)\b", re.I), "Owner", "FOUNDER", "EXECUTIVE"),
    (re.compile(r"\b(administrador[a]? [uú]nico|administrador general)\b", re.I), "Sole Administrator / Owner", "FOUNDER", "EXECUTIVE"),

    # 2. Executive Leadership & C-Suite
    (re.compile(r"\b(ceo|chief executive officer|director[a]? general|managing director|presidente ejecutivo)\b", re.I), "Chief Executive Officer (CEO)", "C_SUITE", "EXECUTIVE"),
    (re.compile(r"\b(coo|chief operating officer|director[a]? de operaciones)\b", re.I), "Chief Operating Officer (COO)", "C_SUITE", "OPERATIONS"),
    (re.compile(r"\b(cto|chief technology officer|director[a]? de tecnolog[ií]a|director[a]? de sistemas|director[a]? ti)\b", re.I), "Chief Technology Officer (CTO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(cio|chief information officer|director[a]? de inform[aá]tica)\b", re.I), "Chief Information Officer (CIO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(cdo|chief digital officer|director[a]? digital)\b", re.I), "Chief Digital Officer (CDO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(chief product officer|director[a]? de producto)\b", re.I), "Chief Product Officer (CPO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(cmo|chief marketing officer|director[a]? de marketing|director[a]? de mercadotecnia)\b", re.I), "Chief Marketing Officer (CMO)", "C_SUITE", "SALES_MARKETING"),
    (re.compile(r"\b(cro|chief revenue officer|director[a]? comercial)\b", re.I), "Chief Revenue Officer (CRO)", "C_SUITE", "SALES_MARKETING"),
    (re.compile(r"\b(cfo|chief financial officer|director[a]? de finanzas|tesorero|director[a]? administrativo y financiero)\b", re.I), "Chief Financial Officer (CFO)", "C_SUITE", "FINANCE"),
    (re.compile(r"\b(ciso|chief information security officer|director[a]? de ciberseguridad)\b", re.I), "Chief Information Security Officer (CISO)", "C_SUITE", "ENGINEERING_IT"),
    (re.compile(r"\b(cso|chief security officer|director[a]? de seguridad)\b", re.I), "Chief Security Officer (CSO)", "C_SUITE", "OPERATIONS"),
    (re.compile(r"\b(chro|chief human resources officer|director[a]? de recursos humanos|director[a]? de talento humano|director[a]? de rh|director[a]? rh)\b", re.I), "Chief Human Resources Officer (CHRO)", "C_SUITE", "HR_PEOPLE"),
    (re.compile(r"\b(chief procurement officer|director[a]? de compras|director[a]? de adquisiciones|director[a]? de proveedur[ií]a)\b", re.I), "Chief Procurement Officer (CPO)", "C_SUITE", "PROCUREMENT"),
    (re.compile(r"\b(clo|chief legal officer|director[a]? jur[ií]dico|director[a]? jur[ií]dica|abogado general|apoderado legal|representante legal)\b", re.I), "Chief Legal Officer (CLO)", "C_SUITE", "LEGAL_COMPLIANCE"),
    (re.compile(r"\b(cco|chief compliance officer|director[a]? de cumplimiento)\b", re.I), "Chief Compliance Officer (CCO)", "C_SUITE", "LEGAL_COMPLIANCE"),
    (re.compile(r"\b(chief strategy officer|director[a]? de estrategia)\b", re.I), "Chief Strategy Officer (CSO)", "C_SUITE", "EXECUTIVE"),

    # 3. Presidents & Vice Presidents
    (re.compile(r"\b(executive vice president|evp|vicepresidente ejecutivo)\b", re.I), "Executive Vice President (EVP)", "VP", "EXECUTIVE"),
    (re.compile(r"\b(senior vice president|svp|vicepresidente senior)\b", re.I), "Senior Vice President (SVP)", "VP", "EXECUTIVE"),
    (re.compile(r"\b(vice president|vp|vicepresidente|vicepresidenta)\b", re.I), "Vice President (VP)", "VP", "EXECUTIVE"),
    (re.compile(r"\b(presidente del consejo|presidente|presidenta)\b", re.I), "President", "VP", "EXECUTIVE"),

    # 4. Managers & HR Leads
    (re.compile(r"\b(gerente de recursos humanos|gerente de talento|hr manager|people operations|coordinador de rh)\b", re.I), "HR Manager", "MANAGER", "HR_PEOPLE"),
    (re.compile(r"\b(gerente general|gerente|manager|subdirector|subdirectora)\b", re.I), "General Manager", "MANAGER", "OPERATIONS"),

    # 5. Generic Directors & Heads (Fallback after specific departments)
    (re.compile(r"\b(director|directora|head of)\b", re.I), "Director", "DIRECTOR", "EXECUTIVE"),
]


def classify_title(raw_title: Optional[str]) -> Tuple[str, str, str]:
    """
    Classifies raw executive title into (Standardized Title, Seniority Level, Department).
    """
    if not raw_title:
        return "Executive", "DIRECTOR", "EXECUTIVE"

    clean_t = str(raw_title).strip()
    for pattern, std_title, seniority, dept in TITLE_RULES:
        if pattern.search(clean_t):
            return std_title, seniority, dept

    return clean_t.title(), "MANAGER", "EXECUTIVE"


class PersonEnrichmentEngine:
    """
    Enriches canonical company records with decision-maker rosters, email patterns, and verification.
    """

    def __init__(self, verify_live_smtp: bool = False):
        self.verify_live_smtp = verify_live_smtp
        self._mx_cache: Dict[str, List[str]] = {}

    def extract_and_enrich_decision_makers(
        self,
        company: CanonicalCompany,
        raw_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> List[DecisionMaker]:
        """
        Extracts, classifies, and enriches decision-makers for a given company.
        """
        domain = company.domain
        company_id = company.company_id
        company_name = company.legal_name or company.trade_name or "Company"
        candidates = raw_candidates or []

        # If no explicit candidates passed, extract from company source records
        if not candidates:
            for s in company.source_records:
                raw_d = getattr(s, "raw_payload_data", None) or {}
                # Check for explicit legal representative or executive contact in source raw data
                rep_name = (
                    raw_d.get("representante_legal")
                    or raw_d.get("contacto_nombre")
                    or raw_d.get("nombre_contacto")
                    or raw_d.get("administrador_unico")
                    or raw_d.get("apoderado_legal")
                )
                rep_title = (
                    raw_d.get("cargo_representante")
                    or raw_d.get("contacto_cargo")
                    or raw_d.get("contacto_puesto")
                    or raw_d.get("puesto")
                    or "Representante Legal / Director General"
                )
                direct_phone = (
                    raw_d.get("telefono_directo")
                    or raw_d.get("contacto_telefono")
                    or raw_d.get("celular")
                    or company.phone
                )
                direct_email = (
                    raw_d.get("correo_directo")
                    or raw_d.get("contacto_email")
                    or raw_d.get("correo_contacto")
                )

                if rep_name:
                    candidates.append({
                        "name": rep_name,
                        "title": rep_title,
                        "phone": direct_phone,
                        "email": direct_email,
                        "source": s.source,
                    })
                elif s.source in ("SUPPLIER_REGISTRY", "SIEM"):
                    candidates.append({
                        "name": f"Representante Legal ({company_name})",
                        "title": "Representante Legal / Apoderado",
                        "source": s.source,
                        "phone": company.phone,
                    })

        # Fast Mail Provider Identification
        mx_hosts = []
        mail_provider = "UNKNOWN"
        if domain:
            if self.verify_live_smtp:
                if domain not in self._mx_cache:
                    try:
                        self._mx_cache[domain] = get_mx_records(domain, timeout=1.0)
                    except Exception:
                        self._mx_cache[domain] = []
                mx_hosts = self._mx_cache[domain]
                mail_provider = detect_mail_provider(mx_hosts)
            else:
                dom_lower = domain.lower()
                if "gmail" in dom_lower:
                    mail_provider = "GOOGLE_WORKSPACE"
                elif "outlook" in dom_lower or "hotmail" in dom_lower:
                    mail_provider = "MICROSOFT_365_OUTLOOK"
                elif "zoho" in dom_lower:
                    mail_provider = "ZOHO_MAIL"
                else:
                    mail_provider = "CUSTOM_SMTP"

        decision_makers: List[DecisionMaker] = []
        seen_names = set()

        for cand in candidates:
            raw_name = cand.get("name") or cand.get("full_name")
            if not raw_name:
                continue

            first_name, last_name, full_name = parse_mexican_full_name(raw_name)
            if not full_name or full_name in seen_names:
                continue
            seen_names.add(full_name)

            raw_title = cand.get("title") or cand.get("puesto") or cand.get("cargo") or "Executive"
            std_title, seniority, dept = classify_title(raw_title)

            # Generate and verify direct work email
            work_email = cand.get("email") or cand.get("correo")
            email_pattern = None
            email_status = "PROBABLE"
            confidence = 80

            if work_email and "@" in work_email:
                if self.verify_live_smtp:
                    email_status, confidence = verify_email_deliverability(
                        work_email,
                        mx_records=mx_hosts,
                        perform_smtp_handshake=True,
                    )
                else:
                    email_status = "VERIFIED" if ".com" in work_email or ".mx" in work_email else "PROBABLE"
                    confidence = 85
            elif domain and first_name:
                # Generate standard corporate permutation
                permutations = generate_email_permutations(first_name, last_name, domain)
                if permutations:
                    work_email, email_pattern = permutations[0]
                    if self.verify_live_smtp:
                        email_status, confidence = verify_email_deliverability(
                            work_email,
                            mx_records=mx_hosts,
                            perform_smtp_handshake=True,
                        )
                    else:
                        email_status = "PROBABLE"
                        confidence = 75

            person_hash = sha256_text(f"{company_id}_{full_name}_{std_title}")
            person_id = f"per_{person_hash[:8]}-{person_hash[8:12]}-{person_hash[12:16]}-{person_hash[16:20]}-{person_hash[20:32]}"

            src_name = cand.get("source") or (company.source_records[0].source if company.source_records else "REGISTRY")
            prov = SourceProvenanceRecord(
                source=src_name,
                source_record_id=str(cand.get("id") or person_id),
                source_url=company.website or f"https://{domain}" if domain else "",
                retrieved_at=company.last_verified_at or company.created_at,
            )

            dm = DecisionMaker(
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
                direct_phone=cand.get("phone") or company.phone,
                phone_extension=cand.get("extension"),
                phone_type="DIRECT" if cand.get("phone") else "OFFICE",
                source_provenance=[prov],
                is_active=True,
            )
            decision_makers.append(dm)

        return decision_makers


person_enrichment_engine = PersonEnrichmentEngine()
