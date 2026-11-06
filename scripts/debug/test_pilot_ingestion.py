import concurrent.futures
import hashlib
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import requests
from psycopg2.extras import execute_values

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from packages.infrastructure.db_connector import get_db_cursor

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("test_pilot")

def fetch_and_insert_page(offset: int):
    t0 = time.time()
    url = "https://data.sfgov.org/resource/g8m3-pdis.json"
    r = requests.get(url, params={"$limit": 1000, "$offset": offset}, timeout=15)
    if r.status_code != 200:
        logger.warning(f"Offset {offset} returned HTTP {r.status_code}")
        return 0
    data = r.json()
    if not data:
        return 0

    now = datetime.now(timezone.utc)
    raw_tuples = []
    staging_tuples = []

    for item in data:
        uid = item.get("uniqueid") or item.get("certificate_number") or str(uuid.uuid4())
        raw_str = json.dumps(item, sort_keys=True)
        p_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
        raw_tuples.append((
            str(uuid.uuid4()),
            "OPEN_DIRECTORIES_SF",
            uid[:255],
            raw_str,
            None,
            p_hash,
            now
        ))

        name = item.get("dba_name") or item.get("ownership_name") or "Unknown"
        legal_name = item.get("ownership_name")
        city = item.get("city") or "San Francisco"
        state = item.get("state") or "CA"
        zip_code = item.get("business_zip")
        naics = item.get("self_reported_naics_code")
        industry = item.get("lic_code_description") or "Commercial Enterprise"

        staging_tuples.append((
            f"sf_{uid}"[:255],
            name[:255],
            (legal_name or name)[:255],
            None,
            None,
            None,
            None,
            city[:100],
            state[:50],
            "CA",
            (zip_code or "")[:20],
            "United States",
            industry[:100],
            (naics or "")[:20],
            None,
            None,
            None,
            None,
            None,
            "OPEN_DIRECTORIES_SF",
            80,
            raw_str,
            False,
            now,
            now
        ))

    with get_db_cursor() as (conn, cur):
        # Raw layer
        execute_values(
            cur,
            """
            INSERT INTO raw_dataextraction.scraper_payloads (
                payload_id, source_name, natural_key, raw_body, s3_url, payload_hash, ingested_at
            ) VALUES %s;
            """,
            raw_tuples,
            page_size=1000
        )
        # Staging layer
        execute_values(
            cur,
            """
            INSERT INTO staging_dataextraction.staging_companies (
                id, name, legal_name, website, domain, email, phone, city, state, state_code,
                zip_code, country, industry, naics_code, ein, cik, employee_min, employee_max,
                employee_band, source, data_quality_score, raw_payload, is_migrated, created_at, updated_at
            ) VALUES %s
            ON CONFLICT (id) DO UPDATE SET updated_at = EXCLUDED.updated_at;
            """,
            staging_tuples,
            page_size=1000
        )
        conn.commit()

    elapsed = round(time.time() - t0, 2)
    logger.info(f"Offset {offset}: Ingested {len(data)} rows in {elapsed}s")
    return len(data)

if __name__ == "__main__":
    t_start = time.time()
    offsets = [1000, 2000, 3000, 4000, 5000]
    total = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(fetch_and_insert_page, offsets)
        total = sum(results)
    print(f"PILOT SUCCESS: {total} records ingested in {round(time.time() - t_start, 2)}s")

