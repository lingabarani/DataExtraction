"""
Field-Level Completeness Analyzer.
Assesses whether returned company records satisfy all requested fields
and constructs a targeted missing-data plan for Live Discovery.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set
from packages.chatbot.models import (
    CompanyCompleteness,
    CompletenessReport,
    FieldAssessment,
    FieldStatus,
)

logger = logging.getLogger("dataextraction.chatbot.completeness")


class CompletenessAnalyzer:
    def analyze(
        self,
        companies: List[Dict[str, Any]],
        requested_fields: List[str],
        verification_required: bool = False,
    ) -> CompletenessReport:
        # Standardize requested fields
        target_fields = [f.lower().strip() for f in requested_fields if f]
        if not target_fields:
            target_fields = ["name", "website", "phone", "email"]

        field_stats: Dict[str, Dict[str, int]] = {f: {} for f in target_fields}
        complete_companies = 0
        incomplete_companies = 0
        missing_data_plan: List[Dict[str, Any]] = []

        for comp in companies:
            comp_id = str(comp.get("company_id") or comp.get("id") or "")
            comp_name = comp.get("company_name") or comp.get("canonical_name") or comp.get("name") or "Unknown"

            comp_assessments: Dict[str, FieldAssessment] = {}
            missing_for_comp: List[str] = []

            for f in target_fields:
                status, val = self._evaluate_field(comp, f, verification_required)
                comp_assessments[f] = FieldAssessment(
                    field_name=f,
                    status=status,
                    value=val,
                    source=comp.get("origin", "Database"),
                    confidence=0.9 if status in (FieldStatus.PRESENT, FieldStatus.VERIFIED) else 0.5,
                )

                # Update global stats
                curr_count = field_stats[f].get(status.value, 0)
                field_stats[f][status.value] = curr_count + 1

                if status in (FieldStatus.MISSING, FieldStatus.UNVERIFIED if verification_required else None):
                    missing_for_comp.append(f)

            if not missing_for_comp:
                complete_companies += 1
            else:
                incomplete_companies += 1
                missing_data_plan.append({
                    "company_id": comp_id,
                    "company_name": comp_name,
                    "domain": comp.get("domain") or self._extract_domain(comp.get("website")),
                    "city": comp.get("address_city") or (comp.get("address") or {}).get("city") or comp.get("city"),
                    "state": comp.get("address_state") or (comp.get("address") or {}).get("state") or comp.get("state"),
                    "missing_fields": missing_for_comp,
                })

        return CompletenessReport(
            total_companies=len(companies),
            complete_count=complete_companies,
            incomplete_count=incomplete_companies,
            field_stats=field_stats,
            missing_data_plan=missing_data_plan,
        )

    def _evaluate_field(
        self,
        comp: Dict[str, Any],
        field: str,
        verification_required: bool,
    ) -> tuple[FieldStatus, Any]:
        if field in ("name", "company_name"):
            val = comp.get("company_name") or comp.get("canonical_name") or comp.get("name")
            return (FieldStatus.PRESENT, val) if val else (FieldStatus.MISSING, None)

        if field in ("website", "domain"):
            val = comp.get("website") or comp.get("domain")
            return (FieldStatus.PRESENT, val) if val else (FieldStatus.MISSING, None)

        if field in ("phone", "phones"):
            val = comp.get("phone")
            if not val and comp.get("phones"):
                p_list = comp["phones"]
                if isinstance(p_list, list) and p_list:
                    val = p_list[0].get("number") if isinstance(p_list[0], dict) else str(p_list[0])
            return (FieldStatus.PRESENT, val) if val else (FieldStatus.MISSING, None)

        if field in ("email", "emails"):
            val = comp.get("email")
            is_verified = False
            if not val and comp.get("emails"):
                e_list = comp["emails"]
                if isinstance(e_list, list) and e_list:
                    first = e_list[0]
                    val = first.get("value") if isinstance(first, dict) else str(first)
                    is_verified = any(e.get("label") == "verified" for e in e_list if isinstance(e, dict))

            if not val:
                return (FieldStatus.MISSING, None)

            email_status = comp.get("email_status")
            if email_status == "VERIFIED" or is_verified:
                return (FieldStatus.VERIFIED, val)
            if verification_required:
                return (FieldStatus.UNVERIFIED, val)
            return (FieldStatus.PRESENT, val)

        if field in ("ceo", "executive", "leadership", "contact_person"):
            val = comp.get("executive") or comp.get("ceo")
            return (FieldStatus.PRESENT, val) if val else (FieldStatus.MISSING, None)

        if field in ("address", "location"):
            city = comp.get("address_city") or (comp.get("address") or {}).get("city") or comp.get("city")
            state = comp.get("address_state") or (comp.get("address") or {}).get("state") or comp.get("state")
            if city or state:
                return (FieldStatus.PRESENT, f"{city or ''}, {state or ''}".strip(", "))
            return (FieldStatus.MISSING, None)

        if field in ("services", "products"):
            val = comp.get("services") or comp.get("subcategories")
            if val and isinstance(val, list) and len(val) > 0:
                return (FieldStatus.PRESENT, val)
            return (FieldStatus.MISSING, None)

        # Fallback generic lookup
        val = comp.get(field)
        return (FieldStatus.PRESENT, val) if val else (FieldStatus.MISSING, None)

    @staticmethod
    def _extract_domain(url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        cleaned = url.lower().replace("http://", "").replace("https://", "").replace("www.", "")
        return cleaned.split("/")[0].split("?")[0]
