"""
Result Merger, Reconciliation, and Provenance Tracker.
Combines database results and Live Discovery results without corrupting golden records.
Stages all newly discovered attributes for human review.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

logger = logging.getLogger("dataextraction.chatbot.merger")


class ResultMerger:
    @staticmethod
    def normalize_name(name: str) -> str:
        if not name:
            return ""
        cleaned = name.lower()
        for suffix in [" inc", " llc", " corp", " corporation", " ltd", " co", " company", " group", ",", "."]:
            cleaned = cleaned.replace(suffix, "")
        return cleaned.strip()

    @staticmethod
    def normalize_domain(domain_or_url: Optional[str]) -> str:
        if not domain_or_url:
            return ""
        cleaned = domain_or_url.lower().replace("http://", "").replace("https://", "").replace("www.", "")
        return cleaned.split("/")[0].split("?")[0].strip()

    def merge_and_stage(
        self,
        session_id: str,
        db_companies: List[Dict[str, Any]],
        discovered_orgs: List[Dict[str, Any]],
        run_id: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Merges DB records and Live Discovery records.
        Returns:
            (merged_companies, staged_review_items)
        """
        merged: List[Dict[str, Any]] = [dict(c) for c in db_companies]
        staged_items: List[Dict[str, Any]] = []

        # Index existing DB companies by normalized name and domain
        name_to_idx: Dict[str, int] = {}
        domain_to_idx: Dict[str, int] = {}

        for idx, comp in enumerate(merged):
            norm_n = self.normalize_name(comp.get("company_name") or comp.get("canonical_name") or "")
            if norm_n:
                name_to_idx[norm_n] = idx
            norm_d = self.normalize_domain(comp.get("domain") or comp.get("website"))
            if norm_d:
                domain_to_idx[norm_d] = idx

        # Process discovered records
        for disc in discovered_orgs:
            d_name = disc.get("canonical_name") or disc.get("name") or ""
            norm_d_name = self.normalize_name(d_name)
            d_domain = self.normalize_domain(disc.get("domain") or disc.get("website"))

            # Check match against existing DB records
            match_idx = None
            if norm_d_name and norm_d_name in name_to_idx:
                match_idx = name_to_idx[norm_d_name]
            elif d_domain and d_domain in domain_to_idx:
                match_idx = domain_to_idx[d_domain]

            if match_idx is not None:
                # Existing company match: reconcile missing or conflicting fields
                target_comp = merged[match_idx]
                target_id = str(target_comp.get("company_id") or target_comp.get("id") or str(uuid4()))
                c_name = target_comp.get("company_name") or target_comp.get("canonical_name") or d_name

                # Check website
                d_web = disc.get("website")
                if d_web and not target_comp.get("website"):
                    target_comp["website"] = d_web
                    target_comp["website_pending_review"] = True
                    staged_items.append(self._create_review_dict(
                        session_id=session_id,
                        run_id=run_id,
                        company_id=target_id,
                        company_name=c_name,
                        field_name="website",
                        existing_value=None,
                        discovered_value=d_web,
                        source_type=disc.get("source", "Live Discovery"),
                        source_url=disc.get("source_url") or d_web,
                        evidence=f"Discovered website via {disc.get('source', 'Live Discovery')}",
                    ))

                # Check phone
                d_phone = disc.get("phone")
                if not d_phone and disc.get("phones"):
                    d_phone = disc["phones"][0].get("number") if isinstance(disc["phones"][0], dict) else str(disc["phones"][0])

                if d_phone:
                    ex_phone = target_comp.get("phone")
                    if not ex_phone:
                        target_comp["phone"] = d_phone
                        target_comp["phone_pending_review"] = True
                        staged_items.append(self._create_review_dict(
                            session_id=session_id,
                            run_id=run_id,
                            company_id=target_id,
                            company_name=c_name,
                            field_name="phone",
                            existing_value=None,
                            discovered_value=d_phone,
                            source_type=disc.get("source", "Live Discovery"),
                            source_url=disc.get("source_url"),
                            evidence="Discovered phone contact",
                        ))
                    elif ex_phone != d_phone:
                        # Conflict detected
                        target_comp["phone_conflict"] = {"database": ex_phone, "discovered": d_phone}
                        staged_items.append(self._create_review_dict(
                            session_id=session_id,
                            run_id=run_id,
                            company_id=target_id,
                            company_name=c_name,
                            field_name="phone",
                            existing_value=ex_phone,
                            discovered_value=d_phone,
                            source_type=disc.get("source", "Live Discovery"),
                            source_url=disc.get("source_url"),
                            verification_status="CONFLICTING",
                            conflict_details={"db_value": ex_phone, "discovered_value": d_phone},
                            evidence=f"Conflicting phone numbers: DB has {ex_phone}, Live Discovery found {d_phone}",
                        ))

                # Check email
                d_email = disc.get("email")
                if not d_email and disc.get("emails"):
                    d_email = disc["emails"][0].get("value") if isinstance(disc["emails"][0], dict) else str(disc["emails"][0])

                if d_email:
                    ex_email = target_comp.get("email")
                    if not ex_email:
                        target_comp["email"] = d_email
                        target_comp["email_pending_review"] = True
                        staged_items.append(self._create_review_dict(
                            session_id=session_id,
                            run_id=run_id,
                            company_id=target_id,
                            company_name=c_name,
                            field_name="email",
                            existing_value=None,
                            discovered_value=d_email,
                            source_type=disc.get("source", "Live Discovery"),
                            source_url=disc.get("source_url"),
                            evidence="Discovered contact email",
                        ))
                    elif ex_email.lower() != d_email.lower():
                        target_comp["email_conflict"] = {"database": ex_email, "discovered": d_email}
                        staged_items.append(self._create_review_dict(
                            session_id=session_id,
                            run_id=run_id,
                            company_id=target_id,
                            company_name=c_name,
                            field_name="email",
                            existing_value=ex_email,
                            discovered_value=d_email,
                            source_type=disc.get("source", "Live Discovery"),
                            source_url=disc.get("source_url"),
                            verification_status="CONFLICTING",
                            conflict_details={"db_value": ex_email, "discovered_value": d_email},
                            evidence=f"Conflicting email addresses: DB has {ex_email}, Live Discovery found {d_email}",
                        ))

                # Check leadership
                d_exec = disc.get("executive") or disc.get("ceo")
                if d_exec and not target_comp.get("executive"):
                    target_comp["executive"] = d_exec
                    target_comp["executive_pending_review"] = True
                    staged_items.append(self._create_review_dict(
                        session_id=session_id,
                        run_id=run_id,
                        company_id=target_id,
                        company_name=c_name,
                        field_name="executive",
                        existing_value=None,
                        discovered_value=d_exec,
                        source_type=disc.get("source", "Live Discovery"),
                        source_url=disc.get("source_url"),
                        evidence="Discovered executive leadership",
                    ))

            else:
                # Completely new company found via Live Discovery
                new_comp_id = str(disc.get("id") or uuid4())
                new_comp = {
                    "company_id": new_comp_id,
                    "company_name": d_name or "Discovered Company",
                    "canonical_name": d_name or "Discovered Company",
                    "industry": disc.get("category"),
                    "website": disc.get("website"),
                    "domain": disc.get("domain") or d_domain,
                    "phone": disc.get("phone") or (disc["phones"][0].get("number") if disc.get("phones") else None),
                    "email": disc.get("email") or (disc["emails"][0].get("value") if disc.get("emails") else None),
                    "address_city": (disc.get("address") or {}).get("city") or disc.get("city"),
                    "address_state": (disc.get("address") or {}).get("state") or disc.get("state"),
                    "address_country": (disc.get("address") or {}).get("country") or "US",
                    "executive": disc.get("executive") or disc.get("ceo"),
                    "origin": "Live Discovery",
                    "pending_review": True,
                }
                merged.append(new_comp)

                # Stage its key attributes for review
                staged_items.append(self._create_review_dict(
                    session_id=session_id,
                    run_id=run_id,
                    company_id=new_comp_id,
                    company_name=new_comp["company_name"],
                    field_name="organization_discovery",
                    existing_value=None,
                    discovered_value=new_comp,
                    source_type=disc.get("source", "Live Discovery"),
                    source_url=disc.get("source_url") or new_comp.get("website"),
                    evidence=f"Discovered new organization matching query in {new_comp.get('address_city') or new_comp.get('address_state') or 'target location'}",
                ))

        return merged, staged_items

    @staticmethod
    def _create_review_dict(
        session_id: str,
        company_id: str,
        company_name: str,
        field_name: str,
        discovered_value: Any,
        source_type: str,
        run_id: Optional[str] = None,
        existing_value: Any = None,
        source_url: Optional[str] = None,
        evidence: Optional[str] = None,
        verification_status: str = "UNVERIFIED",
        conflict_details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "session_id": session_id,
            "run_id": run_id,
            "company_id": company_id,
            "company_name": company_name,
            "field_name": field_name,
            "existing_value": existing_value,
            "discovered_value": discovered_value,
            "source_type": source_type,
            "source_url": source_url,
            "evidence": evidence,
            "field_confidence": 0.8,
            "verification_status": verification_status,
            "conflict_details": conflict_details,
        }
