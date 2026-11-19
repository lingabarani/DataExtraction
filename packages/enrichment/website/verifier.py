"""
DataExtraction — Website Field Cross-Verification Engine
=========================================================
Audits existing corporate information from Agent 1 (Registry) and Agent 2 (Maps/OSM)
against evidence extracted from verified official corporate websites.
Identifies:
- VERIFIED: Website evidence confirms existing staging data.
- CONFLICT: Website evidence disputes existing staging data (never silently overwritten).
- NEW_DISCOVERY: Novel corporate metadata discovered exclusively on official site.
- UNVERIFIED: Existing field not mentioned on crawled pages.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("dataextraction.enrichment.verifier")


def _normalize_string(val: Optional[str]) -> str:
    if not val:
        return ""
    # Strip punctuation, extra spaces, corporate suffixes for comparison
    clean = re.sub(r"[^\w\s]", "", str(val).lower())
    clean = re.sub(r"\b(inc|llc|corp|ltd|co|limited|corporation|incorporated)\b", "", clean)
    return re.sub(r"\s+", " ", clean).strip()


def _normalize_phone(val: Optional[str]) -> str:
    if not val:
        return ""
    # Strip non-digits
    digits = re.sub(r"\D", "", str(val))
    # Normalize US 1-prefix
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


class FieldCrossVerifier:
    """Compares upstream company stubs against extracted website evidence."""

    @staticmethod
    def verify_company_fields(
        domain: str,
        upstream_record: Dict[str, Any],
        website_evidence: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        upstream_record: {"name": ..., "phone": ..., "email": ..., "address": ..., "city": ..., "state": ..., "postal_code": ...}
        website_evidence: {
            "names": [{"value": ..., "source_url": ..., "snippet": ...}],
            "phones": [{"value": ..., "source_url": ..., "snippet": ...}],
            "emails": [{"value": ..., "source_url": ..., "snippet": ...}],
            "addresses": [{"value": ..., "city": ..., "state": ..., "postal_code": ..., "source_url": ..., "snippet": ...}],
        }
        """
        results: List[Dict[str, Any]] = []

        # 1. Company Name Verification
        orig_name = upstream_record.get("name")
        web_names = website_evidence.get("names") or []
        if orig_name:
            norm_orig = _normalize_string(orig_name)
            matched = False
            for w in web_names:
                norm_w = _normalize_string(w.get("value"))
                if norm_orig and norm_w and (norm_orig in norm_w or norm_w in norm_orig):
                    results.append({
                        "domain": domain,
                        "field_name": "company_name",
                        "original_value": orig_name,
                        "website_value": w.get("value"),
                        "status": "VERIFIED",
                        "evidence_url": w.get("source_url"),
                        "evidence_snippet": w.get("snippet"),
                        "confidence": 0.95,
                    })
                    matched = True
                    break
            if not matched and web_names:
                results.append({
                    "domain": domain,
                    "field_name": "company_name",
                    "original_value": orig_name,
                    "website_value": web_names[0].get("value"),
                    "status": "CONFLICT",
                    "evidence_url": web_names[0].get("source_url"),
                    "evidence_snippet": web_names[0].get("snippet"),
                    "confidence": 0.80,
                })
            elif not matched:
                results.append({
                    "domain": domain,
                    "field_name": "company_name",
                    "original_value": orig_name,
                    "website_value": None,
                    "status": "UNVERIFIED",
                    "evidence_url": None,
                    "evidence_snippet": None,
                    "confidence": 0.50,
                })

        # 2. Phone Verification
        orig_phone = upstream_record.get("phone")
        web_phones = website_evidence.get("phones") or []
        norm_orig_phone = _normalize_phone(orig_phone)
        if norm_orig_phone:
            matched = False
            for wp in web_phones:
                norm_wp = _normalize_phone(wp.get("value"))
                if norm_orig_phone == norm_wp:
                    results.append({
                        "domain": domain,
                        "field_name": "phone",
                        "original_value": orig_phone,
                        "website_value": wp.get("value"),
                        "status": "VERIFIED",
                        "evidence_url": wp.get("source_url"),
                        "evidence_snippet": wp.get("snippet"),
                        "confidence": 0.98,
                    })
                    matched = True
                    break
            if not matched and web_phones:
                results.append({
                    "domain": domain,
                    "field_name": "phone",
                    "original_value": orig_phone,
                    "website_value": web_phones[0].get("value"),
                    "status": "CONFLICT",
                    "evidence_url": web_phones[0].get("source_url"),
                    "evidence_snippet": web_phones[0].get("snippet"),
                    "confidence": 0.85,
                })
        elif web_phones:
            results.append({
                "domain": domain,
                "field_name": "phone",
                "original_value": None,
                "website_value": web_phones[0].get("value"),
                "status": "NEW_DISCOVERY",
                "evidence_url": web_phones[0].get("source_url"),
                "evidence_snippet": web_phones[0].get("snippet"),
                "confidence": 0.90,
            })

        # 3. Email Verification
        orig_email = upstream_record.get("email")
        web_emails = website_evidence.get("emails") or []
        if orig_email:
            clean_orig_email = orig_email.strip().lower()
            matched = False
            for we in web_emails:
                clean_we = (we.get("value") or "").strip().lower()
                if clean_orig_email == clean_we:
                    results.append({
                        "domain": domain,
                        "field_name": "email",
                        "original_value": orig_email,
                        "website_value": we.get("value"),
                        "status": "VERIFIED",
                        "evidence_url": we.get("source_url"),
                        "evidence_snippet": we.get("snippet"),
                        "confidence": 0.99,
                    })
                    matched = True
                    break
            if not matched and web_emails:
                results.append({
                    "domain": domain,
                    "field_name": "email",
                    "original_value": orig_email,
                    "website_value": web_emails[0].get("value"),
                    "status": "CONFLICT",
                    "evidence_url": web_emails[0].get("source_url"),
                    "evidence_snippet": web_emails[0].get("snippet"),
                    "confidence": 0.80,
                })
        elif web_emails:
            results.append({
                "domain": domain,
                "field_name": "email",
                "original_value": None,
                "website_value": web_emails[0].get("value"),
                "status": "NEW_DISCOVERY",
                "evidence_url": web_emails[0].get("source_url"),
                "evidence_snippet": web_emails[0].get("snippet"),
                "confidence": 0.92,
            })

        # 4. Postal Code & City Verification
        orig_zip = upstream_record.get("postal_code") or upstream_record.get("zip_code")
        web_addresses = website_evidence.get("addresses") or []
        if orig_zip:
            norm_zip = re.sub(r"\D", "", str(orig_zip))[:5]
            matched = False
            for wa in web_addresses:
                w_zip = re.sub(r"\D", "", str(wa.get("postal_code") or ""))[:5]
                if norm_zip and norm_zip == w_zip:
                    results.append({
                        "domain": domain,
                        "field_name": "postal_code",
                        "original_value": orig_zip,
                        "website_value": wa.get("postal_code"),
                        "status": "VERIFIED",
                        "evidence_url": wa.get("source_url"),
                        "evidence_snippet": wa.get("snippet"),
                        "confidence": 0.95,
                    })
                    matched = True
                    break
            if not matched and web_addresses and any(wa.get("postal_code") for wa in web_addresses):
                first_w_zip = next(wa.get("postal_code") for wa in web_addresses if wa.get("postal_code"))
                results.append({
                    "domain": domain,
                    "field_name": "postal_code",
                    "original_value": orig_zip,
                    "website_value": first_w_zip,
                    "status": "CONFLICT",
                    "evidence_url": web_addresses[0].get("source_url"),
                    "evidence_snippet": web_addresses[0].get("snippet"),
                    "confidence": 0.85,
                })

        return results
