import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import requests

from ..schema import build_empty_company_record, build_source_record, build_phone_entry, build_email_entry
from ..normalizer import normalize_company_name, normalize_phone, normalize_state, normalize_zip, normalize_domain
from .base import BaseSource

logger = logging.getLogger("USBusinessCollector")

from ..config import OverpassConfig, default_config
from ..circuit_breaker import EndpointCircuitBreaker


class OverpassTimeoutError(RuntimeError):
    """Raised when an Overpass query encounters persistent HTTP 504 / server timeout across mirrors."""
    pass


# Default Overpass endpoint from central configuration
DEFAULT_OVERPASS_ENDPOINT = default_config.primary_endpoint
FALLBACK_OVERPASS_ENDPOINTS = list(default_config.fallback_endpoints)
CONNECT_TIMEOUT_SEC: int = default_config.connect_timeout_sec
READ_TIMEOUT_SEC: int = default_config.read_timeout_sec


def validate_overpass_response(data: Any) -> Tuple[bool, Optional[str], int]:
    """
    Validates parsed Overpass JSON response.
    Returns (is_valid, error_reason_or_none, element_count).
    Ensures response contains valid 'elements' list and no runtime errors.
    """
    if not isinstance(data, dict):
        return False, "Response payload is not a valid JSON dictionary", 0

    if "elements" not in data or not isinstance(data["elements"], list):
        return False, "Response is missing valid 'elements' list", 0

    # Check for Overpass server runtime errors embedded in remarks
    remark = data.get("remark", "")
    if remark:
        lower_remark = remark.lower()
        if any(err_term in lower_remark for err_term in ["runtime error", "timed out", "out of memory", "error:"]):
            return False, f"Overpass server error in remark: {remark.strip()}", 0

    # Reject responses from incorrect / regional endpoints that lack US data (e.g. timestamp_osm_base == '117166')
    osm3s_ts = data.get("osm3s", {}).get("timestamp_osm_base", "")
    if osm3s_ts == "117166":
        return False, "Rejected empty response from regional/invalid endpoint (osm3s timestamp 117166)", 0

    return True, None, len(data["elements"])


CSV_EXPORT_FIELDS = [
    "osm_id",
    "osm_type",
    "name",
    "brand",
    "operator",
    "description",
    "category_group",
    "osm_key",
    "osm_value",
    "category",
    "subcategory",
    "business_type",
    "addr:housenumber",
    "addr:street",
    "addr:unit",
    "addr:city",
    "addr:state",
    "addr:postcode",
    "addr:country",
    "addr:place",
    "addr:district",
    "latitude",
    "longitude",
    "phone",
    "mobile",
    "email",
    "website",
    "opening_hours",
    "wheelchair",
    "delivery",
    "takeaway",
    "outdoor_seating",
    "payment",
    "cuisine",
    "internet_access",
    "drive_through",
    "parking",
    "capacity",
    "source_name",
    "source_record_id",
    "source_url",
    "collected_at"
]


class OpenStreetMapSource(BaseSource):
    """OpenStreetMap Overpass API connector with robust retries, endpoint fallbacks, and validation."""

    def __init__(
        self,
        endpoints: Optional[List[str]] = None,
        endpoint_url: Optional[str] = None,
        contact_email: Optional[str] = None,
        config: Optional[OverpassConfig] = None,
        circuit_breaker: Optional[EndpointCircuitBreaker] = None,
    ):
        self.config = config or default_config
        target_endpoint = endpoint_url or self.config.primary_endpoint
        email = contact_email or self.config.contact_email
        super().__init__(
            name="OpenStreetMap",
            source_type="OPEN_GEOSPATIAL_DATABASE",
            base_url=target_endpoint,
            rate_limit_delay=self.config.rate_limit_delay_sec
        )
        self.contact_email = email
        
        # Build mirror pool: allow explicit list or use config fallbacks
        pool = list(endpoints) if endpoints else list(self.config.fallback_endpoints)
        if target_endpoint not in pool:
            pool.insert(0, target_endpoint)
        self.fallback_endpoints = pool
        
        self.circuit_breaker = circuit_breaker or EndpointCircuitBreaker(
            endpoints=pool,
            failure_threshold=2,
            cooldown_sec=self.config.circuit_breaker_cooldown_sec
        )
        self.session.headers.update({
            "User-Agent": self.config.user_agent,
            "Accept": "application/json"
        })

    @property
    def endpoint_url(self) -> str:
        """Return the active Overpass endpoint."""
        return self.base_url

    def _switch_endpoint(self, current_endpoint: str) -> str:
        """Rotates to next healthy fallback mirror via the circuit breaker."""
        new_endpoint = self.circuit_breaker.rotate_endpoint()
        self.base_url = new_endpoint
        print(f"[API] Rotated active mirror to {new_endpoint}", flush=True)
        logger.info(f"Rotated active mirror from {current_endpoint} to {new_endpoint}")
        return new_endpoint

    # ─── Core Overpass Query ──────────────────────────────────────────────────

    def query_overpass(
        self,
        query_str: str,
        max_retries: Optional[int] = None,
        timeout: Optional[int] = None,
        backoff_factor: Optional[float] = None,
        connect_timeout: Optional[int] = None,
        read_timeout: Optional[int] = None,
        counters: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Execute an Overpass query with circuit-breaker-managed mirror rotation,
        randomized jittered backoff, Retry-After handling, and response validation.
        """
        retries = max_retries if max_retries is not None else self.config.max_retries
        conn_to = connect_timeout if connect_timeout is not None else self.config.connect_timeout_sec
        read_to = read_timeout if read_timeout is not None else (timeout or self.config.read_timeout_sec)
        backoff = backoff_factor if backoff_factor is not None else self.config.backoff_factor

        request_timeout = (conn_to, read_to)
        current_endpoint = self.circuit_breaker.get_active_endpoint()
        self.base_url = current_endpoint
        total_attempts = retries + 1
        last_error: Optional[str] = None
        has_timeout_error = False

        for attempt in range(1, total_attempts + 1):
            print(f"[API] Mirror={current_endpoint} Attempt={attempt}/{total_attempts}", flush=True)
            logger.info(f"Submitting Overpass request to {current_endpoint} (attempt {attempt}/{total_attempts})")
            self._throttle()

            t0 = time.time()
            try:
                resp = self.session.post(
                    current_endpoint,
                    data={"data": query_str},
                    timeout=request_timeout
                )
                elapsed = round(time.time() - t0, 3)

                # HTTP 429: Rate limited
                if resp.status_code == 429:
                    if counters is not None:
                        counters["count_429"] = counters.get("count_429", 0) + 1
                        counters["retry_count"] = counters.get("retry_count", 0) + 1
                    
                    self.circuit_breaker.record_failure(current_endpoint, status_code=429, error_message="Rate limit 429")
                    retry_after = 0.0
                    retry_header = resp.headers.get("Retry-After")
                    if retry_header:
                        try:
                            retry_after = float(retry_header)
                        except ValueError:
                            retry_after = 0.0
                    
                    jittered = self.circuit_breaker.calculate_jittered_backoff(attempt, base_backoff=backoff)
                    delay = max(jittered, retry_after)
                    last_error = "HTTP 429 (Rate Limit)"
                    print(
                        f"[API] Mirror={current_endpoint} Attempt={attempt}/{total_attempts} "
                        f"Delay={delay:.1f}s (HTTP 429 Rate Limit, Retry-After={retry_after:.1f}s)",
                        flush=True
                    )
                    logger.warning(f"HTTP 429 from {current_endpoint}. Retrying in {delay:.1f}s")
                    current_endpoint = self._switch_endpoint(current_endpoint)
                    if attempt < total_attempts:
                        time.sleep(delay)
                    continue

                # HTTP 502, 503, 504: Gateway/Server error
                if resp.status_code in (502, 503, 504):
                    if counters is not None:
                        if resp.status_code == 504:
                            counters["count_504"] = counters.get("count_504", 0) + 1
                        counters["retry_count"] = counters.get("retry_count", 0) + 1
                    
                    if resp.status_code == 504:
                        has_timeout_error = True
                        
                    self.circuit_breaker.record_failure(
                        current_endpoint,
                        status_code=resp.status_code,
                        error_message=f"HTTP {resp.status_code} Server Error"
                    )
                    delay = self.circuit_breaker.calculate_jittered_backoff(attempt, base_backoff=backoff)
                    last_error = f"HTTP {resp.status_code}"
                    print(
                        f"[API] Mirror={current_endpoint} Attempt={attempt}/{total_attempts} "
                        f"Delay={delay:.1f}s (HTTP {resp.status_code} Server Error)",
                        flush=True
                    )
                    logger.warning(f"HTTP {resp.status_code} from {current_endpoint}. Retrying in {delay:.1f}s")
                    current_endpoint = self._switch_endpoint(current_endpoint)
                    if attempt < total_attempts:
                        time.sleep(delay)
                    continue

                # Any other non-200 HTTP code
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
                    if counters is not None:
                        counters["retry_count"] = counters.get("retry_count", 0) + 1
                    
                    self.circuit_breaker.record_failure(current_endpoint, status_code=resp.status_code, error_message=last_error)
                    delay = self.circuit_breaker.calculate_jittered_backoff(attempt, base_backoff=backoff)
                    print(
                        f"[API] Mirror={current_endpoint} Attempt={attempt}/{total_attempts} "
                        f"Delay={delay:.1f}s ({last_error})",
                        flush=True
                    )
                    current_endpoint = self._switch_endpoint(current_endpoint)
                    if attempt < total_attempts:
                        time.sleep(delay)
                    continue

                # HTTP 200: Parse and validate JSON
                try:
                    data = resp.json()
                except Exception as json_err:
                    last_error = f"JSON decode error: {json_err}"
                    if counters is not None:
                        counters["retry_count"] = counters.get("retry_count", 0) + 1
                    delay = self.circuit_breaker.calculate_jittered_backoff(attempt, base_backoff=backoff)
                    print(
                        f"[API] Mirror={current_endpoint} Attempt={attempt}/{total_attempts} "
                        f"Delay={delay:.1f}s (HTTP 200 but failed to parse JSON: {json_err})",
                        flush=True
                    )
                    current_endpoint = self._switch_endpoint(current_endpoint)
                    if attempt < total_attempts:
                        time.sleep(delay)
                    continue

                is_valid, validation_err, elem_count = validate_overpass_response(data)
                if not is_valid:
                    last_error = f"Invalid response: {validation_err}"
                    if counters is not None:
                        counters["retry_count"] = counters.get("retry_count", 0) + 1
                    
                    if validation_err and "timed out" in validation_err.lower():
                        has_timeout_error = True

                    self.circuit_breaker.record_failure(
                        current_endpoint,
                        status_code=504 if has_timeout_error else 500,
                        error_message=validation_err
                    )
                    delay = self.circuit_breaker.calculate_jittered_backoff(attempt, base_backoff=backoff)
                    print(
                        f"[API] Mirror={current_endpoint} Attempt={attempt}/{total_attempts} "
                        f"Delay={delay:.1f}s ({last_error})",
                        flush=True
                    )
                    current_endpoint = self._switch_endpoint(current_endpoint)
                    if attempt < total_attempts:
                        time.sleep(delay)
                    continue

                # Valid response confirmed!
                self.circuit_breaker.record_success(current_endpoint)
                print(f"[RESPONSE] HTTP=200 Elements={elem_count} Time={elapsed:.2f}s", flush=True)
                logger.info(f"Query succeeded on {current_endpoint}: HTTP 200, {elem_count} elements in {elapsed:.2f}s")
                return data

            except (requests.exceptions.Timeout, requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
                last_error = f"Timeout: {e}"
                has_timeout_error = True
                if counters is not None:
                    counters["count_timeout"] = counters.get("count_timeout", 0) + 1
                    counters["retry_count"] = counters.get("retry_count", 0) + 1
                
                self.circuit_breaker.record_failure(current_endpoint, status_code=504, error_message=str(e))
                delay = self.circuit_breaker.calculate_jittered_backoff(attempt, base_backoff=backoff)
                print(
                    f"[API] Mirror={current_endpoint} Attempt={attempt}/{total_attempts} "
                    f"Delay={delay:.1f}s (Timeout error: {e})",
                    flush=True
                )
                logger.warning(f"Timeout on {current_endpoint} (attempt {attempt}): {e}")
                current_endpoint = self._switch_endpoint(current_endpoint)
                if attempt < total_attempts:
                    time.sleep(delay)

            except (requests.exceptions.ConnectionError, requests.exceptions.RequestException) as e:
                last_error = f"Network/Connection error: {e}"
                if counters is not None:
                    counters["retry_count"] = counters.get("retry_count", 0) + 1
                
                self.circuit_breaker.record_failure(current_endpoint, status_code=None, error_message=str(e))
                delay = self.circuit_breaker.calculate_jittered_backoff(attempt, base_backoff=backoff)
                print(
                    f"[API] Mirror={current_endpoint} Attempt={attempt}/{total_attempts} "
                    f"Delay={delay:.1f}s (Connection error: {e})",
                    flush=True
                )
                logger.warning(f"ConnectionError on {current_endpoint} (attempt {attempt}): {e}")
                current_endpoint = self._switch_endpoint(current_endpoint)
                if attempt < total_attempts:
                    time.sleep(delay)

        if has_timeout_error:
            raise OverpassTimeoutError(
                f"Overpass query timed out (HTTP 504 / server timeout) after {total_attempts} attempts across mirrors. Last error: {last_error}"
            )
        raise RuntimeError(
            f"Overpass query failed after {total_attempts} attempts across endpoints. Last error: {last_error}"
        )

    def test_connection(
        self,
        bbox: Tuple[float, float, float, float] = (30.65, -88.15, 30.70, -88.10),
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Tests the Overpass API connection using a small query.
        Defaults to a small Alabama bounding box (Mobile, AL area).
        Validates the JSON response and reports element counts.
        """
        s, w, n, e = bbox
        query = f"""[out:json][timeout:25];
(
  node["shop"]({s},{w},{n},{e});
  node["amenity"]({s},{w},{n},{e});
);
out body {limit};"""

        t0 = time.time()
        result: Dict[str, Any] = {
            "endpoint": self.base_url,
            "connected": False,
            "http_status": None,
            "elements_count": 0,
            "example_fields": [],
            "execution_time_sec": 0.0,
            "error": None
        }

        try:
            raw_data = self.query_overpass(query, max_retries=2, timeout=25)
            elapsed = round(time.time() - t0, 3)
            elements = raw_data.get("elements", [])
            result["connected"] = True
            result["http_status"] = 200
            result["elements_count"] = len(elements)
            result["execution_time_sec"] = elapsed
            if elements:
                sample = elements[0]
                fields = list(sample.keys())
                if "tags" in sample and isinstance(sample["tags"], dict):
                    fields.extend([f"tags.{k}" for k in sample["tags"].keys()])
                result["example_fields"] = fields
        except Exception as e:
            result["execution_time_sec"] = round(time.time() - t0, 3)
            result["error"] = str(e)

        return result

    # ─── POI Record Extraction ────────────────────────────────────────────────

    def extract_poi_record(
        self,
        element: Dict[str, Any],
        collected_at: str,
        category_group: Optional[str] = None,
        target_field: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extracts standardized business POI record preserving original OSM information without guessing.
        Missing fields are stored as null (None).
        Full raw OSM tags are preserved in 'raw_tags' (req #13).
        """
        osm_id = element.get("id")
        osm_type = element.get("type", "node")
        tags = element.get("tags", {}) or {}

        # Coordinate extraction (node lat/lon or way/relation center)
        latitude = element.get("lat")
        longitude = element.get("lon")
        if latitude is None and isinstance(element.get("center"), dict):
            latitude = element["center"].get("lat")
            longitude = element["center"].get("lon")

        # Determine primary osm_key and osm_value
        osm_key = None
        osm_value = None
        if target_field and target_field in tags:
            osm_key = target_field
            osm_value = tags[target_field]
        else:
            for candidate_key in [
                "shop", "office", "amenity", "craft", "industrial", "healthcare",
                "tourism", "leisure", "aeroway", "railway", "public_transport",
                "man_made", "club", "landuse", "building"
            ]:
                if candidate_key in tags:
                    osm_key = candidate_key
                    osm_value = tags[candidate_key]
                    break

        category = osm_value if osm_key else None
        subcategory = tags.get("sub_type") or tags.get("type") or None

        website = tags.get("website") or tags.get("contact:website") or tags.get("url") or None
        phone = tags.get("phone") or tags.get("contact:phone") or None
        mobile = tags.get("mobile") or tags.get("contact:mobile") or None
        email = tags.get("email") or tags.get("contact:email") or None

        payment_methods = []
        for k, v in tags.items():
            if k.startswith("payment:") and v in ("yes", "true", "1"):
                payment_methods.append(k.split(":", 1)[1])
        payment_val = ", ".join(payment_methods) if payment_methods else (tags.get("payment") or None)

        record: Dict[str, Any] = {
            "osm_id": osm_id,
            "osm_type": osm_type,
            "name": tags.get("name") or None,
            "brand": tags.get("brand") or None,
            "operator": tags.get("operator") or None,
            "description": tags.get("description") or None,
            "category_group": category_group or "BUSINESS_POI",
            "osm_key": osm_key,
            "osm_value": osm_value,
            "category": category,
            "subcategory": subcategory,
            "business_type": osm_value,
            "addr:housenumber": tags.get("addr:housenumber") or None,
            "addr:street": tags.get("addr:street") or None,
            "addr:unit": tags.get("addr:unit") or None,
            "addr:city": tags.get("addr:city") or None,
            "addr:state": tags.get("addr:state") or None,
            "addr:postcode": tags.get("addr:postcode") or None,
            "addr:country": tags.get("addr:country") or None,
            "addr:place": tags.get("addr:place") or None,
            "addr:district": tags.get("addr:district") or None,
            "latitude": latitude,
            "longitude": longitude,
            "phone": phone,
            "mobile": mobile,
            "email": email,
            "website": website,
            "opening_hours": tags.get("opening_hours") or None,
            "wheelchair": tags.get("wheelchair") or None,
            "delivery": tags.get("delivery") or None,
            "takeaway": tags.get("takeaway") or None,
            "outdoor_seating": tags.get("outdoor_seating") or None,
            "payment": payment_val,
            "cuisine": tags.get("cuisine") or None,
            "internet_access": tags.get("internet_access") or None,
            "drive_through": tags.get("drive_through") or None,
            "parking": tags.get("parking") or None,
            "capacity": tags.get("capacity") or None,
            "source_name": "OpenStreetMap",
            "source_record_id": f"{osm_type}/{osm_id}",
            "source_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
            "collected_at": collected_at,
            "raw_tags": dict(tags)
        }
        return record

    # ─── Legacy Dataset Collector (backward-compat) ───────────────────────────

    def collect_poi_dataset(
        self,
        bbox: Tuple[float, float, float, float] = (30.250, -97.760, 30.280, -97.730),
        area_description: str = "Central Austin, TX (Bounding Box: 30.250, -97.760, 30.280, -97.730)",
        limit: int = 50,
        output_base_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Collects a controlled dataset of US business POIs via Overpass API.
        The `limit` param is kept for API compatibility; all available objects are collected.
        """
        if output_base_dir is None:
            output_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        raw_dir = os.path.join(output_base_dir, "data", "raw")
        processed_dir = os.path.join(output_base_dir, "data", "processed")
        export_dir = os.path.join(output_base_dir, "data", "export")
        logs_dir = os.path.join(output_base_dir, "logs")
        for d in [raw_dir, processed_dir, export_dir, logs_dir]:
            os.makedirs(d, exist_ok=True)

        now_utc = datetime.now(timezone.utc)
        timestamp_str = now_utc.strftime("%Y%m%d_%H%M%S")
        collected_at_iso = now_utc.isoformat()

        log_file_path = os.path.join(logs_dir, f"osm_collector_{timestamp_str}.log")
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(file_handler)
        logger.setLevel(logging.INFO)
        logger.info(f"Starting OSM POI collection for area: {area_description}")

        s, w, n, e = bbox
        query = f"""[out:json][timeout:90];
(
  node["shop"]({s},{w},{n},{e});
  node["office"]({s},{w},{n},{e});
  node["craft"]({s},{w},{n},{e});
  node["industrial"]({s},{w},{n},{e});
  way["shop"]({s},{w},{n},{e});
  way["office"]({s},{w},{n},{e});
  way["craft"]({s},{w},{n},{e});
  way["industrial"]({s},{w},{n},{e});
);
out center tags;"""

        t0 = time.time()
        error_msg = None
        raw_response: Dict[str, Any] = {}
        raw_elements: List[Dict[str, Any]] = []

        try:
            logger.info("Submitting Overpass query...")
            raw_response = self.query_overpass(query)
            raw_elements = raw_response.get("elements", [])
            logger.info(f"Overpass query returned {len(raw_elements)} raw elements")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to query Overpass API: {e}")

        raw_path = os.path.join(raw_dir, f"osm_overpass_raw_{timestamp_str}.json")
        try:
            with open(raw_path, "w", encoding="utf-8") as rf:
                json.dump(raw_response, rf, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving raw response: {e}")

        extracted_records: List[Dict[str, Any]] = []
        seen_keys = set()
        duplicates_removed = 0

        for el in raw_elements:
            osm_id = el.get("id")
            osm_type = el.get("type", "node")
            obj_key = (osm_type, osm_id)
            if obj_key in seen_keys:
                duplicates_removed += 1
                continue
            seen_keys.add(obj_key)
            record = self.extract_poi_record(el, collected_at_iso)
            extracted_records.append(record)

        execution_time = round(time.time() - t0, 3)

        records_with_name = sum(1 for r in extracted_records if r.get("name"))
        records_with_address = sum(
            1 for r in extracted_records
            if any([r.get("addr:housenumber"), r.get("addr:street"), r.get("addr:city"),
                    r.get("addr:state"), r.get("addr:postcode")])
        )
        records_with_phone = sum(1 for r in extracted_records if r.get("phone"))
        records_with_email = sum(1 for r in extracted_records if r.get("email"))
        records_with_website = sum(1 for r in extracted_records if r.get("website"))

        processed_path = os.path.join(processed_dir, f"osm_processed_{timestamp_str}.json")
        processed_latest_path = os.path.join(processed_dir, "osm_processed_latest.json")
        try:
            with open(processed_path, "w", encoding="utf-8") as pf:
                json.dump(extracted_records, pf, indent=2, ensure_ascii=False)
            with open(processed_latest_path, "w", encoding="utf-8") as pf_latest:
                json.dump(extracted_records, pf_latest, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving processed records: {e}")

        export_json_path = os.path.join(export_dir, f"osm_businesses_{timestamp_str}.json")
        try:
            with open(export_json_path, "w", encoding="utf-8") as jf:
                json.dump(extracted_records, jf, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error exporting JSON: {e}")

        export_csv_path = os.path.join(export_dir, f"osm_businesses_{timestamp_str}.csv")
        try:
            with open(export_csv_path, "w", newline="", encoding="utf-8") as cf:
                writer = csv.DictWriter(cf, fieldnames=CSV_EXPORT_FIELDS, extrasaction="ignore")
                writer.writeheader()
                for rec in extracted_records:
                    row = {k: ("" if rec.get(k) is None else rec.get(k)) for k in CSV_EXPORT_FIELDS}
                    writer.writerow(row)
        except Exception as e:
            logger.error(f"Error exporting CSV: {e}")

        logger.removeHandler(file_handler)
        file_handler.close()

        return {
            "geographic_area_used": area_description,
            "records_requested": limit,
            "records_returned": len(raw_elements),
            "records_extracted": len(extracted_records),
            "records_with_business_name": records_with_name,
            "records_with_address": records_with_address,
            "records_with_phone": records_with_phone,
            "records_with_email": records_with_email,
            "records_with_website": records_with_website,
            "duplicates_removed": duplicates_removed,
            "execution_time_sec": execution_time,
            "raw_output_path": raw_path,
            "processed_output_path": processed_path,
            "csv_output_path": export_csv_path,
            "json_output_path": export_json_path,
            "log_path": log_file_path,
            "any_errors": error_msg
        }

    # ─── Search / Map (legacy interface, kept unchanged) ─────────────────────

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
        """
        Queries OpenStreetMap for business POIs matching criteria.
        """
        self._throttle()
        results: List[Dict[str, Any]] = []

        query = f"""[out:json][timeout:25];
(
  node["shop"];
  node["office"];
  node["craft"];
  node["industrial"];
);
out body {limit};"""

        try:
            data = self.query_overpass(query)
            elements = data.get("elements", [])
            for el in elements[:limit]:
                osm_type = el.get("type", "node")
                osm_id = el.get("id", "")
                source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
                tags = el.get("tags", {})
                available_fields = list(el.keys())
                if isinstance(tags, dict):
                    available_fields.extend([f"tags.{k}" for k in tags.keys()])
                results.append({
                    "raw": el,
                    "source_url": source_url,
                    "source_record_id": str(osm_id),
                    "fields_available": available_fields,
                    "collection_method": "API"
                })
        except Exception as e:
            logger.error(f"Error querying OpenStreetMap Overpass API: {e}")

        return results

    def map_to_standard_company(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        data = raw_item["raw"]
        tags = data.get("tags", {}) or {}
        addr_data = data.get("address", {}) or {}
        extra = data.get("extratags", {}) or {}
        source_url = raw_item["source_url"]
        record_id = raw_item["source_record_id"]

        company = build_empty_company_record()

        legal_name = (
            tags.get("operator")
            or tags.get("name")
            or extra.get("operator")
            or data.get("name")
            or ""
        )
        trade_name = tags.get("brand") or tags.get("name") if tags.get("name") != legal_name else ""
        company["legal_name"] = legal_name
        company["trade_name"] = trade_name
        company["normalized_name"] = normalize_company_name(legal_name or trade_name)

        cat = ""
        type_ = ""
        for tag_cat in ["shop", "office", "craft", "industrial"]:
            if tag_cat in tags:
                cat = tag_cat
                type_ = str(tags[tag_cat])
                break
        if not cat:
            cat = data.get("category", "")
            type_ = data.get("type", "")

        company["business_category"] = f"{cat}:{type_}".strip(":")
        company["industry"] = type_.replace("_", " ").title() if type_ else cat.title()

        lat = data.get("lat") or (data.get("center", {}).get("lat") if isinstance(data.get("center"), dict) else None)
        lon = data.get("lon") or (data.get("center", {}).get("lon") if isinstance(data.get("center"), dict) else None)
        try:
            company["address"]["latitude"] = float(lat) if lat else None
            company["address"]["longitude"] = float(lon) if lon else None
        except (ValueError, TypeError):
            pass

        housenumber = tags.get("addr:housenumber") or addr_data.get("house_number", "")
        road = tags.get("addr:street") or addr_data.get("road", "")
        company["address"]["street"] = f"{housenumber} {road}".strip()
        company["address"]["city"] = (
            tags.get("addr:city")
            or addr_data.get("city")
            or addr_data.get("town")
            or addr_data.get("village")
            or ""
        )
        company["address"]["county"] = tags.get("addr:county") or addr_data.get("county", "")

        raw_state = tags.get("addr:state") or addr_data.get("state", "")
        state_name, state_code = normalize_state(raw_state)
        company["address"]["state"] = state_name
        company["address"]["state_code"] = state_code
        company["address"]["zip_code"] = normalize_zip(
            tags.get("addr:postcode") or addr_data.get("postcode", "")
        )

        phone_val = (
            tags.get("phone")
            or tags.get("contact:phone")
            or extra.get("phone")
            or extra.get("contact:phone")
        )
        if phone_val:
            norm_phone = normalize_phone(phone_val)
            if norm_phone:
                company["phones"].append(
                    build_phone_entry(norm_phone, self.name, source_url, "OFFICE")
                )

        email_val = (
            tags.get("email")
            or tags.get("contact:email")
            or extra.get("email")
            or extra.get("contact:email")
        )
        if email_val and "@" in email_val:
            company["emails"].append(
                build_email_entry(email_val.strip(), self.name, source_url, "OFFICE")
            )

        website_val = (
            tags.get("website")
            or tags.get("contact:website")
            or tags.get("url")
            or extra.get("website")
            or extra.get("contact:website")
            or extra.get("url")
        )
        if website_val:
            company["website"] = website_val.strip()
            company["domain"] = normalize_domain(website_val)

        collected = []
        if company["legal_name"]: collected.append("legal_name")
        if company["business_category"]: collected.append("business_category")
        if company["address"]["street"] or company["address"]["city"]: collected.append("address")
        if company["phones"]: collected.append("phones")
        if company["emails"]: collected.append("emails")
        if company["website"]: collected.append("website")
        if company["address"]["latitude"]: collected.append("coordinates")

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


if __name__ == "__main__":
    source = OpenStreetMapSource()
    print("Executing OSM POI collection test...")
    summary = source.collect_poi_dataset()
    print("\n" + "=" * 60)
    print("              OSM COLLECTION SUMMARY")
    print("=" * 60)
    print(f"Records returned           : {summary['records_returned']}")
    print(f"Records extracted          : {summary['records_extracted']}")
    print(f"Execution time             : {summary['execution_time_sec']}s")
    print(f"Any errors                 : {summary['any_errors']}")
    print("=" * 60 + "\n")

