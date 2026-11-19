"""
LeadIntel email verification engine.
Validates email addresses across syntax, disposable domains, role accounts, and MX records.
Reuses canonical validation logic from packages.pipeline.contact_validator.
"""

from dataclasses import dataclass
import logging
import re
from typing import Optional, Set

from .disposable_domains import is_disposable_domain
from .email_finder import check_mx_records

try:
    from packages.pipeline.contact_validator import ROLE_PREFIXES as _CANONICAL_ROLES
except ImportError:
    _CANONICAL_ROLES = set()

ROLE_PREFIXES: Set[str] = set(_CANONICAL_ROLES) | {
    "info", "support", "sales", "contact", "admin", "administrator", "billing",
    "help", "office", "team", "marketing", "press", "legal", "care", "general",
}

logger = logging.getLogger("dataextraction.leadintel.verification")

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)


@dataclass
class VerificationResult:
    email: str
    is_valid_syntax: bool
    is_disposable: bool
    is_role_account: bool
    has_mx_records: bool
    score: float
    status: str  # "valid", "risky", "invalid"
    reason: Optional[str] = None


class VerificationEngine:
    """Evaluates deliverability indicators and produces confidence scores."""

    def verify_email(self, email: str, check_dns: bool = True) -> VerificationResult:
        if not email or not isinstance(email, str):
            return VerificationResult(
                email="",
                is_valid_syntax=False,
                is_disposable=False,
                is_role_account=False,
                has_mx_records=False,
                score=0.0,
                status="invalid",
                reason="Empty email string",
            )

        clean = email.strip().lower()
        if not EMAIL_REGEX.match(clean):
            return VerificationResult(
                email=clean,
                is_valid_syntax=False,
                is_disposable=False,
                is_role_account=False,
                has_mx_records=False,
                score=0.0,
                status="invalid",
                reason="Malformed email syntax",
            )

        local_part, domain = clean.split("@", 1)

        # Disposable check
        disposable = is_disposable_domain(domain)
        if disposable:
            return VerificationResult(
                email=clean,
                is_valid_syntax=True,
                is_disposable=True,
                is_role_account=False,
                has_mx_records=False,
                score=0.0,
                status="invalid",
                reason=f"Disposable domain {domain}",
            )

        # Role account check
        role_account = local_part in ROLE_PREFIXES or any(
            local_part.startswith(p + ".") or local_part.startswith(p + "_") for p in ROLE_PREFIXES
        )

        # MX resolution
        has_mx = True
        if check_dns:
            has_mx = check_mx_records(domain)
            if not has_mx:
                return VerificationResult(
                    email=clean,
                    is_valid_syntax=True,
                    is_disposable=False,
                    is_role_account=role_account,
                    has_mx_records=False,
                    score=0.25,
                    status="risky",
                    reason=f"Domain {domain} has no valid MX records",
                )

        score = 0.95
        if role_account:
            score -= 0.25

        status = "valid" if score >= 0.7 else "risky"

        return VerificationResult(
            email=clean,
            is_valid_syntax=True,
            is_disposable=False,
            is_role_account=role_account,
            has_mx_records=has_mx,
            score=round(score, 2),
            status=status,
            reason=None,
        )
