"""
AI Query Client for Database-First Search.
Reuses existing PostgreSQL tables (discovery_dataextraction.organizations, us_leads, mexico_leads)
with safe parameterized SQL execution and connection pooling.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from packages.chatbot.models import ChatIntent
from packages.infrastructure.db_connector import get_db_cursor

logger = logging.getLogger("dataextraction.chatbot.ai_query")


class AIQueryClient:
    """Queries existing PostgreSQL database without arbitrary SQL execution."""

    def search_database(self, intent: ChatIntent) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        # 1. First search discovery_dataextraction.organizations
        disc_orgs = self._search_discovery_organizations(intent)
        results.extend(disc_orgs)

        # 2. If needed or requested, also search master leads tables (us_leads)
        if len(results) < intent.limit:
            leads = self._search_leads_table(intent, current_count=len(results))
            # Deduplicate leads against existing orgs by name / domain
            seen_names = {r["company_name"].lower().strip() for r in results if r.get("company_name")}
            seen_domains = {r["domain"].lower().strip() for r in results if r.get("domain")}

            for l in leads:
                l_name = l.get("company_name", "").lower().strip()
                l_dom = l.get("domain", "").lower().strip()
                if l_name and l_name in seen_names:
                    continue
                if l_dom and l_dom in seen_domains:
                    continue
                results.append(l)
                if len(results) >= intent.limit:
                    break

        return results[:intent.limit]

    def _search_discovery_organizations(self, intent: ChatIntent) -> List[Dict[str, Any]]:
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

        # Targeted company name lookup
        if intent.company_name:
            sql.append("AND (canonical_name ILIKE %s OR normalized_name ILIKE %s)")
            params.extend([f"%{intent.company_name}%", f"%{intent.company_name.lower()}%"])

        # Industry filter
        if intent.industry:
            sql.append("AND (category ILIKE %s OR subcategories::text ILIKE %s)")
            params.extend([f"%{intent.industry}%", f"%{intent.industry}%"])

        # State filter
        if state:
            sql.append("AND (address_state ILIKE %s OR address_state = %s)")
            params.extend([f"%{state}%", state.upper()])

        # City filter
        if city:
            sql.append("AND lower(address_city) = %s")
            params.append(city.lower())

        # Zip filter
        if zip_code:
            sql.append("AND address_postal_code = %s")
            params.append(zip_code)

        # Verification requirement
        if intent.verification_required:
            sql.append("AND emails::text ILIKE '%verified%'")

        sql.append("ORDER BY quality_score DESC NULLS LAST, rating DESC NULLS LAST LIMIT %s;")
        params.append(intent.limit)

        orgs: List[Dict[str, Any]] = []
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("\n".join(sql), tuple(params))
                rows = cur.fetchall()

                # Get leadership for returned orgs from discovery_dataextraction.people
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
                        "normalized_name": r[2],
                        "industry": r[3],
                        "subcategories": r[4] if isinstance(r[4], list) else [],
                        "address_street": r[5],
                        "address_city": r[6],
                        "address_state": r[7],
                        "address_postal_code": r[8],
                        "address_country": r[9] or "US",
                        "phone": phone,
                        "phones": p_json,
                        "email": email,
                        "emails": e_json,
                        "website": r[12],
                        "domain": r[13],
                        "rating": float(r[14]) if r[14] is not None else None,
                        "review_count": int(r[15]) if r[15] is not None else 0,
                        "services": r[16] if isinstance(r[16], list) else [],
                        "lead_score": int(float(r[17] or 0.5) * 100),
                        "email_status": email_status,
                        "executive": people_by_org.get(str(r[0])),
                        "origin": "Database",
                    })
        except Exception as exc:
            logger.warning("Querying discovery_dataextraction.organizations failed: %s", exc)

        return orgs

    def _search_leads_table(self, intent: ChatIntent, current_count: int = 0) -> List[Dict[str, Any]]:
        geo = intent.geography or {}
        state = geo.get("state")
        target_table = "us_leads"
        if (geo.get("country") or "").upper() == "MX":
            target_table = "mexico_leads"

        sql = [
            f"SELECT id::text, company_name, industry, website, phone, email, state_code, lead_score, email_status, executive_name, executive_title",
            f"FROM {target_table}",
            "WHERE 1=1",
        ]
        params: List[Any] = []

        if intent.company_name:
            sql.append("AND company_name ILIKE %s")
            params.append(f"%{intent.company_name}%")

        if intent.industry:
            sql.append("AND industry ILIKE %s")
            params.append(f"%{intent.industry}%")

        if state:
            sql.append("AND state_code = %s")
            params.append(state.upper())

        if intent.verification_required:
            sql.append("AND email_status = 'VERIFIED'")

        remaining = max(1, intent.limit - current_count)
        sql.append("ORDER BY lead_score DESC NULLS LAST LIMIT %s;")
        params.append(remaining)

        leads: List[Dict[str, Any]] = []
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute("\n".join(sql), tuple(params))
                for r in cur.fetchall():
                    exec_info = f"{r[9]} ({r[10]})" if r[9] and r[10] else (r[9] or None)
                    leads.append({
                        "company_id": str(r[0]),
                        "company_name": r[1],
                        "industry": r[2],
                        "website": r[3],
                        "domain": r[3].replace("http://", "").replace("https://", "").split("/")[0] if r[3] else None,
                        "phone": r[4],
                        "email": r[5],
                        "address_state": r[6],
                        "lead_score": int(r[7]) if r[7] is not None else 70,
                        "email_status": r[8],
                        "executive": exec_info,
                        "origin": "Database",
                    })
        except Exception as exc:
            # Table might not exist or be empty in tests
            logger.debug("Querying leads table %s failed (skipping): %s", target_table, exc)

        return leads
