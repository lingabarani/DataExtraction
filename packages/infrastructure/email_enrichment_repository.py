"""
DataExtraction — Email Enrichment Repository
============================================
Data access layer for email enrichment jobs, discovered results, and audit telemetry.
All database access is parameterized, thread-safe, and connection-pooled.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from packages.infrastructure.db_connector import execute_query, get_db_connection
from packages.infrastructure.structured_logger import get_structured_logger

logger = get_structured_logger("infrastructure.email_repository")


class EmailEnrichmentRepository:
    """Repository handling CRUD operations for email enrichment schemas."""

    @staticmethod
    def create_job(
        job_type: str = "POST_DEDUP_CANONICAL",
        target_table: str = "staging_dataextraction.working_organizations",
        batch_size: int = 500,
        max_concurrency: int = 50,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Creates a new email enrichment job record and returns the generated UUID."""
        job_id = str(uuid.uuid4())
        meta_json = json.dumps(metadata or {})
        query = """
            INSERT INTO staging_dataextraction.email_enrichment_jobs (
                id, job_type, status, target_table, batch_size, max_concurrency,
                execution_metadata, started_at
            ) VALUES (
                %s, %s, 'RUNNING', %s, %s, %s, %s, NOW()
            )
        """
        execute_query(query, (job_id, job_type, target_table, batch_size, max_concurrency, meta_json))
        logger.info("Created email enrichment job %s (type=%s, target=%s)", job_id, job_type, target_table)
        return job_id

    @staticmethod
    def update_job_progress(
        job_id: str,
        processed_delta: int = 0,
        success_delta: int = 0,
        failed_delta: int = 0,
        last_processed_id: Optional[str] = None,
    ) -> None:
        """Atomically increments job progress counters and updates keyset checkpoint."""
        query = """
            UPDATE staging_dataextraction.email_enrichment_jobs
            SET processed_records = processed_records + %s,
                successful_discoveries = successful_discoveries + %s,
                failed_records = failed_records + %s,
                last_processed_id = COALESCE(%s, last_processed_id)
            WHERE id = %s
        """
        execute_query(query, (processed_delta, success_delta, failed_delta, last_processed_id, job_id))

    @staticmethod
    def complete_job(job_id: str, error_message: Optional[str] = None) -> None:
        """Marks a job as COMPLETED or FAILED."""
        status = "FAILED" if error_message else "COMPLETED"
        query = """
            UPDATE staging_dataextraction.email_enrichment_jobs
            SET status = %s,
                error_message = %s,
                completed_at = NOW()
            WHERE id = %s
        """
        execute_query(query, (status, error_message, job_id))
        logger.info("Completed email enrichment job %s with status=%s", job_id, status)

    @staticmethod
    def get_pending_canonical_companies(
        last_id: Optional[str] = None,
        limit: int = 500,
        target_table: str = "staging_dataextraction.working_organizations",
    ) -> List[Dict[str, Any]]:
        """
        Fetches canonical organizations requiring email discovery using keyset pagination.
        Sprint 2: Reads from staging_dataextraction.working_organizations where
        email_verification_status = 'PENDING'.
        """
        last_val = last_id or ""
        if "working_organizations" in target_table:
            query = """
                SELECT org_id AS id, COALESCE(display_name, legal_name, 'Commercial Entity') AS name,
                       website, primary_domain AS domain
                FROM staging_dataextraction.working_organizations
                WHERE (email_verification_status = 'PENDING' OR email_verification_status IS NULL)
                  AND org_id > %s
                ORDER BY org_id ASC
                LIMIT %s
            """
            rows = execute_query(query, (last_val, limit))
        else:
            query = """
                SELECT id, name, website, domain
                FROM companies
                WHERE website IS NOT NULL 
                  AND website != ''
                  AND (email IS NULL OR email = '')
                  AND id > %s
                ORDER BY id ASC
                LIMIT %s
            """
            rows = execute_query(query, (last_val, limit))

        return [
            {
                "id": str(r[0]),
                "name": r[1],
                "website": r[2] or (f"https://{r[3]}" if r[3] else ""),
                "domain": r[3] or "",
            }
            for r in rows
        ]

    @staticmethod
    def save_enrichment_result(
        company_id: str,
        domain: str,
        primary_email: Optional[str],
        all_emails: List[str],
        discovery_source: str,
        deliverability_status: str,
        confidence_score: float,
        is_catchall: bool = False,
        tech_stack: Optional[List[str]] = None,
        cms_detected: Optional[str] = None,
        ssl_valid: Optional[bool] = None,
        site_speed_ms: Optional[int] = None,
        http_status_code: Optional[int] = None,
        job_id: Optional[str] = None,
    ) -> None:
        """
        Persists an enrichment result and updates the canonical company record.
        Uses upsert on company_id and non-destructive COALESCE on companies.
        """
        emails_json = json.dumps(all_emails)
        tech_json = json.dumps(tech_stack or [])

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # 1. Upsert into staging_dataextraction.email_enrichment_results
                upsert_query = """
                    INSERT INTO staging_dataextraction.email_enrichment_results (
                        job_id, company_id, domain, primary_email, all_emails,
                        discovery_source, deliverability_status, confidence_score,
                        is_catchall, tech_stack, cms_detected, ssl_valid,
                        site_speed_ms, http_status_code, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    ON CONFLICT (company_id) DO UPDATE SET
                        job_id = EXCLUDED.job_id,
                        primary_email = COALESCE(NULLIF(EXCLUDED.primary_email, ''), staging_dataextraction.email_enrichment_results.primary_email),
                        all_emails = EXCLUDED.all_emails,
                        discovery_source = EXCLUDED.discovery_source,
                        deliverability_status = EXCLUDED.deliverability_status,
                        confidence_score = EXCLUDED.confidence_score,
                        is_catchall = EXCLUDED.is_catchall,
                        tech_stack = EXCLUDED.tech_stack,
                        cms_detected = EXCLUDED.cms_detected,
                        ssl_valid = EXCLUDED.ssl_valid,
                        site_speed_ms = EXCLUDED.site_speed_ms,
                        http_status_code = EXCLUDED.http_status_code,
                        enrichment_attempts = staging_dataextraction.email_enrichment_results.enrichment_attempts + 1,
                        updated_at = NOW()
                """
                try:
                    cur.execute("SAVEPOINT sp_enrich_res;")
                    cur.execute(
                        upsert_query,
                        (
                            job_id, company_id, domain, primary_email, emails_json,
                            discovery_source, deliverability_status, confidence_score,
                            is_catchall, tech_json, cms_detected, ssl_valid,
                            site_speed_ms, http_status_code
                        ),
                    )
                    cur.execute("RELEASE SAVEPOINT sp_enrich_res;")
                except Exception as enrich_err:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_enrich_res;")
                    logger.debug("email_enrichment_results tracking notice: %s", enrich_err)

                # 2. Sprint 2: Persist mailboxes into staging_dataextraction.working_emails
                candidate_emails = list(all_emails) if all_emails else []
                if primary_email and primary_email not in candidate_emails:
                    candidate_emails.append(primary_email)

                for em in candidate_emails:
                    if not em or "@" not in str(em):
                        continue
                    clean_em = str(em).strip().lower()
                    mb_user = clean_em.split("@")[0]
                    em_dom = clean_em.split("@")[-1]
                    status_for_em = deliverability_status if clean_em == (primary_email or "").lower() else "DISCOVERED"
                    score_for_em = int(confidence_score) if clean_em == (primary_email or "").lower() else 50

                    try:
                        cur.execute("SAVEPOINT sp_work_em;")
                        cur.execute(
                            """
                            INSERT INTO staging_dataextraction.working_emails (
                                org_id, email_address, mailbox_user, email_domain,
                                deliverability_status, confidence_score, is_catchall,
                                discovery_source, smtp_verified_at, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                            ON CONFLICT (org_id, email_address) DO UPDATE SET
                                deliverability_status = EXCLUDED.deliverability_status,
                                confidence_score = EXCLUDED.confidence_score,
                                is_catchall = EXCLUDED.is_catchall,
                                smtp_verified_at = NOW();
                            """,
                            (
                                company_id, clean_em, mb_user, em_dom,
                                status_for_em, score_for_em, is_catchall,
                                discovery_source,
                            )
                        )
                        cur.execute("RELEASE SAVEPOINT sp_work_em;")
                    except Exception as email_err:
                        cur.execute("ROLLBACK TO SAVEPOINT sp_work_em;")
                        logger.debug("Working emails insert notice: %s", email_err)

                # 3. Sprint 2: Update staging_dataextraction.working_organizations
                try:
                    cur.execute("SAVEPOINT sp_work_org;")
                    cur.execute(
                        """
                        UPDATE staging_dataextraction.working_organizations
                        SET email_verification_status = 'COMPLETED',
                            updated_at = NOW()
                        WHERE org_id = %s;
                        """,
                        (company_id,)
                    )
                    cur.execute("RELEASE SAVEPOINT sp_work_org;")
                except Exception as org_err:
                    cur.execute("ROLLBACK TO SAVEPOINT sp_work_org;")
                    logger.debug("Working organizations update notice: %s", org_err)

                # 4. Legacy compatibility update on companies view/table if it exists
                if primary_email and deliverability_status in ("DELIVERABLE", "MX_CONFIRMED", "RISKY"):
                    try:
                        cur.execute("SAVEPOINT sp_comp_upd;")
                        company_update_query = """
                            UPDATE companies
                            SET email = COALESCE(NULLIF(email, ''), %s),
                                emails = CASE 
                                    WHEN emails IS NULL OR emails = '[]'::jsonb THEN %s::jsonb
                                    ELSE emails || %s::jsonb
                                END,
                                updated_at = NOW()
                            WHERE id = %s
                        """
                        cur.execute(company_update_query, (primary_email, emails_json, emails_json, company_id))
                        cur.execute("RELEASE SAVEPOINT sp_comp_upd;")
                    except Exception:
                        cur.execute("ROLLBACK TO SAVEPOINT sp_comp_upd;")

            conn.commit()

    @staticmethod
    def record_audit_probe(
        target_domain: str,
        probe_type: str,
        duration_ms: float,
        is_success: bool,
        probed_email: Optional[str] = None,
        mx_host: Optional[str] = None,
        smtp_code: Optional[int] = None,
        smtp_response: Optional[str] = None,
        error_trace: Optional[str] = None,
        company_id: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> None:
        """Appends a single low-level audit trace for an HTTP or SMTP probe."""
        query = """
            INSERT INTO staging_dataextraction.email_discovery_audit (
                job_id, company_id, target_domain, probed_email, probe_type,
                mx_host, smtp_code, smtp_response, duration_ms, is_success,
                error_trace, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
        """
        execute_query(
            query,
            (
                job_id, company_id, target_domain, probed_email, probe_type,
                mx_host, smtp_code, (smtp_response[:500] if smtp_response else None),
                duration_ms, is_success, (error_trace[:1000] if error_trace else None)
            ),
        )


    @staticmethod
    def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single email enrichment job by ID."""
        query = """
            SELECT id, job_type, status, target_table, batch_size, max_concurrency,
                   total_records, processed_records, successful_discoveries, failed_records,
                   last_processed_id, started_at, completed_at, error_message, execution_metadata
            FROM staging_dataextraction.email_enrichment_jobs
            WHERE id = %s
        """
        rows = execute_query(query, (job_id,))
        if not rows:
            return None
        r = rows[0]
        return {
            "id": str(r[0]),
            "job_type": r[1],
            "status": r[2],
            "target_table": r[3],
            "batch_size": r[4],
            "max_concurrency": r[5],
            "total_records": r[6],
            "processed_records": r[7],
            "successful_discoveries": r[8],
            "failed_records": r[9],
            "last_processed_id": r[10],
            "started_at": r[11].isoformat() if r[11] else None,
            "completed_at": r[12].isoformat() if r[12] else None,
            "error_message": r[13],
            "metadata": r[14] if isinstance(r[14], dict) else (json.loads(r[14]) if r[14] else {}),
        }

    @staticmethod
    def get_recent_jobs(limit: int = 50, offset: int = 0, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves paginated list of enrichment jobs."""
        if status_filter:
            query = """
                SELECT id, job_type, status, target_table, batch_size,
                       processed_records, successful_discoveries, failed_records,
                       started_at, completed_at, error_message
                FROM staging_dataextraction.email_enrichment_jobs
                WHERE status = %s
                ORDER BY started_at DESC
                LIMIT %s OFFSET %s
            """
            rows = execute_query(query, (status_filter, limit, offset))
        else:
            query = """
                SELECT id, job_type, status, target_table, batch_size,
                       processed_records, successful_discoveries, failed_records,
                       started_at, completed_at, error_message
                FROM staging_dataextraction.email_enrichment_jobs
                ORDER BY started_at DESC
                LIMIT %s OFFSET %s
            """
            rows = execute_query(query, (limit, offset))

        return [
            {
                "id": str(r[0]),
                "job_type": r[1],
                "status": r[2],
                "target_table": r[3],
                "batch_size": r[4],
                "processed_records": r[5],
                "successful_discoveries": r[6],
                "failed_records": r[7],
                "started_at": r[8].isoformat() if r[8] else None,
                "completed_at": r[9].isoformat() if r[9] else None,
                "error_message": r[10],
            }
            for r in rows
        ]

    @staticmethod
    def get_audit_for_company(company_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieves audit trail entries for a given company ID."""
        query = """
            SELECT id, job_id, company_id, target_domain, probed_email, probe_type,
                   mx_host, smtp_code, smtp_response, duration_ms, is_success,
                   error_trace, created_at
            FROM staging_dataextraction.email_discovery_audit
            WHERE company_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        rows = execute_query(query, (company_id, limit))
        return [
            {
                "id": str(r[0]),
                "job_id": str(r[1]) if r[1] else None,
                "company_id": str(r[2]) if r[2] else None,
                "target_domain": r[3],
                "probed_email": r[4],
                "probe_type": r[5],
                "mx_host": r[6],
                "smtp_code": r[7],
                "smtp_response": r[8],
                "duration_ms": float(r[9]) if r[9] is not None else 0.0,
                "is_success": bool(r[10]),
                "error_trace": r[11],
                "created_at": r[12].isoformat() if r[12] else None,
            }
            for r in rows
        ]

    @staticmethod
    def get_enrichment_result_by_company_id(company_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves the latest enrichment result for a company."""
        query = """
            SELECT id, job_id, company_id, domain, primary_email, all_emails,
                   discovery_source, deliverability_status, confidence_score,
                   is_catchall, tech_stack, cms_detected, ssl_valid,
                   site_speed_ms, http_status_code, updated_at
            FROM staging_dataextraction.email_enrichment_results
            WHERE company_id = %s
        """
        rows = execute_query(query, (company_id,))
        if not rows:
            return None
        r = rows[0]
        return {
            "id": str(r[0]),
            "job_id": str(r[1]) if r[1] else None,
            "company_id": str(r[2]),
            "domain": r[3],
            "primary_email": r[4],
            "all_emails": r[5] if isinstance(r[5], list) else (json.loads(r[5]) if r[5] else []),
            "discovery_source": r[6],
            "deliverability_status": r[7],
            "confidence_score": float(r[8]) if r[8] is not None else 0.0,
            "is_catchall": bool(r[9]),
            "tech_stack": r[10] if isinstance(r[10], list) else (json.loads(r[10]) if r[10] else []),
            "cms_detected": r[11],
            "ssl_valid": bool(r[12]) if r[12] is not None else None,
            "site_speed_ms": r[13],
            "http_status_code": r[14],
            "updated_at": r[15].isoformat() if r[15] else None,
        }


email_enrichment_repo = EmailEnrichmentRepository()

