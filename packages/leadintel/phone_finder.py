"""
Phone number extraction and normalization service using python-phonenumbers.
Extracts numbers from raw text or HTML snippets and normalizes to E.164.
"""

from typing import Any, Dict, List, Optional
import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType


class PhoneFinder:
    """Extracts and normalizes phone numbers with region context."""

    @staticmethod
    def map_phone_type(num_type: PhoneNumberType) -> str:
        mapping = {
            PhoneNumberType.FIXED_LINE: "landline",
            PhoneNumberType.MOBILE: "mobile",
            PhoneNumberType.FIXED_LINE_OR_MOBILE: "landline_or_mobile",
            PhoneNumberType.TOLL_FREE: "toll_free",
            PhoneNumberType.PREMIUM_RATE: "premium",
            PhoneNumberType.VOIP: "voip",
            PhoneNumberType.PERSONAL_NUMBER: "personal",
            PhoneNumberType.PAGER: "pager",
            PhoneNumberType.UAN: "uan",
            PhoneNumberType.UNKNOWN: "unknown",
        }
        return mapping.get(num_type, "unknown")

    def extract_from_text(
        self,
        text: str,
        default_region: str = "US",
        source_url: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract all valid or possible phone numbers from text."""
        results: List[Dict[str, Any]] = []
        seen: set[str] = set()

        if not text or not text.strip():
            return results

        try:
            for match in phonenumbers.PhoneNumberMatcher(text, default_region):
                parsed = match.number
                if not phonenumbers.is_possible_number(parsed):
                    continue

                is_valid = phonenumbers.is_valid_number(parsed)
                e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
                intl = phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL)
                nat = phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)
                num_type = self.map_phone_type(phonenumbers.number_type(parsed))

                if e164 in seen:
                    continue
                seen.add(e164)

                results.append({
                    "raw": match.raw_string,
                    "e164": e164,
                    "international": intl,
                    "national": nat,
                    "country_code": f"+{parsed.country_code}",
                    "type": num_type,
                    "is_valid": is_valid,
                    "source_url": source_url,
                })
        except Exception:
            pass

        return results

    def format_single_number(
        self,
        number_str: str,
        default_region: str = "US",
    ) -> Optional[Dict[str, Any]]:
        """Parse and format a single phone number string."""
        if not number_str or not number_str.strip():
            return None
        try:
            parsed = phonenumbers.parse(number_str.strip(), default_region)
            if not phonenumbers.is_possible_number(parsed):
                return None
            return {
                "e164": phonenumbers.format_number(parsed, PhoneNumberFormat.E164),
                "international": phonenumbers.format_number(parsed, PhoneNumberFormat.INTERNATIONAL),
                "national": phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL),
                "country_code": f"+{parsed.country_code}",
                "type": self.map_phone_type(phonenumbers.number_type(parsed)),
                "is_valid": phonenumbers.is_valid_number(parsed),
            }
        except Exception:
            return None
