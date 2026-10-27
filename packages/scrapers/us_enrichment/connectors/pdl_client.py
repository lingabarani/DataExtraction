"""
People Data Labs (PDL) API Connector.
Source: https://api.peopledatalabs.com/v5/
Provides: Enterprise company enrichment (employee count, social links, industry, tech stack)
          and Person / Decision-Maker enrichment (verified work email, phone, title, LinkedIn).
"""

import time
import requests
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..config.settings import settings
from ..models.company import USCanonicalCompany, USAddress, USPhoneItem
from ..models.person import USDecisionMaker
from ..models.source_record import SourceProvenanceRecord, RawSourcePayload

PDL_COMPANY_ENRICH_URL = "https://api.peopledatalabs.com/v5/company/enrich"
PDL_PERSON_ENRICH_URL = "https://api.peopledatalabs.com/v5/person/enrich"


class PeopleDataLabsClient:
    """
    Fetches enriched company & executive decision-maker records from People Data Labs API.
    """

    SOURCE_KEY = "PEOPLEDATALABS"
    SOURCE_NAME = "People Data Labs B2B Intelligence"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.PEOPLEDATALABS_API_KEY
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "OneExtraction-B2B/1.0",
        })

    def enrich_company(self, domain: Optional[str] = None, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Enriches company data by website domain or legal name via PDL Company Enrich API.
        """
        if not self.api_key:
            return None

        params = {}
        if domain:
            params["website"] = domain
        elif name:
            params["name"] = name
        else:
            return None

        try:
            r = self.session.get(PDL_COMPANY_ENRICH_URL, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def enrich_person(
        self,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        company_domain: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Enriches decision-maker executive contacts via PDL Person Enrich API.
        """
        if not self.api_key:
            return None

        params = {}
        if first_name:
            params["first_name"] = first_name
        if last_name:
            params["last_name"] = last_name
        if company_domain:
            params["company"] = company_domain
        if title:
            params["title"] = title

        try:
            r = self.session.get(PDL_PERSON_ENRICH_URL, params=params, timeout=15)
            if r.status_code == 200:
                return r.json().get("data")
        except Exception:
            pass
        return None

    def search_csuite_executives(self, domain: str, size: int = 4) -> List[Dict[str, Any]]:
        """
        Searches real C-Suite executives (CEO, CFO, CTO, VPs) by company website domain via PDL Person Search API.
        """
        if not self.api_key or not domain:
            return []

        search_url = "https://api.peopledatalabs.com/v5/person/search"
        clean_domain = domain.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
        payload = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"job_company_website": clean_domain}},
                        {"term": {"job_title_levels": "cxo"}}
                    ]
                }
            },
            "size": size
        }

        try:
            r = self.session.post(search_url, json=payload, timeout=20)
            if r.status_code == 200:
                return r.json().get("data", [])
        except Exception:
            pass
        return []


pdl_client = PeopleDataLabsClient()
