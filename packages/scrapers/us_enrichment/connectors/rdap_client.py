"""
RDAP WHOIS Domain Ownership Connector.
Source: https://rdap.org/domain/{domain}
Coverage: All registered .com, .org, .net, .edu, .gov, .us domain names.
Provides: Registrant Legal Organization Name, Creation Date, Registrar Name, Domain Status, Tech Contacts.
No API key required. Rate limit: Free open ICANN RDAP protocol.
"""

import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..models.source_record import RawSourcePayload

try:
    from botasaurus.request import request as bt_request, Request as BtRequest
    HAS_BOTASAURUS = True
except ImportError:
    HAS_BOTASAURUS = False

RDAP_BASE_URL = "https://rdap.org/domain/"

if HAS_BOTASAURUS:
    @bt_request(cache=True, parallel=4, output=None)
    def fetch_rdap_domain_botasaurus(request: BtRequest, domain: str) -> Dict[str, Any]:
        """Botasaurus @request decorated fetcher for ICANN RDAP domain WHOIS."""
        clean_d = domain.lower().replace("www.", "").strip("/")
        url = f"{RDAP_BASE_URL}{clean_d}"
        headers = {
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json, application/rdap+json",
        }
        try:
            response = request.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {}


class RDAPClient:
    """
    Fetches open domain ownership & registrar data from ICANN RDAP servers.
    """

    SOURCE_KEY = "RDAP_WHOIS"
    SOURCE_NAME = "ICANN RDAP Domain Registry"

    def __init__(self, rate_limit_rps: float = 3.0):
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json, application/rdap+json",
        })

    def fetch_domain_info(self, domain: str) -> Optional[Dict[str, Any]]:
        """Queries RDAP protocol for domain registration details."""
        clean_d = domain.lower().replace("www.", "").strip("/")
        if not clean_d or "." not in clean_d:
            return None

        if HAS_BOTASAURUS:
            try:
                res = fetch_rdap_domain_botasaurus(clean_d)
                if res:
                    return self.parse_rdap_response(res, clean_d)
            except Exception:
                pass

        time.sleep(self.delay)
        try:
            r = self.session.get(f"{RDAP_BASE_URL}{clean_d}", timeout=10)
            if r.status_code == 200:
                return self.parse_rdap_response(r.json(), clean_d)
        except Exception:
            pass
        return None

    def parse_rdap_response(self, data: Dict[str, Any], domain: str) -> Dict[str, Any]:
        """Parses raw RDAP vCard / entity JSON structure."""
        parsed = {
            "domain": domain,
            "handle": data.get("handle"),
            "registrant_organization": None,
            "registrar_name": None,
            "creation_date": None,
            "expiration_date": None,
            "domain_status": data.get("status", []),
        }

        # Extract creation / expiration dates from events
        for evt in data.get("events", []) or []:
            action = evt.get("eventAction", "")
            date_str = evt.get("eventDate", "")
            if action == "registration":
                parsed["creation_date"] = date_str
            elif action == "expiration":
                parsed["expiration_date"] = date_str

        # Extract entities (registrant / registrar)
        for entity in data.get("entities", []) or []:
            roles = entity.get("roles", [])
            vcard = entity.get("vcardArray", [])
            fn = _extract_vcard_fn(vcard)

            if "registrant" in roles:
                parsed["registrant_organization"] = fn or entity.get("handle")
            elif "registrar" in roles:
                parsed["registrar_name"] = fn or entity.get("handle")

        return parsed


def _extract_vcard_fn(vcard_array: List[Any]) -> Optional[str]:
    """Helper to extract fn (formatted name/org) from jCard/vCard JSON array."""
    if not vcard_array or len(vcard_array) < 2:
        return None
    try:
        entries = vcard_array[1]
        for item in entries:
            if isinstance(item, list) and len(item) >= 4:
                prop_name = item[0]
                if prop_name in ("fn", "org"):
                    val = item[3]
                    if isinstance(val, list):
                        return " ".join(str(v) for v in val if v).strip()
                    return str(val).strip()
    except Exception:
        pass
    return None


rdap_client = RDAPClient()
