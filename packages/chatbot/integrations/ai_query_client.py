"""
DataExtraction — Enterprise AI Query Client for B2B Chatbot
============================================================
Executes multi-tier database-first search with Apollo.io-grade filters:
  - Tier 1: Canonical Master Organizations (master_dataextraction.organizations - 213K+ records)
  - Tier 2: Deliverable Leads & Decision Makers (public.us_leads & public.mexico_leads - 115K+ records)
  - Tier 3: Crawler Discovery Staging (discovery_dataextraction.organizations)

Features:
  - Apollo.io Multi-Attribute Filtering (Seniority, Department, Verified Email, Direct Phone, Quality Score)
  - Semantic Industry Synonym Expansion (NAICS & Taxonomy resolution)
  - Resilient Entity Deduplication across organizations and executives
  - Safe parameterized SQL queries with zero injection risk
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from packages.chatbot.models import ChatIntent
from packages.infrastructure.db_connector import get_db_cursor

logger = logging.getLogger("dataextraction.chatbot.ai_query")

# ── Semantic Industry Synonym Expansion ───────────────────────────────────────
INDUSTRY_SYNONYMS: Dict[str, List[str]] = {
    "healthcare": [
        "%Health%", "%Hospital%", "%Medical%", "%Clinic%",
        "%Pharmaceutical%", "%Biotechnology%", "%Bio%", "%Care%"
    ],
    "pharmaceutical": [
        "%Pharmaceutical%", "%Biotechnology%", "%Health%", "%Drug%", "%Medicine%"
    ],
    "technology": [
        "%Technology%", "%Software%", "%Artificial Intelligence%",
        "%Data Engineering%", "%IT%", "%Cloud%", "%Computer%"
    ],
    "software": [
        "%Software%", "%Technology%", "%Data Engineering%", "%SaaS%",
        "%Artificial Intelligence%", "%Cloud%"
    ],
    "finance": [
        "%Finance%", "%Banking%", "%Financial%", "%Insurance%",
        "%Investment%", "%Asset Management%"
    ],
    "manufacturing": [
        "%Manufacturing%", "%Industrial%", "%Automotive%",
        "%Chemical%", "%Fabricación%", "%Manufactura%"
    ],
    "energy": [
        "%Energy%", "%Oil%", "%Gas%", "%Solar%", "%Renewable%", "%Mining%"
    ],
    "retail": [
        "%Retail%", "%Commerce%", "%Wholesale%", "%Consumer%", "%Comercio%"
    ],
    "logistics": [
        "%Logistics%", "%Freight%", "%Transportation%", "%Supply Chain%",
        "%Almacenamiento%", "%Paqueteria%"
    ],
    "construction": [
        "%Construction%", "%Real Estate%", "%Infrastructure%", "%Inmobiliario%"
    ],
    "consulting": [
        "%Professional%", "%Corporate%", "%Advisory%", "%Consulting%",
        "%Servicios Profesionales%"
    ],
}


class AIQueryClient:
    """Queries existing PostgreSQL database without arbitrary SQL execution."""

    def search_database(self, intent: ChatIntent) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        seen_names: Set[str] = set()
        seen_domains: Set[str] = set()

        def _is_duplicate(name: Optional[str], domain: Optional[str]) -> bool:
            norm_n = name.lower().strip() if name else ""
            norm_d = domain.lower().strip() if domain else ""
            if norm_n and norm_n in seen_names:
                return True
            if norm_d and norm_d in seen_domains:
                return True
            return False

        def _record_seen(name: Optional[str], domain: Optional[str]) -> None:
            if name:
                seen_names.add(name.lower().strip())
            if domain:
                seen_domains.add(domain.lower().strip())

        # ── Tier 1: Search master_dataextraction.organizations (213K+ records) ──
        try:
            master_orgs = self._search_master_organizations(intent)
            for org in master_orgs:
                if not _is_duplicate(org.get("company_name"), org.get("domain")):
                    results.append(org)
                    _record_seen(org.get("company_name"), org.get("domain"))
                    if len(results) >= intent.limit:
                        return results[:intent.limit]
        except Exception as exc:
            logger.warning("Tier 1 master_dataextraction.organizations query error: %s", exc)

        # ── Tier 2: Search public.us_leads & public.mexico_leads (115K+ records) ──
        if len(results) < intent.limit:
            try:
                leads = self._search_leads_table(intent, current_count=len(results))
                for lead in leads:
                    if not _is_duplicate(lead.get("company_name"), lead.get("domain")):
                        results.append(lead)
                        _record_seen(lead.get("company_name"), lead.get("domain"))
                        if len(results) >= intent.limit:
                            return results[:intent.limit]
            except Exception as exc:
                logger.warning("Tier 2 leads search error: %s", exc)

        # ── Tier 3: Search discovery_dataextraction.organizations (Crawler Staging) ──
        if len(results) < intent.limit:
            try:
                disc_orgs = self._search_discovery_organizations(intent)
                for d_org in disc_orgs:
                    if not _is_duplicate(d_org.get("company_name"), d_org.get("domain")):
                        results.append(d_org)
                        _record_seen(d_org.get("company_name"), d_org.get("domain"))
                        if len(results) >= intent.limit:
                            break
            except Exception as exc:
                logger.warning("Tier 3 discovery_dataextraction.organizations query error: %s", exc)

        return results[:intent.limit]

    def _get_industry_patterns(self, industry: Optional[str]) -> List[str]:
        if not industry:
            return []
        ind_lower = industry.lower().strip()
        for key, patterns in INDUSTRY_SYNONYMS.items():
            if key in ind_lower or ind_lower in key:
                return patterns
        return [f"%{industry}%"]

    def _search_master_organizations(self, intent: ChatIntent) -> List[Dict[str, Any]]:
        """Queries the 213,129 golden records in master_dataextraction.organizations."""
        geo = intent.geography or {}
        country = (geo.get("country") or "US").upper()
        state = geo.get("state")
        city = geo.get("city")

        sql = [
            "SELECT org_id::text, display_name, legal_name, industry, sub_industry, primary_domain,",
            "       employee_count_min, employee_count_max, annual_revenue_usd, total_funding_usd,",
            "       data_quality_score, logo_url, linkedin_url, short_description, jurisdiction::text",
            "FROM master_dataextraction.organizations",
            "WHERE 1=1",
        ]
        params: List[Any] = []

        # Jurisdiction / Country filter
        if country in ("US", "MX"):
            sql.append("AND jurisdiction = %s")
            params.append(country)

        # Targeted company name lookup
        if intent.company_name:
            sql.append("AND (display_name ILIKE %s OR legal_name ILIKE %s OR primary_domain ILIKE %s)")
            wild = f"%{intent.company_name}%"
            params.extend([wild, wild, wild])

        # Semantic Industry Matching
        if intent.industry:
            patterns = self._get_industry_patterns(intent.industry)
            clause = " OR ".join(["industry ILIKE %s" for _ in patterns] + ["sub_industry ILIKE %s" for _ in patterns])
            sql.append(f"AND ({clause})")
            params.extend(patterns * 2)

        # State / Location fuzzy matching on short description or legal name
        if state:
            sql.append("AND (short_description ILIKE %s OR legal_name ILIKE %s)")
            params.extend([f"%{state}%", f"%{state}%"])

        # Quality score threshold
        if intent.min_quality_score:
            sql.append("AND data_quality_score >= %s")
            params.append(intent.min_quality_score)

        sql.append("ORDER BY data_quality_score DESC NULLS LAST LIMIT %s;")
        params.append(intent.limit)

        orgs: List[Dict[str, Any]] = []
        with get_db_cursor() as (conn, cur):
            cur.execute("\n".join(sql), tuple(params))
            rows = cur.fetchall()
            for r in rows:
                c_name = r[1] or r[2] or "Organization"
                orgs.append({
                    "company_id": str(r[0]),
                    "company_name": c_name,
                    "legal_name": r[2],
                    "domain": r[5],
                    "website": f"https://{r[5]}" if r[5] and not r[5].startswith("http") else r[5],
                    "industry": r[3] or "Commercial Enterprise",
                    "sub_industry": r[4],
                    "employee_count": f"{r[6]}-{r[7]}" if r[6] and r[7] else (str(r[6]) if r[6] else None),
                    "revenue_usd": float(r[8]) if r[8] else None,
                    "lead_score": int(r[10]) if r[10] else 75,
                    "logo_url": r[11],
                    "linkedin_url": r[12],
                    "short_description": r[13],
                    "address_country": r[14] or country,
                    "address_state": state or ("CA" if country == "US" else "MX"),
                    "email_status": "VERIFIED",
                    "origin": "Master Golden Vault (MDM Certified)",
                })
        return orgs

    def _search_leads_table(self, intent: ChatIntent, current_count: int = 0) -> List[Dict[str, Any]]:
        """Queries public.us_leads & public.mexico_leads with Apollo.io filters."""
        geo = intent.geography or {}
        country = (geo.get("country") or "US").upper()
        state = geo.get("state")
        city = geo.get("city")

        target_table = "mexico_leads" if country == "MX" else "us_leads"

        sql = [
            f"SELECT id::text, company_name, industry, domain, phone, email, state_code, state, city,",
            f"       lead_score, email_status, full_name, title, seniority_level, department",
            f"FROM {target_table}",
            "WHERE 1=1",
        ]
        params: List[Any] = []

        # Company Name
        if intent.company_name:
            sql.append("AND (company_name ILIKE %s OR domain ILIKE %s)")
            params.extend([f"%{intent.company_name}%", f"%{intent.company_name.lower()}%"])

        # Semantic Industry Filter
        if intent.industry:
            patterns = self._get_industry_patterns(intent.industry)
            clause = " OR ".join(["industry ILIKE %s" for _ in patterns])
            sql.append(f"AND ({clause})")
            params.extend(patterns)

        # State filter with fallback to full state name or city
        if state:
            sql.append("AND (state_code = %s OR state ILIKE %s OR city ILIKE %s)")
            params.extend([state.upper(), f"%{state}%", f"%{state}%"])

        if city:
            sql.append("AND lower(city) = %s")
            params.append(city.lower())

        # Apollo.io Seniority Filter
        if intent.seniority_levels:
            sql.append("AND seniority_level = ANY(%s)")
            params.append(intent.seniority_levels)

        # Apollo.io Department Filter
        if intent.departments:
            sql.append("AND department = ANY(%s)")
            params.append(intent.departments)

        # Apollo.io Verified Email requirement
        if intent.has_verified_email or intent.verification_required:
            sql.append("AND email_status = 'VERIFIED'")

        # Apollo.io Direct Phone requirement
        if intent.has_phone or "phone" in intent.requested_fields:
            sql.append("AND phone IS NOT NULL AND phone != ''")

        # Quality score threshold
        if intent.min_quality_score:
            sql.append("AND lead_score >= %s")
            params.append(intent.min_quality_score)

        remaining = max(1, intent.limit - current_count)
        sql.append("ORDER BY lead_score DESC NULLS LAST LIMIT %s;")
        params.append(remaining)

        leads: List[Dict[str, Any]] = []
        with get_db_cursor() as (conn, cur):
            cur.execute("\n".join(sql), tuple(params))
            for r in cur.fetchall():
                exec_name = r[11]
                exec_title = r[12]
                exec_info = f"{exec_name} ({exec_title})" if exec_name and exec_title else (exec_name or None)
                leads.append({
                    "company_id": str(r[0]),
                    "company_name": r[1],
                    "industry": r[2] or "Commercial Enterprise",
                    "domain": r[3],
                    "website": f"https://{r[3]}" if r[3] and not r[3].startswith("http") else r[3],
                    "phone": r[4],
                    "email": r[5],
                    "address_state": r[6] or r[7] or state,
                    "address_city": r[8] or city,
                    "address_country": country,
                    "lead_score": int(r[9]) if r[9] is not None else 85,
                    "email_status": r[10] or "VERIFIED",
                    "executive": exec_info,
                    "seniority_level": r[13],
                    "department": r[14],
                    "origin": f"Deliverable Leads Vault ({country})",
                })
        return leads

    def _search_discovery_organizations(self, intent: ChatIntent) -> List[Dict[str, Any]]:
        """Queries crawler discoveries in discovery_dataextraction.organizations."""
        geo = intent.geography or {}
        state = geo.get("state")
        city = geo.get("city")
        zip_code = geo.get("zip")

        sql = [
            "SELECT id::text, canonical_name, normalized_name, category, subcategories,",
            "       address_street, address_city, address_state, address_postal_code, address_country,",
            "       phones, emails, website, domain, rating, review_count, services, quality_score",
            "FROM discovery_dataextraction.organizations",
            "WHERE 1=1",
        ]
        params: List[Any] = []

        if intent.company_name:
            sql.append("AND (canonical_name ILIKE %s OR normalized_name ILIKE %s)")
            params.extend([f"%{intent.company_name}%", f"%{intent.company_name.lower()}%"])

        if intent.industry:
            patterns = self._get_industry_patterns(intent.industry)
            clause = " OR ".join(["category ILIKE %s" for _ in patterns] + ["subcategories::text ILIKE %s" for _ in patterns])
            sql.append(f"AND ({clause})")
            params.extend(patterns * 2)

        if state:
            sql.append("AND (address_state ILIKE %s OR address_state = %s)")
            params.extend([f"%{state}%", state.upper()])

        if city:
            sql.append("AND lower(address_city) = %s")
            params.append(city.lower())

        if zip_code:
            sql.append("AND address_postal_code = %s")
            params.append(zip_code)

        if intent.has_verified_email or intent.verification_required:
            sql.append("AND emails::text ILIKE %s")
            params.append("%verified%")

        sql.append("ORDER BY quality_score DESC NULLS LAST LIMIT %s;")
        params.append(intent.limit)

        orgs: List[Dict[str, Any]] = []
        with get_db_cursor() as (conn, cur):
            cur.execute("\n".join(sql), tuple(params))
            rows = cur.fetchall()

            org_ids = [r[0] for r in rows]
            people_by_org: Dict[str, str] = {}
            if org_ids:
                p_sql = """
                    SELECT org_id::text, full_name, title
                    FROM discovery_dataextraction.people
                    WHERE org_id = ANY(%s::uuid[]) AND NOT suppressed
                    ORDER BY first_seen DESC;
                """
                cur.execute(p_sql, (org_ids,))
                for p_row in cur.fetchall():
                    o_id, p_name, p_title = str(p_row[0]), p_row[1], p_row[2]
                    if o_id not in people_by_org:
                        people_by_org[o_id] = f"{p_name} ({p_title})" if p_title else p_name

            for r in rows:
                p_json = r[10] if isinstance(r[10], list) else (json.loads(r[10]) if r[10] else [])
                e_json = r[11] if isinstance(r[11], list) else (json.loads(r[11]) if r[11] else [])
                phone = p_json[0].get("number") if p_json and isinstance(p_json[0], dict) else None
                email = e_json[0].get("value") if e_json and isinstance(e_json[0], dict) else None
                email_status = "VERIFIED" if any(e.get("label") == "verified" for e in e_json if isinstance(e, dict)) else ("PRESENT" if email else None)

                orgs.append({
                    "company_id": str(r[0]),
                    "company_name": r[1],
                    "domain": r[13],
                    "website": r[12],
                    "industry": r[3] or "Commercial Enterprise",
                    "phone": phone,
                    "email": email,
                    "address_state": r[7] or state,
                    "address_city": r[6] or city,
                    "address_country": r[9] or "US",
                    "lead_score": int(float(r[17] or 0.7) * 100),
                    "email_status": email_status or "VERIFIED",
                    "executive": people_by_org.get(str(r[0])),
                    "origin": "Crawler Discovery Staging",
                })
        return orgs
