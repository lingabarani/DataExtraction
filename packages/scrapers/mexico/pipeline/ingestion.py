"""
Pipeline Orchestrator for Mexico B2B Open-Data Ingestion & Decision-Maker Enrichment.
Implements completely separated API Ingestion, Public-Directory Scraping, and Optional Combined Golden Merging.
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from ..config.sources import sources_registry, SourceConfig
from ..connectors import get_connector
from ..models.company import CanonicalCompany
from ..models.person import DecisionMaker
from .deduplication import deduplication_engine
from .merger import merge_engine
from .person_enrichment import person_enrichment_engine
from .validation import validate_company, validate_person, get_company_validation_flags, get_person_validation_flags
from .quality import calculate_data_quality_score
from ..storage.output import (
    api_output_manager,
    scraping_output_manager,
    combined_output_manager,
    output_manager,
)
from ..utils.logging import logger, get_channel_logger


class IngestionPipeline:
    """
    Main pipeline orchestrator for ingesting, validating, resolving, merging,
    and enriching Mexican business & executive decision-maker data with physical API / Scraping separation.
    """

    def __init__(self):
        self.sources_registry = sources_registry
        self.dedup_engine = deduplication_engine
        self.merger = merge_engine
        self.person_engine = person_enrichment_engine
        self.api_output = api_output_manager
        self.scraping_output = scraping_output_manager
        self.combined_output = combined_output_manager
        self.general_output = output_manager

    def run_api_pipeline(
        self,
        source_keys: Optional[List[str]] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        sample: bool = False,
        verify_emails: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes the API Ingestion Pipeline.
        Ingests official government APIs and structured open data catalogs.
        Outputs strictly to output/api/.
        """
        start_time = time.time()
        run_id = f"api_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        api_log = get_channel_logger("api", "ingestion")
        val_log = get_channel_logger("api", "validation")

        effective_limit = 50 if sample and (limit is None or limit > 50) else limit

        api_log.info(f"RUN_START run_id={run_id} channel=api limit={effective_limit} dry_run={dry_run}")
        
        all_api_sources = self.sources_registry.get_api_sources()
        if source_keys and "all" not in [s.lower() for s in source_keys] and "api" not in [s.lower() for s in source_keys]:
            selected_sources = {k: v for k, v in all_api_sources.items() if k.lower() in [s.lower() for s in source_keys]}
        else:
            selected_sources = all_api_sources

        all_valid_records: List[CanonicalCompany] = []
        all_invalid_reports: List[Dict[str, Any]] = []
        source_metrics: Dict[str, Any] = {}
        total_requests = 0
        successful_requests = 0
        failed_requests = 0

        # Stage 1: Ingest each selected API source independently
        for key, config in selected_sources.items():
            src_start = time.time()
            api_log.info(f"API_REQUEST endpoint={config.name} status=CONNECTING")
            total_requests += 1

            try:
                connector = get_connector(key, config)
                valid_recs, invalid_recs = connector.ingest(limit=effective_limit)
                successful_requests += 1

                for r in valid_recs:
                    if r.source_records:
                        r.source_records[0].source_type = "official_api"
                
                all_valid_records.extend(valid_recs)
                all_invalid_reports.extend(invalid_recs)
                
                api_log.info(f"RECORDS_RECEIVED endpoint={config.name} count={len(valid_recs)} invalid={len(invalid_recs)}")

                # Validate records and log
                warning_count = 0
                for r in valid_recs:
                    res = validate_company(r)
                    if res.warnings:
                        warning_count += 1
                        val_log.warn(f"VALIDATION_WARNING record_id={r.company_id} warnings={len(res.warnings)}")

                val_log.info(f"VALIDATION_COMPLETED source={config.name} valid={len(valid_recs)} warnings={warning_count} rejected={len(invalid_recs)}")

                duration = round(time.time() - src_start, 2)
                source_metrics[config.name] = {
                    "status": "SUCCESS",
                    "records_received": len(valid_recs) + len(invalid_recs),
                    "companies": len(valid_recs),
                    "people": 0,
                    "validation_passed": len(valid_recs) - warning_count,
                    "validation_warnings": warning_count,
                    "validation_rejected": len(invalid_recs),
                    "duration_seconds": duration,
                    "error": None,
                }
            except Exception as e:
                failed_requests += 1
                duration = round(time.time() - src_start, 2)
                api_log.error(f"API_REQUEST_FAILED endpoint={config.name} error={str(e)}")
                val_log.error(f"VALIDATION_ABORTED source={config.name} error={str(e)}")
                source_metrics[config.name] = {
                    "status": "FAILED",
                    "records_received": 0,
                    "companies": 0,
                    "people": 0,
                    "validation_passed": 0,
                    "validation_warnings": 0,
                    "validation_rejected": 0,
                    "duration_seconds": duration,
                    "error": str(e),
                }

        # Stage 2: Deduplication & Entity Resolution
        clusters, review_queue, duplicate_count = self.dedup_engine.deduplicate(all_valid_records)
        api_log.info(f"DEDUPLICATION_COMPLETED input={len(all_valid_records)} duplicates={duplicate_count} final={len(clusters)}")

        # Stage 3: Source Priority Merging
        merged_companies = self.merger.merge_all_clusters(clusters)

        # Stage 4: Decision-Maker Enrichment
        all_decision_makers: List[DecisionMaker] = []
        seen_person_ids = set()
        company_rfc_map = {}
        for company in merged_companies:
            if company.rfc:
                company_rfc_map[company.company_id] = company.rfc
            executives = self.person_engine.extract_and_enrich_decision_makers(company)
            company.decision_makers = executives
            for dm in executives:
                if dm.person_id not in seen_person_ids:
                    seen_person_ids.add(dm.person_id)
                    all_decision_makers.append(dm)

        # Update per-source people count in metrics
        for dm in all_decision_makers:
            src = dm.source_provenance[0].source if dm.source_provenance else "DENUE"
            if src in source_metrics:
                source_metrics[src]["people"] += 1

        # Stage 5: Quality Scores & Metrics
        total_score = sum(c.data_quality_score for c in merged_companies)
        avg_quality_score = round(total_score / len(merged_companies), 2) if merged_companies else 0.0

        total_duration = round(time.time() - start_time, 2)
        total_received = len(all_valid_records) + len(all_invalid_reports)
        total_warnings = sum(v["validation_warnings"] for v in source_metrics.values())

        summary_data = {
            "run_id": run_id,
            "channel": "api",
            "ingestion_method": "api",
            "started_at": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": total_duration,
            "sources": source_metrics,
            "totals": {
                "companies": len(merged_companies),
                "people": len(all_decision_makers),
                "records_received": total_received,
                "records_rejected": len(all_invalid_reports),
                "records_with_warnings": total_warnings,
                "duplicates_resolved": duplicate_count,
                "average_quality_score": avg_quality_score,
                "request_count": total_requests,
                "successful_requests": successful_requests,
                "failed_requests": failed_requests,
            },
        }

        validation_report = {
            "run_id": run_id,
            "channel": "api",
            "summary_metrics": summary_data["totals"],
            "source_statuses": source_metrics,
            "invalid_records_sample": all_invalid_reports[:50],
        }

        # Stage 6: Write API Output Files
        if not dry_run:
            self.api_output.write_companies(merged_companies)
            self.api_output.write_people(all_decision_makers, company_rfc_map=company_rfc_map)
            self.api_output.write_summary(summary_data)
            self.api_output.write_validation_report(validation_report)

        api_log.info(f"RUN_COMPLETE run_id={run_id} companies={len(merged_companies)} people={len(all_decision_makers)} duration_seconds={total_duration}")

        return {
            "run_id": run_id,
            "category": "api",
            "companies": merged_companies,
            "people": all_decision_makers,
            "metrics": summary_data["totals"],
            "summary": summary_data,
            "validation_report": validation_report,
        }

    def run_scraping_pipeline(
        self,
        source_keys: Optional[List[str]] = None,
        limit: Optional[int] = None,
        dry_run: bool = False,
        sample: bool = False,
        verify_emails: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes the Public-Directory Scraping Pipeline.
        Ingests permitted public business directories & chamber directories.
        Outputs strictly to output/scraping/.
        """
        start_time = time.time()
        run_id = f"scrape_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        scrape_log = get_channel_logger("scraping", "ingestion")
        val_log = get_channel_logger("scraping", "validation")

        effective_limit = 50 if sample and (limit is None or limit > 50) else limit

        scrape_log.info(f"RUN_START run_id={run_id} channel=scraping limit={effective_limit} dry_run={dry_run}")

        all_scraping_sources = self.sources_registry.get_scraping_sources()
        if source_keys and "all" not in [s.lower() for s in source_keys] and "scraping" not in [s.lower() for s in source_keys]:
            selected_sources = {k: v for k, v in all_scraping_sources.items() if k.lower() in [s.lower() for s in source_keys]}
        else:
            selected_sources = all_scraping_sources

        all_valid_records: List[CanonicalCompany] = []
        all_invalid_reports: List[Dict[str, Any]] = []
        source_metrics: Dict[str, Any] = {}
        total_pages = 0
        successful_pages = 0
        failed_pages = 0

        # Stage 1: Ingest each public directory source
        for key, config in selected_sources.items():
            src_start = time.time()
            scrape_log.info(f"PAGE_REQUEST directory={config.name} status=200")
            total_pages += 1

            try:
                connector = get_connector(key, config)
                valid_recs, invalid_recs = connector.ingest(limit=effective_limit)
                successful_pages += 1

                for r in valid_recs:
                    if r.source_records:
                        r.source_records[0].source_type = "public_directory"

                all_valid_records.extend(valid_recs)
                all_invalid_reports.extend(invalid_recs)

                scrape_log.info(f"EXTRACTION_COMPLETED directory={config.name} companies={len(valid_recs)} invalid={len(invalid_recs)}")

                # Validate records and log
                warning_count = 0
                for r in valid_recs:
                    res = validate_company(r)
                    if res.warnings:
                        warning_count += 1
                        val_log.warn(f"VALIDATION_WARNING record_id={r.company_id} warnings={len(res.warnings)}")

                val_log.info(f"VALIDATION_COMPLETED directory={config.name} valid={len(valid_recs)} warnings={warning_count} rejected={len(invalid_recs)}")

                duration = round(time.time() - src_start, 2)
                source_metrics[config.name] = {
                    "status": "SUCCESS",
                    "records_received": len(valid_recs) + len(invalid_recs),
                    "companies": len(valid_recs),
                    "people": 0,
                    "validation_passed": len(valid_recs) - warning_count,
                    "validation_warnings": warning_count,
                    "validation_rejected": len(invalid_recs),
                    "duration_seconds": duration,
                    "error": None,
                }
            except Exception as e:
                failed_pages += 1
                duration = round(time.time() - src_start, 2)
                scrape_log.error(f"SCRAPING_FAILED directory={config.name} error={str(e)}")
                val_log.error(f"VALIDATION_ABORTED directory={config.name} error={str(e)}")
                source_metrics[config.name] = {
                    "status": "FAILED",
                    "records_received": 0,
                    "companies": 0,
                    "people": 0,
                    "validation_passed": 0,
                    "validation_warnings": 0,
                    "validation_rejected": 0,
                    "duration_seconds": duration,
                    "error": str(e),
                }

        # Stage 2: Deduplication & Entity Resolution
        clusters, review_queue, duplicate_count = self.dedup_engine.deduplicate(all_valid_records)
        scrape_log.info(f"DEDUPLICATION_COMPLETED input={len(all_valid_records)} duplicates={duplicate_count} final={len(clusters)}")

        # Stage 3: Merging
        merged_companies = self.merger.merge_all_clusters(clusters)

        # Stage 4: Decision-Maker Enrichment
        all_decision_makers: List[DecisionMaker] = []
        seen_person_ids = set()
        company_rfc_map = {}
        for company in merged_companies:
            if company.rfc:
                company_rfc_map[company.company_id] = company.rfc
            executives = self.person_engine.extract_and_enrich_decision_makers(company)
            company.decision_makers = executives
            for dm in executives:
                if dm.person_id not in seen_person_ids:
                    seen_person_ids.add(dm.person_id)
                    all_decision_makers.append(dm)

        # Update per-source people count in metrics
        for dm in all_decision_makers:
            src = dm.source_provenance[0].source if dm.source_provenance else "CANACINTRA"
            if src in source_metrics:
                source_metrics[src]["people"] += 1

        # Stage 5: Quality Scores & Metrics
        total_score = sum(c.data_quality_score for c in merged_companies)
        avg_quality_score = round(total_score / len(merged_companies), 2) if merged_companies else 0.0

        total_duration = round(time.time() - start_time, 2)
        total_received = len(all_valid_records) + len(all_invalid_reports)
        total_warnings = sum(v["validation_warnings"] for v in source_metrics.values())

        summary_data = {
            "run_id": run_id,
            "channel": "scraping",
            "ingestion_method": "scraping",
            "started_at": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": total_duration,
            "sources": source_metrics,
            "totals": {
                "companies": len(merged_companies),
                "people": len(all_decision_makers),
                "records_received": total_received,
                "records_rejected": len(all_invalid_reports),
                "records_with_warnings": total_warnings,
                "duplicates_resolved": duplicate_count,
                "average_quality_score": avg_quality_score,
                "pages_visited": total_pages,
                "successful_pages": successful_pages,
                "failed_pages": failed_pages,
            },
        }

        validation_report = {
            "run_id": run_id,
            "channel": "scraping",
            "summary_metrics": summary_data["totals"],
            "source_statuses": source_metrics,
            "invalid_records_sample": all_invalid_reports[:50],
        }

        # Stage 6: Write Scraping Output Files
        if not dry_run:
            self.scraping_output.write_companies(merged_companies)
            self.scraping_output.write_people(all_decision_makers, company_rfc_map=company_rfc_map)
            self.scraping_output.write_summary(summary_data)
            self.scraping_output.write_validation_report(validation_report)

        scrape_log.info(f"RUN_COMPLETE run_id={run_id} companies={len(merged_companies)} people={len(all_decision_makers)} duration_seconds={total_duration}")

        return {
            "run_id": run_id,
            "category": "scraping",
            "companies": merged_companies,
            "people": all_decision_makers,
            "metrics": summary_data["totals"],
            "summary": summary_data,
            "validation_report": validation_report,
        }

    def run_combined_pipeline(
        self,
        api_companies: List[CanonicalCompany],
        scraped_companies: List[CanonicalCompany],
        api_people: List[DecisionMaker],
        scraped_people: List[DecisionMaker],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes the Combined Golden Entity Resolution stage.
        Combines independent API and Scraped datasets into Golden Profiles while preserving full source provenance.
        Outputs strictly to output/combined/.
        """
        start_time = time.time()
        logger.info(
            "Starting Combined Golden Entity Resolution",
            api_companies=len(api_companies),
            scraped_companies=len(scraped_companies),
        )

        # Combine all companies for cross-source entity resolution
        all_companies = api_companies + scraped_companies
        clusters, review_queue, duplicate_count = self.dedup_engine.deduplicate(all_companies)
        golden_companies = self.merger.merge_all_clusters(clusters)

        # Combine people
        all_people_combined: List[DecisionMaker] = []
        seen_people = set()
        for p in api_people + scraped_people:
            pkey = f"{p.company_id}_{p.full_name}"
            if pkey not in seen_people:
                seen_people.add(pkey)
                all_people_combined.append(p)

        total_score = sum(c.data_quality_score for c in golden_companies)
        avg_quality_score = round(total_score / len(golden_companies), 2) if golden_companies else 0.0

        total_duration = round(time.time() - start_time, 2)

        summary_data = {
            "combined_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": total_duration,
            "total_api_companies": len(api_companies),
            "total_scraped_companies": len(scraped_companies),
            "total_api_people": len(api_people),
            "total_scraped_people": len(scraped_people),
            "cross_source_duplicates": duplicate_count,
            "golden_company_profiles": len(golden_companies),
            "final_unique_companies": len(golden_companies),
            "final_unique_people": len(all_people_combined),
            "average_quality_score": avg_quality_score,
            "review_queue_candidates": len(review_queue),
        }

        if not dry_run:
            self.combined_output.write_companies(golden_companies)
            self.combined_output.write_people(all_people_combined)
            self.combined_output.write_summary(summary_data)
            # Also write master combined spreadsheet
            self.general_output.write_combined_master_export(golden_companies)

        logger.info(
            "Combined Golden Entity Resolution Complete",
            golden_companies=len(golden_companies),
            golden_people=len(all_people_combined),
            duplicates=duplicate_count,
        )

        return {
            "golden_companies": golden_companies,
            "golden_people": all_people_combined,
            "summary": summary_data,
        }

    def run(
        self,
        source_keys: Optional[List[str]] = None,
        category: Optional[str] = "all",
        limit: Optional[int] = None,
        dry_run: bool = False,
        combine: bool = False,
        sample: bool = False,
        verify_emails: bool = False,
    ) -> Dict[str, Any]:
        """
        Unified entrypoint supporting API, Scraping, or Combined execution.
        """
        cat_lower = (category or "all").lower()
        # Partition specific source_keys if provided
        api_keys = []
        scraping_keys = []
        if source_keys:
            for k in source_keys:
                src = sources_registry.get_source(k)
                if src:
                    if src.category == "api":
                        api_keys.append(k)
                    elif src.category == "scraping":
                        scraping_keys.append(k)
                elif k.lower() == "api":
                    cat_lower = "api"
                elif k.lower() == "scraping":
                    cat_lower = "scraping"
                elif k.lower() == "all":
                    cat_lower = "all"

        api_results = None
        scraping_results = None
        combined_results = None

        # Execute API Channel if requested or if API keys are specified
        should_run_api = (cat_lower in ("api", "all") and not scraping_keys) or bool(api_keys)
        if should_run_api:
            api_results = self.run_api_pipeline(
                source_keys=api_keys if api_keys else None,
                limit=limit,
                dry_run=dry_run,
                sample=sample,
                verify_emails=verify_emails,
            )

        # Execute Scraping Channel if requested or if Scraping keys are specified
        should_run_scraping = (cat_lower in ("scraping", "all") and not api_keys) or bool(scraping_keys)
        if should_run_scraping:
            scraping_results = self.run_scraping_pipeline(
                source_keys=scraping_keys if scraping_keys else None,
                limit=limit,
                dry_run=dry_run,
                sample=sample,
                verify_emails=verify_emails,
            )

        # Execute Combined Golden Stage if both were run or combine explicitly requested
        if (cat_lower == "all" or combine) and api_results and scraping_results:
            combined_results = self.run_combined_pipeline(
                api_companies=api_results["companies"],
                scraped_companies=scraping_results["companies"],
                api_people=api_results["people"],
                scraped_people=scraping_results["people"],
                dry_run=dry_run,
            )

        # Aggregate metrics and records for backward compatibility
        all_companies_out = []
        if combined_results:
            all_companies_out = combined_results["golden_companies"]
        else:
            if api_results:
                all_companies_out.extend(api_results["companies"])
            if scraping_results:
                all_companies_out.extend(scraping_results["companies"])

        raw_recs = (
            (api_results["metrics"].get("records_received", api_results["metrics"].get("raw_records", 0)) if api_results else 0)
            + (scraping_results["metrics"].get("records_received", scraping_results["metrics"].get("raw_records", 0)) if scraping_results else 0)
        )
        valid_recs = (
            (api_results["metrics"].get("companies", api_results["metrics"].get("valid_records", 0)) if api_results else 0)
            + (scraping_results["metrics"].get("companies", scraping_results["metrics"].get("valid_records", 0)) if scraping_results else 0)
        )
        merged_count = len(all_companies_out)
        avg_q = (
            combined_results["summary"]["average_quality_score"]
            if combined_results
            else (
                api_results["summary"]["totals"]["average_quality_score"]
                if api_results and not scraping_results
                else (
                    scraping_results["summary"]["totals"]["average_quality_score"]
                    if scraping_results and not api_results
                    else (
                        round(
                            (
                                (api_results["summary"]["totals"]["average_quality_score"] if api_results else 0)
                                + (scraping_results["summary"]["totals"]["average_quality_score"] if scraping_results else 0)
                            )
                            / 2,
                            2,
                        )
                    )
                )
            )
        )

        all_people_out = []
        if combined_results:
            all_people_out = combined_results.get("golden_people", [])
        else:
            if api_results:
                all_people_out.extend(api_results.get("people", []))
            if scraping_results:
                all_people_out.extend(scraping_results.get("people", []))

        c_suite_count = sum(1 for p in all_people_out if getattr(p, "seniority_level", "") == "C_SUITE" or (isinstance(p, dict) and p.get("seniority_level") == "C_SUITE"))

        metrics = {
            "total_raw_records": raw_recs,
            "valid_records": valid_recs,
            "merged_records": merged_count,
            "total_decision_makers": len(all_people_out),
            "c_suite_executives": c_suite_count,
            "average_quality_score": avg_q,
            "total_duration_seconds": round(
                (api_results["metrics"].get("duration_seconds", 0) if api_results else 0)
                + (scraping_results["metrics"].get("duration_seconds", 0) if scraping_results else 0),
                2
            ),
        }

        # Write root legacy exports if not dry run
        if not dry_run and all_companies_out:
            self.general_output.write_json(all_companies_out)
            self.general_output.write_csv(all_companies_out)
            self.general_output.write_xlsx(all_companies_out)
            if all_people_out:
                self.general_output.write_people_json(all_people_out)
                self.general_output.write_people_csv(all_people_out)
                self.general_output.write_people_xlsx(all_people_out)
            validation_combined = {}
            source_statuses = {}
            if api_results:
                validation_combined.update(api_results.get("validation_report", {}))
                source_statuses.update(api_results.get("summary", {}).get("sources", {}))
            if scraping_results:
                validation_combined.update(scraping_results.get("validation_report", {}))
                source_statuses.update(scraping_results.get("summary", {}).get("sources", {}))
            self.general_output.write_validation_report({
                "summary_metrics": metrics,
                "source_statuses": source_statuses,
                "reports": validation_combined,
            })
            self.general_output.write_source_status(source_statuses)

        return {
            "api": api_results,
            "scraping": scraping_results,
            "combined": combined_results,
            "metrics": metrics,
            "companies": all_companies_out,
            "people": all_people_out,
        }

pipeline = IngestionPipeline()
