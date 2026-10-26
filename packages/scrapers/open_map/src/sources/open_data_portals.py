import logging
from typing import Any, Dict, List, Optional
from ..schema import build_empty_company_record, build_source_record, build_phone_entry
from ..normalizer import normalize_company_name, normalize_phone, normalize_state, normalize_zip
from .base import BaseSource

logger = logging.getLogger("USBusinessCollector")

class MunicipalOpenDataSource(BaseSource):
    """
    US Municipal and State Open Data Portals (Socrata Open Data APIs under Data.gov standards).
    Publicly accessible government open datasets.
    No authentication required for open queries.
    """

    PORTALS = {
        "SF": {
            "name": "City of San Francisco Open Data",
            "url": "https://data.sfgov.org/resource/g8m3-pdis.json",
            "state_code": "CA",
            "city": "San Francisco",
            "name_col": "ownership_name",
            "dba_col": "dba_name",
            "id_col": "location_id",
            "street_col": "street_address",
            "city_col": "city",
            "state_col": "state",
            "zip_col": "source_zipcode",
            "naics_col": "naics_code",
            "industry_col": "naics_code_description"
        },
        "LA": {
            "name": "City of Los Angeles Open Data",
            "url": "https://data.lacity.org/resource/6rrh-rzua.json",
            "state_code": "CA",
            "city": "Los Angeles",
            "name_col": "business_name",
            "dba_col": "dba_name",
            "id_col": "account_key",
            "street_col": "street_address",
            "city_col": "city",
            "state_col": "state",
            "zip_col": "zip_code",
            "naics_col": "naics",
            "industry_col": "primary_naics_description"
        },
        "CHICAGO": {
            "name": "City of Chicago Open Data",
            "url": "https://data.cityofchicago.org/resource/u9hu-wpgb.json",
            "state_code": "IL",
            "city": "Chicago",
            "name_col": "legal_name",
            "dba_col": "doing_business_as_name",
            "id_col": "license_id",
            "street_col": "address",
            "city_col": "city",
            "state_col": "state",
            "zip_col": "zip_code",
            "naics_col": None,
            "industry_col": "business_activity_description"
        }
    }

    def __init__(self):
        super().__init__(
            name="US Municipal Open Data Portals",
            source_type="GOVERNMENT_OPEN_DATA_PORTAL",
            base_url="https://data.gov",
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
        results = []

        # Determine which portal(s) to query
        norm_state = normalize_state(state)[1] if state else ""
        norm_city = city.lower().strip() if city else ""

        selected_portals = []
        for key, p in self.PORTALS.items():
            if norm_state and p["state_code"] != norm_state:
                continue
            if norm_city and norm_city not in p["city"].lower():
                continue
            selected_portals.append(p)

        if not selected_portals:
            # Default to all if no location constraint specified
            selected_portals = list(self.PORTALS.values())

        per_portal_limit = max(2, limit // len(selected_portals) + 1)

        for portal in selected_portals:
            params = {"$limit": per_portal_limit}
            where_clauses = []

            if company_name:
                esc_name = company_name.replace("'", "''")
                where_clauses.append(f"(lower({portal['name_col']}) like '%{esc_name.lower()}%' or lower({portal['dba_col']}) like '%{esc_name.lower()}%')")

            if naics_code and portal.get("naics_col"):
                where_clauses.append(f"{portal['naics_col']} like '{naics_code}%'")

            if zip_code:
                where_clauses.append(f"{portal['zip_col']} like '{zip_code}%'")

            if where_clauses:
                params["$where"] = " AND ".join(where_clauses)

            try:
                resp = self.session.get(portal["url"], params=params, timeout=15)
                if resp.status_code == 200:
                    rows = resp.json()
                    for row in rows:
                        results.append({
                            "raw": row,
                            "source_url": portal["url"],
                            "source_record_id": str(row.get(portal["id_col"], "")),
                            "portal_meta": portal,
                            "fields_available": list(row.keys()),
                            "collection_method": "API"
                        })
                        if len(results) >= limit:
                            break
            except Exception as e:
                logger.error(f"Error querying portal {portal['name']}: {e}")

            if len(results) >= limit:
                break

        return results[:limit]

    def map_to_standard_company(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        data = raw_item["raw"]
        portal = raw_item["portal_meta"]
        source_url = raw_item["source_url"]
        record_id = raw_item["source_record_id"]

        company = build_empty_company_record()

        legal_name = data.get(portal["name_col"], "").strip()
        dba_name = data.get(portal["dba_col"], "").strip()

        company["legal_name"] = legal_name or dba_name
        company["dba_name"] = dba_name if dba_name != legal_name else ""
        company["normalized_name"] = normalize_company_name(company["legal_name"])
        company["registration_number"] = record_id
        company["company_status"] = data.get("business_status", "") or data.get("status", "") or "ACTIVE"

        # Address
        company["address"]["street"] = data.get(portal["street_col"], "").strip()
        company["address"]["city"] = data.get(portal["city_col"], portal["city"]).strip()
        
        state_raw = data.get(portal["state_col"], portal["state_code"])
        state_name, state_code = normalize_state(state_raw)
        company["address"]["state"] = state_name
        company["address"]["state_code"] = state_code
        company["address"]["zip_code"] = normalize_zip(data.get(portal["zip_col"], ""))

        # Coordinates if present in Socrata format
        loc = data.get("location") or data.get("location_1") or data.get("geom")
        if isinstance(loc, dict) and "latitude" in loc and "longitude" in loc:
            try:
                company["address"]["latitude"] = float(loc["latitude"])
                company["address"]["longitude"] = float(loc["longitude"])
            except (ValueError, TypeError):
                pass

        # Industry / NAICS
        if portal.get("naics_col") and data.get(portal["naics_col"]):
            company["naics_code"] = str(data.get(portal["naics_col"])).strip()

        if portal.get("industry_col") and data.get(portal["industry_col"]):
            company["industry"] = str(data.get(portal["industry_col"])).strip()

        # Source record provenance
        collected = ["legal_name", "registration_number", "address"]
        if company["dba_name"]: collected.append("dba_name")
        if company["naics_code"]: collected.append("naics_code")
        if company["industry"]: collected.append("industry")

        company["source_records"].append(
            build_source_record(
                source_name=portal["name"],
                source_type="GOVERNMENT_REGISTRY",
                source_url=source_url,
                source_record_id=record_id,
                collection_method="API",
                fields_collected=collected,
                source_status="ACTIVE"
            )
        )

        return company
