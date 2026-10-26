import os
import json
import csv
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .schema import build_empty_company_record
from .normalizer import normalize_company_name
from .fingerprint import generate_entity_fingerprint
from .scorer import calculate_data_quality_score
from .sources import (
    BaseSource,
    SecEdgarSource,
    OpenStreetMapSource,
    MunicipalOpenDataSource,
    USASpendingSource
)

def get_utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

SOURCE_PRIORITY = {
    "GOVERNMENT_REGISTRY": 1,
    "GOVERNMENT_DATABASE": 2,
    "GOVERNMENT_OPEN_DATA_PORTAL": 3,
    "COMPANY_WEBSITE": 4,
    "OPEN_GEOSPATIAL_DATABASE": 5,
    "OPEN_DIRECTORY": 6
}

class CollectionPipeline:
    def __init__(self, output_base_dir: str):
        self.output_base_dir = output_base_dir
        self.raw_dir = os.path.join(output_base_dir, "data", "raw")
        self.processed_dir = os.path.join(output_base_dir, "data", "processed")
        self.export_dir = os.path.join(output_base_dir, "data", "export")
        self.logs_dir = os.path.join(output_base_dir, "logs")

        for d in [self.raw_dir, self.processed_dir, self.export_dir, self.logs_dir]:
            os.makedirs(d, exist_ok=True)

        self.logger = self._setup_logger()

        # Available sources registry
        self.available_sources: Dict[str, BaseSource] = {
            "sec_edgar": SecEdgarSource(),
            "osm": OpenStreetMapSource(),
            "open_data_portals": MunicipalOpenDataSource(),
            "usaspending": USASpendingSource()
        }

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("USBusinessCollector")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            log_file = os.path.join(self.logs_dir, f"collection_{get_utc_timestamp()}.log")
            fh = logging.FileHandler(log_file, encoding="utf-8")
            sh = logging.StreamHandler()
            formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
            fh.setFormatter(formatter)
            sh.setFormatter(formatter)
            logger.addHandler(fh)
            logger.addHandler(sh)
        return logger

    def _merge_company_records(self, existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges incoming record into existing record while preserving source provenance
        and respecting source priority.
        """
        existing_sources = [s.get("source_type", "") for s in existing.get("source_records", [])]
        incoming_sources = [s.get("source_type", "") for s in incoming.get("source_records", [])]

        existing_prio = min([SOURCE_PRIORITY.get(st, 99) for st in existing_sources] or [99])
        incoming_prio = min([SOURCE_PRIORITY.get(st, 99) for st in incoming_sources] or [99])

        overwrite = incoming_prio < existing_prio

        # Update scalar fields if empty or if higher priority
        for field in [
            "legal_name", "trade_name", "dba_name", "entity_type", "company_status",
            "registration_number", "state_registration_number", "ein", "uei", "duns",
            "cik", "description", "industry", "industry_code", "naics_code", "sic_code",
            "business_category", "website", "domain"
        ]:
            inc_val = incoming.get(field)
            ex_val = existing.get(field)
            if inc_val:
                if not ex_val or overwrite:
                    existing[field] = inc_val

        # Address merging
        for a_field in ["street", "city", "state", "state_code", "zip_code", "county"]:
            inc_val = incoming["address"].get(a_field)
            ex_val = existing["address"].get(a_field)
            if inc_val:
                if not ex_val or overwrite:
                    existing["address"][a_field] = inc_val

        if incoming["address"].get("latitude") is not None and (existing["address"].get("latitude") is None or overwrite):
            existing["address"]["latitude"] = incoming["address"]["latitude"]
            existing["address"]["longitude"] = incoming["address"]["longitude"]

        # Phones list (deduplicate by value)
        existing_phone_vals = {p.get("value") for p in existing.get("phones", [])}
        for p in incoming.get("phones", []):
            if p.get("value") not in existing_phone_vals:
                existing["phones"].append(p)
                existing_phone_vals.add(p.get("value"))

        # Emails list (deduplicate by value)
        existing_email_vals = {e.get("value") for e in existing.get("emails", [])}
        for e in incoming.get("emails", []):
            if e.get("value") not in existing_email_vals:
                existing["emails"].append(e)
                existing_email_vals.add(e.get("value"))

        # Append source records provenance
        for sr in incoming.get("source_records", []):
            existing["source_records"].append(sr)

        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        return existing

    def run_collection(
        self,
        company_name: Optional[str] = None,
        industry: Optional[str] = None,
        state: Optional[str] = None,
        city: Optional[str] = None,
        zip_code: Optional[str] = None,
        naics_code: Optional[str] = None,
        sic_code: Optional[str] = None,
        limit: int = 10,
        sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        timestamp = get_utc_timestamp()
        self.logger.info(f"Starting US Business Data Collection at {timestamp}")
        self.logger.info(f"Query filters: company_name='{company_name}', industry='{industry}', state='{state}', city='{city}', zip='{zip_code}', naics='{naics_code}', limit={limit}")

        target_source_keys = sources or list(self.available_sources.keys())
        raw_collection: List[Dict[str, Any]] = []
        source_usage_info: List[Dict[str, Any]] = []

        total_collected_raw = 0
        total_failed_records = 0
        error_details = []

        # Step 1: Query selected open sources
        for s_key in target_source_keys:
            if s_key not in self.available_sources:
                self.logger.warning(f"Source '{s_key}' not recognized. Skipping.")
                continue

            src = self.available_sources[s_key]
            self.logger.info(f"Querying source: {src.name} ({src.source_type})...")
            try:
                items = src.search(
                    company_name=company_name,
                    industry=industry,
                    state=state,
                    city=city,
                    zip_code=zip_code,
                    naics_code=naics_code,
                    sic_code=sic_code,
                    limit=limit
                )
                self.logger.info(f"Retrieved {len(items)} records from {src.name}.")
                total_collected_raw += len(items)
                source_usage_info.append({
                    "source_name": src.name,
                    "source_type": src.source_type,
                    "count": len(items),
                    "method": "API"
                })

                for it in items:
                    raw_collection.append({
                        "source_key": s_key,
                        "item": it
                    })
            except Exception as e:
                self.logger.error(f"Failed querying {src.name}: {e}")
                error_details.append(f"{src.name}: {str(e)}")

        # Step 2: Save raw data
        raw_file_path = os.path.join(self.raw_dir, f"raw_collection_{timestamp}.json")
        with open(raw_file_path, "w", encoding="utf-8") as f:
            json.dump(raw_collection, f, indent=2, ensure_ascii=False)
        self.logger.info(f"Saved raw collection data to {raw_file_path}")

        # Step 3: Mapping, Normalization, Deduplication & Quality Scoring
        companies_by_fingerprint: Dict[str, Dict[str, Any]] = {}
        duplicates_count = 0
        successful_normalized = 0

        all_fields_available = set()

        for wrapper in raw_collection:
            s_key = wrapper["source_key"]
            raw_item = wrapper["item"]
            src = self.available_sources[s_key]

            try:
                company = src.map_to_standard_company(raw_item)
                
                # Check for bare minimum identity
                if not company.get("legal_name") and not company.get("trade_name") and not company.get("dba_name"):
                    total_failed_records += 1
                    continue

                successful_normalized += 1

                # Track available fields in this company
                for k, v in company.items():
                    if v not in [None, "", [], {}]:
                        all_fields_available.add(k)
                if isinstance(company.get("address"), dict):
                    for ak, av in company["address"].items():
                        if av not in [None, ""]:
                            all_fields_available.add(f"address.{ak}")

                # Fingerprint & Deduplication
                fingerprint = generate_entity_fingerprint(company)
                if fingerprint in companies_by_fingerprint:
                    duplicates_count += 1
                    self.logger.info(f"Duplicate detected for fingerprint: {fingerprint}. Merging records...")
                    merged = self._merge_company_records(companies_by_fingerprint[fingerprint], company)
                    companies_by_fingerprint[fingerprint] = merged
                else:
                    companies_by_fingerprint[fingerprint] = company

            except Exception as e:
                self.logger.error(f"Error normalizing item from {src.name}: {e}")
                total_failed_records += 1
                error_details.append(f"Normalization error ({src.name}): {str(e)}")

        # Final pass: compute data quality scores
        final_companies = list(companies_by_fingerprint.values())
        for comp in final_companies:
            comp["data_quality_score"] = calculate_data_quality_score(comp)
            comp["confidence_score"] = comp["data_quality_score"]

        # Step 4: Save Standardized JSON & JSONL
        json_file_path = os.path.join(self.processed_dir, f"companies_{timestamp}.json")
        latest_json_path = os.path.join(self.processed_dir, "companies_latest.json")
        
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump(final_companies, f, indent=2, ensure_ascii=False)
        with open(latest_json_path, "w", encoding="utf-8") as f:
            json.dump(final_companies, f, indent=2, ensure_ascii=False)

        # Step 5: Save CSV Export
        csv_file_path = os.path.join(self.export_dir, f"companies_{timestamp}.csv")
        latest_csv_path = os.path.join(self.export_dir, "companies_latest.csv")
        
        flattened_records = []
        for c in final_companies:
            phones_str = "; ".join([p.get("value", "") for p in c.get("phones", [])])
            emails_str = "; ".join([e.get("value", "") for e in c.get("emails", [])])
            sources_str = "; ".join([s.get("source_name", "") for s in c.get("source_records", [])])

            flattened_records.append({
                "company_id": c.get("company_id"),
                "legal_name": c.get("legal_name"),
                "trade_name": c.get("trade_name"),
                "dba_name": c.get("dba_name"),
                "normalized_name": c.get("normalized_name"),
                "company_status": c.get("company_status"),
                "registration_number": c.get("registration_number"),
                "ein": c.get("ein"),
                "uei": c.get("uei"),
                "duns": c.get("duns"),
                "cik": c.get("cik"),
                "industry": c.get("industry"),
                "naics_code": c.get("naics_code"),
                "sic_code": c.get("sic_code"),
                "street": c["address"].get("street"),
                "city": c["address"].get("city"),
                "state": c["address"].get("state"),
                "state_code": c["address"].get("state_code"),
                "zip_code": c["address"].get("zip_code"),
                "latitude": c["address"].get("latitude"),
                "longitude": c["address"].get("longitude"),
                "phone": phones_str,
                "email": emails_str,
                "website": c.get("website"),
                "domain": c.get("domain"),
                "data_quality_score": c.get("data_quality_score"),
                "sources": sources_str
            })

        if flattened_records:
            df = pd.DataFrame(flattened_records)
            df.to_csv(csv_file_path, index=False, encoding="utf-8")
            df.to_csv(latest_csv_path, index=False, encoding="utf-8")
        else:
            # Create empty CSV with headers
            cols = ["company_id", "legal_name", "normalized_name", "state_code", "city", "data_quality_score"]
            pd.DataFrame(columns=cols).to_csv(csv_file_path, index=False)
            pd.DataFrame(columns=cols).to_csv(latest_csv_path, index=False)

        # Determine all missing required fields across schema
        full_required_fields = {
            "company_id", "legal_name", "normalized_name", "entity_type", "company_status",
            "registration_number", "ein", "uei", "duns", "cik", "description",
            "industry", "naics_code", "sic_code", "employee_count", "revenue",
            "address.street", "address.city", "address.state", "address.state_code", "address.zip_code",
            "website", "domain", "phones", "emails", "people", "executives"
        }
        fields_missing = sorted(list(full_required_fields - all_fields_available))

        summary = {
            "number_of_records_collected": len(final_companies),
            "raw_records_fetched": total_collected_raw,
            "sources_used": source_usage_info,
            "collection_method": "API",
            "fields_available": sorted(list(all_fields_available)),
            "fields_missing": fields_missing,
            "number_of_duplicates": duplicates_count,
            "number_of_records_successfully_normalized": successful_normalized,
            "number_of_failed_records": total_failed_records,
            "error_details": error_details,
            "output_file_locations": {
                "raw_data": raw_file_path,
                "standardized_json": json_file_path,
                "latest_json": latest_json_path,
                "csv": csv_file_path,
                "latest_csv": latest_csv_path,
                "logs": os.path.join(self.logs_dir, f"collection_{timestamp}.log")
            }
        }

        self.logger.info(f"Collection complete. Standardized records: {len(final_companies)}, Duplicates merged: {duplicates_count}")
        return summary
