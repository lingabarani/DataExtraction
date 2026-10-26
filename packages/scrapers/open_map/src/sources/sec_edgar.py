import json
import logging
from typing import Any, Dict, List, Optional
from ..schema import build_empty_company_record, build_source_record, build_phone_entry
from ..normalizer import normalize_company_name, normalize_phone, normalize_state, normalize_zip
from .base import BaseSource

logger = logging.getLogger("USBusinessCollector")

class SecEdgarSource(BaseSource):
    """
    US Securities and Exchange Commission (SEC) EDGAR API.
    Publicly accessible government database.
    Rate limit: max 10 requests/sec per SEC fair access policy.
    Requires declared User-Agent with contact email.
    """

    TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
    SUBMISSION_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

    def __init__(self, contact_email: str = "researcher@example.org"):
        super().__init__(
            name="SEC EDGAR",
            source_type="GOVERNMENT_REGISTRY",
            base_url="https://data.sec.gov",
            rate_limit_delay=0.2  # 5 req/s max, well within 10/s SEC limit
        )
        self.session.headers.update({
            "User-Agent": f"OpenDataResearchCollector {contact_email}",
            "Accept": "application/json"
        })
        self._cached_tickers: Optional[Dict[str, Any]] = None

    def _get_tickers(self) -> Dict[str, Any]:
        if self._cached_tickers is None:
            self._throttle()
            try:
                resp = self.session.get(self.TICKERS_URL, timeout=15)
                if resp.status_code == 200:
                    self._cached_tickers = resp.json()
                else:
                    logger.warning(f"SEC EDGAR tickers returned status {resp.status_code}")
                    self._cached_tickers = {}
            except Exception as e:
                logger.error(f"Failed to fetch SEC tickers: {e}")
                self._cached_tickers = {}
        return self._cached_tickers

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
        tickers_data = self._get_tickers()
        matched_ciks: List[tuple] = [] # (cik, title, ticker)

        norm_query = normalize_company_name(company_name) if company_name else ""

        for _, item in tickers_data.items():
            title = item.get("title", "")
            norm_title = normalize_company_name(title)
            ticker = item.get("ticker", "")
            cik = str(item.get("cik_str", "")).zfill(10)

            if norm_query:
                if norm_query in norm_title or norm_query == ticker.lower():
                    matched_ciks.append((cik, title, ticker))
            else:
                # If no specific company name, gather up to limit
                matched_ciks.append((cik, title, ticker))

            if len(matched_ciks) >= limit * 2:
                break

        results = []
        for cik, title, ticker in matched_ciks[:limit]:
            self._throttle()
            sub_url = self.SUBMISSION_URL.format(cik=cik)
            try:
                resp = self.session.get(sub_url, timeout=15)
                if resp.status_code == 200:
                    raw_json = resp.json()
                    results.append({
                        "raw": raw_json,
                        "source_url": sub_url,
                        "source_record_id": cik,
                        "fields_available": list(raw_json.keys()),
                        "collection_method": "API"
                    })
            except Exception as e:
                logger.error(f"Error fetching SEC submission for CIK {cik}: {e}")

        return results

    def map_to_standard_company(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        data = raw_item["raw"]
        source_url = raw_item["source_url"]
        record_id = raw_item["source_record_id"]

        company = build_empty_company_record()
        
        # Identity
        legal_name = data.get("name", "").strip()
        company["legal_name"] = legal_name
        company["normalized_name"] = normalize_company_name(legal_name)
        company["entity_type"] = data.get("entityType", "")
        company["cik"] = str(data.get("cik", "")).zfill(10) if data.get("cik") else None
        company["ein"] = str(data.get("ein", "")).strip() if data.get("ein") else None

        # Business Info
        sic = data.get("sic")
        company["sic_code"] = str(sic).strip() if sic else ""
        company["industry"] = data.get("sicDescription", "")
        company["description"] = data.get("description", "") or ""

        # Address (SEC provides business and mailing)
        addresses = data.get("addresses", {})
        biz_addr = addresses.get("business", {}) or {}
        street_parts = [biz_addr.get("street1", ""), biz_addr.get("street2", "")]
        company["address"]["street"] = " ".join([p.strip() for p in street_parts if p]).strip()
        company["address"]["city"] = biz_addr.get("city", "").strip()
        
        raw_state = biz_addr.get("stateOrCountry", "").strip()
        state_name, state_code = normalize_state(raw_state)
        company["address"]["state"] = state_name or biz_addr.get("stateOrCountryDescription", "")
        company["address"]["state_code"] = state_code
        company["address"]["zip_code"] = normalize_zip(biz_addr.get("zipCode", ""))

        # Phone
        phone_num = data.get("phone", "")
        if phone_num:
            norm_phone = normalize_phone(phone_num)
            if norm_phone:
                company["phones"].append(
                    build_phone_entry(norm_phone, self.name, source_url, "OFFICE")
                )

        # Source record provenance
        collected_fields = [
            k for k in ["legal_name", "cik", "ein", "sic_code", "industry", "address", "phones"]
            if company.get(k) or (k == "address" and company["address"]["city"])
        ]
        
        company["source_records"].append(
            build_source_record(
                source_name=self.name,
                source_type=self.source_type,
                source_url=source_url,
                source_record_id=record_id,
                collection_method="API",
                fields_collected=collected_fields,
                source_status="ACTIVE"
            )
        )

        return company
