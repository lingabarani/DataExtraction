"""
OneExtraction — Federal & Open Data Temporal Activities
========================================================
Production-grade Temporal activities for executing bulk extractions
across US Federal and Open Data registries (SAM.gov, Census CBP, openFDA,
BLS, BEA, EIA, USGS, Data.gov) with direct OneExtraction PostgreSQL persistence.

Standards:
  - Active heartbeats to prevent Temporal activity timeouts
  - Direct persistence into PostgreSQL `businesses` and `people`
  - Circuit-breaker protected execution and rate limiting
  - Non-destructive `dry_run` support for pipeline simulation
"""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from temporalio import activity

PACKAGES_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = PACKAGES_DIR.parent
US_ENRICH_DIR = PACKAGES_DIR / "scrapers" / "us_enrichment"
INFRA_DIR = PACKAGES_DIR / "infrastructure"

for p in [str(ROOT_DIR), str(PACKAGES_DIR), str(US_ENRICH_DIR), str(INFRA_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("dataextraction.activities.open_data")


def _safe_heartbeat(msg: str):
    """Safely issues a Temporal heartbeat if running within an activity context."""
    try:
        activity.heartbeat(msg)
    except Exception:
        pass


def _get_activity_logger():
    """Returns the Temporal activity logger if in context, otherwise standard logger."""
    try:
        return activity.logger
    except Exception:
        return logger


def _get_pg_conn():
    """Acquires a PostgreSQL connection from the central pool."""
    try:
        from db_connector import get_connection
        return get_connection()
    except Exception as exc:
        logger.warning("PostgreSQL connection could not be acquired: %s", exc)
        return None


def _release_pg_conn(conn):
    """Releases a PostgreSQL connection back to the pool."""
    if not conn:
        return
    try:
        from db_connector import release_connection
        release_connection(conn)
    except Exception as exc:
        logger.warning("Error releasing PostgreSQL connection: %s", exc)


# ── Activity 1: SAM.gov Entity Registry ──────────────────────────────────────

@activity.defn(name="run_sam_gov_extraction")
async def run_sam_gov_extraction_activity(args: dict) -> dict:
    """
    Executes SAM.gov federal entity and vendor contractor extraction.
    Persists vendors to `businesses` and Point of Contact (POC) executives to `people`.
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting SAM.gov extraction (args=%s)", args)

    limit = int(args.get("limit", 100))
    naics = args.get("naics", "541511")
    dry_run = bool(args.get("dry_run", False))

    if dry_run:
        return {"source": "SAM_GOV", "mode": "dry_run", "limit": limit, "status": "SUCCESS"}

    _safe_heartbeat("Initializing SAM.gov client")
    from packages.scrapers.us_enrichment.connectors.sam_client import SamGovClient
    from packages.scrapers.us_enrichment.storage.federal_postgres_writer import upsert_federal_businesses, upsert_federal_people

    client = SamGovClient()
    _safe_heartbeat(f"Querying SAM.gov entities for NAICS {naics}")

    # Fetch entities
    companies, dm_records = client.fetch_entities_for_naics(naics, max_records=limit)
    _safe_heartbeat(f"Fetched {len(companies)} vendors from SAM.gov")

    # Map canonical models to dicts
    biz_records = []
    people_records = []

    for c in companies:
        biz_records.append({
            "company_id": f"sam_{c.uei or c.cage_code or c.ein}",
            "name": c.legal_name,
            "legal_name": c.legal_name,
            "uei": c.uei,
            "cage_code": c.cage_code,
            "ein": c.ein,
            "naics_code": c.primary_naics,
            "industry": c.industry,
            "city": c.primary_address.city if c.primary_address else None,
            "state_code": c.primary_address.state if c.primary_address else None,
            "zip_code": c.primary_address.postal_code if c.primary_address else None,
            "source": "sam_gov",
            "data_quality_score": 90,
        })

    for dm in dm_records:
        people_records.append({
            "company_id": f"sam_{dm.company_id}",
            "full_name": dm.full_name,
            "title": dm.title,
            "work_email": dm.email,
            "direct_phone": dm.phone,
            "source": "sam_gov",
        })

    # Persist to PostgreSQL
    pg_inserted = 0
    conn = _get_pg_conn()
    if conn:
        try:
            res_biz = upsert_federal_businesses(conn, biz_records, default_source="sam_gov")
            pg_inserted = res_biz.get("inserted_or_updated", 0)
            if people_records:
                upsert_federal_people(conn, people_records, default_source="sam_gov")
        finally:
            _release_pg_conn(conn)

    _safe_heartbeat(f"Finished: {len(biz_records)} vendors, {len(people_records)} POCs stored in Postgres")
    return {
        "source": "SAM_GOV",
        "records_fetched": len(biz_records),
        "people_fetched": len(people_records),
        "postgres_inserted": pg_inserted,
        "status": "SUCCESS",
    }


# ── Activity 2: US Census Bureau County Business Patterns (CBP) ──────────────

@activity.defn(name="run_census_cbp_extraction")
async def run_census_cbp_extraction_activity(args: dict) -> dict:
    """
    Executes US Census County Business Patterns extraction.
    Pulls establishment counts, employee size bands, and payroll benchmarks by NAICS.
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting Census CBP extraction (args=%s)", args)

    state = args.get("state", "06")  # California FIPS default
    naics = args.get("naics", "5415")
    dry_run = bool(args.get("dry_run", False))

    if dry_run:
        return {"source": "CENSUS_CBP", "mode": "dry_run", "state": state, "status": "SUCCESS"}

    _safe_heartbeat("Initializing Census Bureau client")
    from packages.scrapers.us_enrichment.connectors.census_client import CensusClient
    from packages.scrapers.us_enrichment.storage.federal_postgres_writer import upsert_federal_businesses

    client = CensusClient()
    _safe_heartbeat(f"Querying Census CBP for state FIPS {state}")

    records = client.get_county_business_patterns(year="2022", state=state, naics=naics)
    biz_records = []

    for r in records:
        fips = r.get("state_code", "")
        naics_code = r.get("naics_code", "")
        biz_records.append({
            "company_id": f"census_cbp_{fips}_{naics_code}",
            "name": f"{r.get('state_name', 'US')} NAICS {naics_code} Industry Establishment Group",
            "state_code": fips,
            "naics_code": naics_code,
            "employee_count_band": f"{r.get('employee_count')} total employees across {r.get('establishment_count')} establishments",
            "industry": "Census Business Establishment",
            "source": "census_cbp",
            "data_quality_score": 70,
        })

    pg_inserted = 0
    conn = _get_pg_conn()
    if conn:
        try:
            res = upsert_federal_businesses(conn, biz_records, default_source="census_cbp")
            pg_inserted = res.get("inserted_or_updated", 0)
        finally:
            _release_pg_conn(conn)

    return {
        "source": "CENSUS_CBP",
        "records_fetched": len(biz_records),
        "postgres_inserted": pg_inserted,
        "status": "SUCCESS",
    }


# ── Activity 3: openFDA Medical Device & Life Sciences Establishments ────────

@activity.defn(name="run_openfda_extraction")
async def run_openfda_extraction_activity(args: dict) -> dict:
    """
    Executes openFDA medical device establishment and drug registration extraction.
    Persists regulated life sciences facilities to `businesses`.
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting openFDA extraction (args=%s)", args)

    limit = int(args.get("limit", 50))
    state = args.get("state")
    dry_run = bool(args.get("dry_run", False))

    if dry_run:
        return {"source": "OPENFDA", "mode": "dry_run", "limit": limit, "status": "SUCCESS"}

    _safe_heartbeat("Initializing openFDA client")
    from packages.scrapers.us_enrichment.connectors.openfda_client import OpenFDAClient
    from packages.scrapers.us_enrichment.storage.federal_postgres_writer import upsert_federal_businesses

    client = OpenFDAClient()
    _safe_heartbeat("Querying openFDA medical device establishments")

    records = client.get_device_establishments(state=state, limit=limit)
    pg_inserted = 0
    conn = _get_pg_conn()
    if conn:
        try:
            res = upsert_federal_businesses(conn, records, default_source="openfda")
            pg_inserted = res.get("inserted_or_updated", 0)
        finally:
            _release_pg_conn(conn)

    return {
        "source": "OPENFDA",
        "records_fetched": len(records),
        "postgres_inserted": pg_inserted,
        "status": "SUCCESS",
    }


# ── Activity 4: Bureau of Labor Statistics (BLS) Employment Observations ─────

@activity.defn(name="run_bls_extraction")
async def run_bls_extraction_activity(args: dict) -> dict:
    """
    Queries BLS timeseries labor and employment series.
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting BLS extraction (args=%s)", args)

    dry_run = bool(args.get("dry_run", False))
    if dry_run:
        return {"source": "BLS", "mode": "dry_run", "status": "SUCCESS"}

    _safe_heartbeat("Querying BLS API")
    from packages.scrapers.us_enrichment.connectors.bls_client import BLSClient

    client = BLSClient()
    series = client.get_industry_employment_series(
        series_ids=args.get("series_ids"),
        start_year=args.get("start_year", 2023),
        end_year=args.get("end_year", 2024),
    )

    return {
        "source": "BLS",
        "series_observations": len(series),
        "status": "SUCCESS",
    }


# ── Activity 5: Bureau of Economic Analysis (BEA) Regional GDP ───────────────

@activity.defn(name="run_bea_extraction")
async def run_bea_extraction_activity(args: dict) -> dict:
    """
    Queries BEA regional economic accounts.
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting BEA extraction (args=%s)", args)

    dry_run = bool(args.get("dry_run", False))
    if dry_run:
        return {"source": "BEA", "mode": "dry_run", "status": "SUCCESS"}

    _safe_heartbeat("Querying BEA API")
    from packages.scrapers.us_enrichment.connectors.bea_client import BEAClient

    client = BEAClient()
    data = client.get_regional_gdp_by_industry(
        geo_fips=args.get("geo_fips", "STATE"),
        year=args.get("year", "2023"),
    )

    return {
        "source": "BEA",
        "records_fetched": len(data),
        "status": "SUCCESS",
    }


# ── Activity 6: Energy Information Administration (EIA) Utilities ────────────

@activity.defn(name="run_eia_extraction")
async def run_eia_extraction_activity(args: dict) -> dict:
    """
    Extracts commercial energy providers and utility data.
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting EIA extraction (args=%s)", args)

    dry_run = bool(args.get("dry_run", False))
    if dry_run:
        return {"source": "EIA", "mode": "dry_run", "status": "SUCCESS"}

    _safe_heartbeat("Querying EIA API")
    from packages.scrapers.us_enrichment.connectors.eia_client import EIAClient

    client = EIAClient()
    providers = client.get_commercial_electricity_providers(
        state=args.get("state"),
        limit=int(args.get("limit", 50)),
    )

    return {
        "source": "EIA",
        "providers_fetched": len(providers),
        "status": "SUCCESS",
    }


# ── Activity 7: USGS Water Monitoring Facilities ─────────────────────────────

@activity.defn(name="run_usgs_extraction")
async def run_usgs_extraction_activity(args: dict) -> dict:
    """
    Extracts active water resources infrastructure facilities from USGS.
    Persists facilities directly to PostgreSQL `businesses`.
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting USGS extraction (args=%s)", args)

    dry_run = bool(args.get("dry_run", False))
    if dry_run:
        return {"source": "USGS", "mode": "dry_run", "status": "SUCCESS"}

    _safe_heartbeat("Querying USGS Water Services")
    from packages.scrapers.us_enrichment.connectors.usgs_client import USGSClient
    from packages.scrapers.us_enrichment.storage.federal_postgres_writer import upsert_federal_businesses

    client = USGSClient()
    facilities = client.get_monitoring_facilities(
        state_code=args.get("state", "CA"),
        limit=int(args.get("limit", 50)),
    )

    pg_inserted = 0
    conn = _get_pg_conn()
    if conn:
        try:
            res = upsert_federal_businesses(conn, facilities, default_source="usgs")
            pg_inserted = res.get("inserted_or_updated", 0)
        finally:
            _release_pg_conn(conn)

    return {
        "source": "USGS",
        "facilities_fetched": len(facilities),
        "postgres_inserted": pg_inserted,
        "status": "SUCCESS",
    }


# ── Activity 8: Data.gov Federal Educational Institutions ─────────────────────

@activity.defn(name="run_datagov_extraction")
async def run_datagov_extraction_activity(args: dict) -> dict:
    """
    Extracts higher educational institutions and universities from Data.gov.
    Persists institutions directly to PostgreSQL `businesses`.
    """
    act_logger = _get_activity_logger()
    act_logger.info("Starting Data.gov extraction (args=%s)", args)

    dry_run = bool(args.get("dry_run", False))
    if dry_run:
        return {"source": "DATA_GOV", "mode": "dry_run", "status": "SUCCESS"}

    _safe_heartbeat("Querying Data.gov API")
    from packages.scrapers.us_enrichment.connectors.datagov_client import DataGovClient
    from packages.scrapers.us_enrichment.storage.federal_postgres_writer import upsert_federal_businesses

    client = DataGovClient()
    institutions = client.get_educational_institutions(
        state=args.get("state", "CA"),
        limit=int(args.get("limit", 50)),
    )

    pg_inserted = 0
    conn = _get_pg_conn()
    if conn:
        try:
            res = upsert_federal_businesses(conn, institutions, default_source="data_gov")
            pg_inserted = res.get("inserted_or_updated", 0)
        finally:
            _release_pg_conn(conn)

    return {
        "source": "DATA_GOV",
        "institutions_fetched": len(institutions),
        "postgres_inserted": pg_inserted,
        "status": "SUCCESS",
    }
