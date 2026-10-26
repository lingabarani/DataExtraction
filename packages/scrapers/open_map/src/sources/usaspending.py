import logging
from typing import Any, Dict, List, Optional
from ..schema import build_empty_company_record, build_source_record
from ..normalizer import normalize_company_name, normalize_state, normalize_zip
from .base import BaseSource

logger = logging.getLogger("USBusinessCollector")

class USASpendingSource(BaseSource):
    """
    USAspending.gov API Connector.
    Official open data source for federal awards and registered recipients.
    Publicly accessible government API, no API key required.
    """

    AUTOCOMPLETE_URL = "https://api.usaspending.gov/api/v2/autocomplete/recipient/"

    def __init__(self):
        super().__init__(
            name="USAspending.gov",
            source_type="GOVERNMENT_DATABASE",
            base_url="https://api.usaspending.gov",
            rate_limit_delay=0.5
        )

    def search(
        self,
        company_name: Optional[str] = None,
        industry: Optional[str] = None,
        state: Optional[str] = None,
        city: Optional[str] = None,
        zip_code: Optional[str] = None,
        naics_code: Optional[str] = None,
        sic_code: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        self._throttle()

        query_term = company_name or industry or "Technology"
        payload = {
            "search_text": query_term,
            "limit": limit
        }

        results = []
        try:
            resp = self.session.post(self.AUTOCOMPLETE_URL, json=payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                # The response has {'count': ..., 'results': [...]}
                recipients = data.get("results", [])
                if isinstance(recipients, list):
                    for item in recipients[:limit]:
                        results.append({
                            "raw": item,
                            "source_url": self.AUTOCOMPLETE_URL,
                            "source_record_id": str(item.get("recipient_unique_id", "") or item.get("recipient_id", "") or item.get("recipient_name", "")),
                            "fields_available": list(item.keys()),
                            "collection_method": "API"
                        })
        except Exception as e:
            logger.error(f"Error querying USAspending: {e}")

        return results

    def map_to_standard_company(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        data = raw_item["raw"]
        source_url = raw_item["source_url"]
        record_id = raw_item["source_record_id"]

        company = build_empty_company_record()
        
        legal_name = data.get("recipient_name", "").strip()
        company["legal_name"] = legal_name
        company["normalized_name"] = normalize_company_name(legal_name)
        company["uei"] = data.get("uei")
        company["duns"] = data.get("duns") or (record_id if len(record_id) == 9 and record_id.isdigit() else None)

        collected = ["legal_name"]
        if company["uei"]: collected.append("uei")
        if company["duns"]: collected.append("duns")

        company["source_records"].append(
            build_source_record(
                source_name=self.name,
                source_type=self.source_type,
                source_url=source_url,
                source_record_id=record_id,
                collection_method="API",
                fields_collected=collected,
                source_status="ACTIVE"
            )
        )

        return company
