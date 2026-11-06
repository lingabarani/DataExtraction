import requests
import json

sources = [
    ("SF_BUSINESSES", "https://data.sfgov.org/resource/g8m3-pdis.json?$limit=5"),
    ("LA_BUSINESSES", "https://data.lacity.org/resource/6rrh-rzua.json?$limit=5"),
    ("CHICAGO_LICENSES", "https://data.cityofchicago.org/resource/r5kz-chrr.json?$limit=5"),
    ("NY_BUSINESSES", "https://data.ny.gov/resource/mqq6-iqfu.json?$limit=5"),
    ("SEC_EDGAR", "https://www.sec.gov/files/company_tickers.json"),
    ("FDIC_BANKS", "https://banks.data.fdic.gov/api/institutions?limit=5"),
    ("CMS_NPI", "https://npiregistry.cms.hhs.gov/api/?version=2.1&enumeration_type=NPI-2&limit=5&city=San+Francisco&state=CA")
]

headers = {
    "User-Agent": "OneExtraction-Audit/2.0 (compliance@oneextraction.internal)"
}

for name, url in sources:
    try:
        r = requests.get(url, headers=headers, timeout=10)
        status = r.status_code
        data = r.json()
        count = len(data) if isinstance(data, (list, dict)) else 0
        print(f"[{name}] Status: {status}, Count/Keys: {count}")
    except Exception as e:
        print(f"[{name}] FAILED: {e}")

