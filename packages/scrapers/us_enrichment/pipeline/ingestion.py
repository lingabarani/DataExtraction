"""
US B2B Apollo.io-Style Ingestion Pipeline Orchestrator.
Mirrors the Mexico IngestionPipeline exactly in structure and output.

Sources: SEC EDGAR, SAM.gov, USASpending, OpenCorporates, ProPublica 990, Census CBP
Output: us_companies.json/xlsx + us_people.json/xlsx + us_leads_by_industry.xlsx
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..connectors import (
    sam_gov_client, edgar_client, propublica_client,
    census_cbp_client, usaspending_client, opencorporates_client,
)
from ..models.company import USCanonicalCompany
from ..models.person import USDecisionMaker
from ..pipeline.deduplication import us_deduplication_engine, generate_us_company_id
from ..pipeline.merger import us_merge_engine
from ..pipeline.person_enrichment import us_person_enrichment_engine
from ..pipeline.quality import calculate_data_quality_score
from ..pipeline.validation import validate_company, validate_person, get_company_validation_flags, get_person_validation_flags
from ..storage.output import us_output_manager
from ..utils.logging import logger, get_pipeline_logger

# Industry classification (12 categories — matches Mexico)
INDUSTRY_TAXONOMY = {
    "Technology & Software":     ["541511", "541512", "541519", "334111", "517311", "518210", "519130"],
    "Financial Services":        ["522110", "522120", "523110", "523120", "524113", "524126", "525910"],
    "Healthcare & Pharma":       ["621111", "622110", "622210", "325412", "325411", "339113", "621610"],
    "Manufacturing":             ["331", "332", "333", "334", "335", "336", "337", "311", "312", "313"],
    "Logistics & Transport":     ["481111", "482111", "484121", "484122", "491110", "492110", "488510"],
    "Retail & Consumer":         ["441110", "442110", "443141", "444110", "445110", "446110", "452210"],
    "Professional Services":     ["541611", "541612", "541820", "541330", "561320", "611430", "721110"],
    "Energy & Mining":           ["211120", "212111", "213112", "221111", "221121", "221210", "486110"],
    "Construction & Real Estate":["236210", "236220", "237110", "238220", "531110", "531120", "531311"],
    "Agriculture & Food":        ["111110", "111140", "112111", "311111", "311812", "311999", "312120"],
    "Media & Entertainment":     ["512110", "515120", "519110", "711110", "711211", "712110", "713940"],
    "Nonprofit & Education":     ["611110", "611310", "813110", "813211", "813319", "813410", "813990"],
}


def classify_industry(company: USCanonicalCompany) -> str:
    """Classify a company into one of 12 industry categories."""
    naics = company.naics_code or ""
    sic = company.sic_code or ""

    for category, codes in INDUSTRY_TAXONOMY.items():
        for code in codes:
            if naics.startswith(code):
                return category

    # SIC-based fallback
    if sic:
        try:
            sic_int = int(sic)
            if 100 <= sic_int <= 999:
                return "Agriculture & Food"
            if 1000 <= sic_int <= 1499:
                return "Energy & Mining"
            if 1500 <= sic_int <= 1799:
                return "Construction & Real Estate"
            if 2000 <= sic_int <= 3999:
                return "Manufacturing"
            if 4000 <= sic_int <= 4999:
                return "Logistics & Transport"
            if 5000 <= sic_int <= 5999:
                return "Retail & Consumer"
            if 6000 <= sic_int <= 6999:
                return "Financial Services"
            if 7000 <= sic_int <= 7379:
                return "Technology & Software"
            if 7380 <= sic_int <= 8099:
                return "Professional Services"
            if 8000 <= sic_int <= 8099:
                return "Healthcare & Pharma"
            if 8200 <= sic_int <= 8299:
                return "Nonprofit & Education"
            if 7900 <= sic_int <= 7999:
                return "Media & Entertainment"
        except (ValueError, TypeError):
            pass

    # Text-based fallback
    industry_text = (company.industry or "").lower()
    for category in INDUSTRY_TAXONOMY.keys():
        if category.split("&")[0].strip().lower() in industry_text:
            return category

    return "Professional Services"


class USIngestionPipeline:
    """
    US B2B Apollo.io-Style Pipeline Orchestrator.
    Ingests all US open-data sources, deduplicates, merges, enriches executives,
    and exports to XLSX/CSV/JSON — same output format as Mexico pipeline.
    """

    def __init__(self):
        self.dedup = us_deduplication_engine
        self.merger = us_merge_engine
        self.person_engine = us_person_enrichment_engine
        self.output = us_output_manager

    # ─────────────────────────────────────────────────────────────────────────
    # SAM.gov Ingestion
    # ─────────────────────────────────────────────────────────────────────────
    def ingest_sam_gov(
        self,
        naics_codes: Optional[List[str]] = None,
        states: Optional[List[str]] = None,
        max_per_naics: int = 200,
    ) -> List[USCanonicalCompany]:
        """Ingest company + POC data from SAM.gov federal vendor registry."""
        log = get_pipeline_logger("sam_gov")
        log.info("Starting SAM.gov ingestion")
        all_companies = []

        target_naics = naics_codes or [
            "541511", "541512", "541611", "238220", "541330",
            "611430", "517311", "522110", "621111", "236220",
        ]
        target_states = states or [None]  # None = all states

        for naics in target_naics:
            for state in target_states:
                try:
                    payloads = sam_gov_client.fetch_entities(
                        naics_code=naics,
                        state=state,
                        max_records=max_per_naics,
                    )
                    companies = sam_gov_client.normalize_batch(payloads)
                    all_companies.extend(companies)
                    log.info(f"SAM.gov NAICS={naics} state={state}", count=len(companies))
                except Exception as e:
                    log.error(f"SAM.gov fetch error NAICS={naics}: {e}")

        log.info("SAM.gov ingestion complete", total=len(all_companies))
        return all_companies

    # ─────────────────────────────────────────────────────────────────────────
    # SEC EDGAR Ingestion
    # ─────────────────────────────────────────────────────────────────────────
    def ingest_edgar(
        self,
        max_companies: int = 2000,
        fetch_submissions: bool = False,
    ) -> List[USCanonicalCompany]:
        """Ingest public company data from SEC EDGAR."""
        log = get_pipeline_logger("edgar")
        log.info("Starting SEC EDGAR ingestion", max_companies=max_companies)
        try:
            ticker_payloads = edgar_client.fetch_company_tickers(max_companies=max_companies)
            companies = edgar_client.normalize_batch(
                ticker_payloads,
                fetch_submissions=fetch_submissions,
            )
            log.info("SEC EDGAR ingestion complete", total=len(companies))
            return companies
        except Exception as e:
            log.error(f"SEC EDGAR ingestion error: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # ProPublica IRS 990 Ingestion
    # ─────────────────────────────────────────────────────────────────────────
    def ingest_propublica(
        self,
        queries: Optional[List[str]] = None,
        max_per_query: int = 300,
    ) -> List[USCanonicalCompany]:
        """Ingest nonprofit company + executive data from ProPublica IRS 990."""
        log = get_pipeline_logger("propublica")
        log.info("Starting ProPublica 990 ingestion")
        all_companies = []

        search_queries = queries or [
            "university", "hospital", "foundation", "healthcare", "research",
            "community", "services", "technology", "education", "housing",
        ]

        for q in search_queries:
            try:
                payloads = propublica_client.search_nonprofits(
                    query=q,
                    max_records=max_per_query,
                )
                companies = propublica_client.normalize_batch(payloads)
                all_companies.extend(companies)
                log.info(f"ProPublica query='{q}'", count=len(companies))
            except Exception as e:
                log.error(f"ProPublica fetch error query={q}: {e}")

        log.info("ProPublica 990 ingestion complete", total=len(all_companies))
        return all_companies

    # ─────────────────────────────────────────────────────────────────────────
    # USASpending Ingestion
    # ─────────────────────────────────────────────────────────────────────────
    def ingest_usaspending(
        self,
        naics_codes: Optional[List[str]] = None,
        max_per_naics: int = 200,
    ) -> List[USCanonicalCompany]:
        """Ingest federal award recipients from USASpending.gov."""
        log = get_pipeline_logger("usaspending")
        log.info("Starting USASpending ingestion")
        all_companies = []

        target_naics = naics_codes or [
            "541511", "541330", "238220", "561320", "541612",
            "336413", "332119", "611430", "921110", "518210",
        ]

        for naics in target_naics:
            try:
                payloads = usaspending_client.fetch_award_recipients(
                    naics_code=naics,
                    max_records=max_per_naics,
                )
                companies = usaspending_client.normalize_batch(payloads)
                all_companies.extend(companies)
                log.info(f"USASpending NAICS={naics}", count=len(companies))
            except Exception as e:
                log.error(f"USASpending fetch error NAICS={naics}: {e}")

        log.info("USASpending ingestion complete", total=len(all_companies))
        return all_companies

    # ─────────────────────────────────────────────────────────────────────────
    # OpenCorporates Ingestion
    # ─────────────────────────────────────────────────────────────────────────
    def ingest_opencorporates(
        self,
        states: Optional[List[str]] = None,
        max_per_state: int = 200,
    ) -> List[USCanonicalCompany]:
        """Ingest state business registrations + officers from OpenCorporates."""
        log = get_pipeline_logger("opencorporates")
        log.info("Starting OpenCorporates ingestion")
        all_companies = []

        target_states = states or [
            "ca", "tx", "ny", "fl", "il", "pa", "oh", "ga", "nc", "mi",
            "nj", "va", "wa", "az", "ma", "tn", "in", "mo", "md", "wi",
        ]

        for state in target_states:
            try:
                payloads = opencorporates_client.search_companies(
                    jurisdiction_code=state,
                    max_records=max_per_state,
                )
                companies = opencorporates_client.normalize_batch(payloads)
                all_companies.extend(companies)
                log.info(f"OpenCorporates state={state}", count=len(companies))
            except Exception as e:
                log.error(f"OpenCorporates fetch error state={state}: {e}")

        log.info("OpenCorporates ingestion complete", total=len(all_companies))
        return all_companies

    # ─────────────────────────────────────────────────────────────────────────
    # CMS NPI Healthcare Ingestion (FORGE Port)
    # ─────────────────────────────────────────────────────────────────────────
    def ingest_npi(self, cities: Optional[List[str]] = None, max_per_city: int = 100) -> List[USCanonicalCompany]:
        """Ingest healthcare business and practitioner data from CMS NPI Registry."""
        from ..connectors.npi_client import npi_client
        log = get_pipeline_logger("npi")
        log.info("Starting CMS NPI Healthcare ingestion")
        all_companies = []
        target_cities = cities or ["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"]
        for city in target_cities:
            try:
                payloads = npi_client.fetch_providers(city=city, max_records=max_per_city)
                companies = npi_client.normalize_batch(payloads)
                all_companies.extend(companies)
                log.info(f"CMS NPI city={city}", count=len(companies))
            except Exception as e:
                log.error(f"CMS NPI fetch error city={city}: {e}")
        log.info("CMS NPI Healthcare ingestion complete", total=len(all_companies))
        return all_companies

    # ─────────────────────────────────────────────────────────────────────────
    # FCC ULS Telecom Ingestion (FORGE Port)
    # ─────────────────────────────────────────────────────────────────────────
    def ingest_fcc_uls(self, keywords: Optional[List[str]] = None, max_per_keyword: int = 100) -> List[USCanonicalCompany]:
        """Ingest telecom and wireless license holders from FCC ULS Registry."""
        from ..connectors.fcc_uls_client import fcc_uls_client
        log = get_pipeline_logger("fcc_uls")
        log.info("Starting FCC ULS Telecom ingestion")
        all_companies = []
        target_keywords = keywords or ["Telecom", "Wireless", "Broadcasting"]
        for kw in target_keywords:
            try:
                payloads = fcc_uls_client.fetch_licenses(searchValue=kw, max_records=max_per_keyword)
                companies = fcc_uls_client.normalize_batch(payloads)
                all_companies.extend(companies)
                log.info(f"FCC ULS keyword={kw}", count=len(companies))
            except Exception as e:
                log.error(f"FCC ULS fetch error keyword={kw}: {e}")
        log.info("FCC ULS Telecom ingestion complete", total=len(all_companies))
        return all_companies

    # ─────────────────────────────────────────────────────────────────────────
    # OpenDirectories 12M+ Business Ingestion (FORGE Port)
    # ─────────────────────────────────────────────────────────────────────────
    def ingest_opendirectories(self, directories: Optional[List[str]] = None, max_per_dir: int = 100) -> List[USCanonicalCompany]:
        """Ingest business & healthcare provider data from OpenDirectories 12M+ Supabase API."""
        from ..connectors.opendirectories_client import opendirectories_client
        log = get_pipeline_logger("opendirectories")
        log.info("Starting OpenDirectories ingestion")
        all_companies = []
        target_dirs = directories or ["us-healthcare", "us-nonprofits", "us-carriers", "us-schools"]
        for d in target_dirs:
            try:
                payloads = opendirectories_client.fetch_businesses(directory=d, max_records=max_per_dir)
                companies = opendirectories_client.normalize_batch(payloads)
                all_companies.extend(companies)
                log.info(f"OpenDirectories directory={d}", count=len(companies))
            except Exception as e:
                log.error(f"OpenDirectories fetch error directory={d}: {e}")
        log.info("OpenDirectories ingestion complete", total=len(all_companies))
        return all_companies

    # ─────────────────────────────────────────────────────────────────────────
    # Full Pipeline
    # ─────────────────────────────────────────────────────────────────────────
    def run(
        self,
        target_records: int = 5000,
        sources: Optional[List[str]] = None,
        dry_run: bool = False,
        export_formats: Optional[List[str]] = None,
        real_data_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Run the full US B2B pipeline:
        1. Ingest from all configured sources
        2. Deduplicate
        3. Merge clusters
        4. Score data quality
        5. Enrich executives (skip enhancement if real_data_only=True)
        6. Export

        Args:
            target_records: Target number of records to ingest
            sources: List of data sources to use
            dry_run: If True, skip export
            export_formats: List of export formats (json, xlsx, csv)
            real_data_only: If True, skip enhancement layer and export only raw data

        Returns metrics dict.
        """
        start_time = time.time()
        run_id = f"us_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        log = get_pipeline_logger("ingestion")
        log.info(f"=== US B2B Pipeline Run {run_id} ===", target=target_records, dry_run=dry_run, real_data_only=real_data_only)

        # Note: OPENDIRECTORIES disabled by default (Supabase endpoint down)
        enabled_sources = sources or ["SEC_EDGAR", "PROPUBLICA_990", "USASPENDING", "CMS_NPI"]
        formats = export_formats or ["json", "xlsx"]

        # ── Step 1: Ingestion ────────────────────────────────────────────────
        all_raw: List[USCanonicalCompany] = []
        per_source = max(target_records // len(enabled_sources), 500)

        if "SAM_GOV" in enabled_sources:
            all_raw.extend(self.ingest_sam_gov(max_per_naics=per_source // 10))

        if "SEC_EDGAR" in enabled_sources:
            all_raw.extend(self.ingest_edgar(max_companies=per_source))

        if "PROPUBLICA_990" in enabled_sources:
            all_raw.extend(self.ingest_propublica(max_per_query=per_source // 10))

        if "USASPENDING" in enabled_sources:
            all_raw.extend(self.ingest_usaspending(max_per_naics=per_source // 10))

        if "OPENCORPORATES" in enabled_sources:
            all_raw.extend(self.ingest_opencorporates(max_per_state=per_source // 20))

        if "CMS_NPI" in enabled_sources:
            all_raw.extend(self.ingest_npi(max_per_city=per_source // 10))

        if "FCC_ULS" in enabled_sources:
            all_raw.extend(self.ingest_fcc_uls(max_per_keyword=per_source // 10))

        if "OPENDIRECTORIES" in enabled_sources:
            all_raw.extend(self.ingest_opendirectories(max_per_dir=per_source // 10))

        log.info("All sources ingested", total_raw=len(all_raw))



        # ── Step 2: Deduplication ────────────────────────────────────────────
        clusters, review_queue, dupe_count = self.dedup.deduplicate(all_raw)
        log.info("Deduplication done", clusters=len(clusters), dupes=dupe_count)

        # ── Step 3: Merge ─────────────────────────────────────────────────────
        canonical: List[USCanonicalCompany] = self.merger.merge_all(clusters)

        # ── Step 4: Quality Scoring ──────────────────────────────────────────
        # When real_data_only=True, skip validation filter to preserve all raw data
        # Validation is too strict and filters out real data with incomplete fields
        if real_data_only:
            # For real data only mode, skip validation and use all merged companies
            valid_companies = canonical
            for company in valid_companies:
                company.data_quality_score = calculate_data_quality_score(company)
                company.industry = company.industry or classify_industry(company)
        else:
            # Standard mode: apply validation filter
            valid_companies = []
            for company in canonical:
                if not validate_company(company):
                    continue
                company.data_quality_score = calculate_data_quality_score(company)
                company.industry = company.industry or classify_industry(company)
                valid_companies.append(company)

        # Cap at target
        final_companies = valid_companies[:target_records]
        log.info("Quality scoring done", valid=len(valid_companies), exported=len(final_companies), real_data_only=real_data_only)

        # ── Step 5: Executive Enrichment ─────────────────────────────────────
        all_people: List[USDecisionMaker] = []
        for company in final_companies:
            try:
                dms = self.person_engine.extract_and_enrich_decision_makers(company)
                company.decision_makers = [dm.to_dict() for dm in dms]
                all_people.extend(dms)
            except Exception as e:
                log.error(f"Person enrichment error for {company.company_id}: {e}")

        log.info("Executive enrichment done", total_people=len(all_people))

        # ── Step 6: Export ───────────────────────────────────────────────────
        elapsed = time.time() - start_time
        
        # Determine file suffix based on real_data_only flag
        file_suffix = "_real_data_only" if real_data_only else ""
        
        # If real_data_only, force JSON-only export for faster processing
        export_formats = ["json"] if real_data_only else formats
        
        metrics = {
            "run_id": run_id,
            "total_raw_ingested": len(all_raw),
            "total_after_dedup": len(canonical),
            "total_valid_companies": len(valid_companies),
            "total_exported_companies": len(final_companies),
            "total_decision_makers": len(all_people),
            "duplicate_records_removed": dupe_count,
            "avg_quality_score": (
                sum(c.data_quality_score for c in final_companies) / len(final_companies)
                if final_companies else 0
            ),
            "elapsed_seconds": round(elapsed, 2),
            "sources_used": enabled_sources,
            "export_formats": export_formats,
            "real_data_only": real_data_only,
            "status": "DRY_RUN" if dry_run else "COMPLETE",
        }

        if not dry_run:
            try:
                # Build filenames with suffix if real_data_only
                companies_filename = f"us_companies{file_suffix}.json"
                people_filename = f"us_people{file_suffix}.json"
                
                if "json" in export_formats:
                    self.output.write_companies_json(final_companies, filename=companies_filename)
                    self.output.write_people_json(all_people, filename=people_filename)
                if "xlsx" in export_formats:
                    self.output.write_companies_xlsx(final_companies)
                    self.output.write_people_xlsx(all_people)
                    self.output.write_industry_report(final_companies, all_people)
                if "csv" in export_formats:
                    self.output.write_companies_csv(final_companies)
                    self.output.write_people_csv(all_people)
                log.info("Exports complete", formats=export_formats, suffix=file_suffix)
            except Exception as e:
                log.error(f"Export error: {e}")
                metrics["export_error"] = str(e)

        log.info(
            "=== US B2B Pipeline Complete ===",
            companies=len(final_companies),
            people=len(all_people),
            elapsed=f"{elapsed:.1f}s",
        )

        return metrics


us_ingestion_pipeline = USIngestionPipeline()
