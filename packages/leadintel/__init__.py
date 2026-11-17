"""
LeadIntel service package for contact extraction, email permutation, verification, and deduplication.
"""

from .disposable_domains import DISPOSABLE_DOMAINS, is_disposable_domain
from .phone_finder import PhoneFinder
from .email_finder import (
    FREE_EMAIL_PROVIDERS,
    check_mx_records,
    company_domain,
    generate_email_candidates,
    infer_email_entry,
)
from .verification_engine import VerificationEngine, VerificationResult
from .parser import TeamPageParser
from .deduplication import generate_company_match_key, generate_person_match_key, normalize_string

__all__ = [
    "DISPOSABLE_DOMAINS",
    "is_disposable_domain",
    "PhoneFinder",
    "FREE_EMAIL_PROVIDERS",
    "company_domain",
    "generate_email_candidates",
    "check_mx_records",
    "infer_email_entry",
    "VerificationEngine",
    "VerificationResult",
    "TeamPageParser",
    "generate_company_match_key",
    "generate_person_match_key",
    "normalize_string",
]
