import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class USPipelineSettings:
    # ─── API Keys ────────────────────────────────────────────────────────────
    CENSUS_DATA_API_KEY = os.getenv("CENSUS_DATA_API_KEY", "")
    DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY", "")
    SAM_GOV_API_KEY = os.getenv("SAM_GOV_API_KEY", "")  # optional — public data available without key
    PEOPLEDATALABS_API_KEY = os.getenv("PEOPLEDATALABS_API_KEY", "9b4afc863602036ad087a9674d6071f0531f0f0d9de6d8995d9bdd1d3b5085db")

    # ─── Directories ─────────────────────────────────────────────────────────
    BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
    RAW_DATA_DIR = BASE_DIR / "data" / "raw" / "us"
    OUTPUT_DIR = BASE_DIR / "output" / "us"

    # Channel sub-directories
    API_COMPANIES_DIR = OUTPUT_DIR / "api" / "companies"
    API_PEOPLE_DIR = OUTPUT_DIR / "api" / "people"
    API_LOGS_DIR = OUTPUT_DIR / "api" / "logs"
    API_REPORTS_DIR = OUTPUT_DIR / "api" / "reports"

    # ─── Pipeline Behaviour ───────────────────────────────────────────────────
    ENABLE_PERSONAL_CONTACT_FIELDS = True
    DEFAULT_BATCH_SIZE = 500
    MAX_RECORDS_PER_SOURCE = 10_000
    EMAIL_VERIFY_LIVE_SMTP = False          # Set True for live SMTP probing
    DEDUP_BLOCK_SIZE = 1_000               # Max block size for fuzzy dedup

    # ─── Create directories on import ────────────────────────────────────────
    for _d in (
        RAW_DATA_DIR, OUTPUT_DIR,
        API_COMPANIES_DIR, API_PEOPLE_DIR,
        API_LOGS_DIR, API_REPORTS_DIR,
    ):
        _d.mkdir(parents=True, exist_ok=True)


settings = USPipelineSettings()
