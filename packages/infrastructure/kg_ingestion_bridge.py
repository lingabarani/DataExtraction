"""
DataExtraction — Knowledge Graph Ingestion Bridge
=================================================
Connects extraction pipelines, scrapers, and Temporal workers to the
PostgreSQL 16/18 Knowledge Graph tables and MinIO/S3 Lakehouse storage.

Responsibilities:
  1. Offload raw payload to Lakehouse (MinIO/S3 Parquet) and track in `kg_observation`.
  2. Ingest normalized organizations into `kg_core.organizations`, `organization_aliases`,
     and `organization_domains`.
  3. Ingest persons and career tenure into `kg_core.persons` and `kg_graph.employment_relationships`.
  4. Ingest contact intelligence into `kg_core.contact_emails` and `kg_core.contact_phones`.
  5. Record field-level provenance in `kg_lineage.field_provenance`.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.storage_lakehouse import (
    LakehouseObservationClient,
    lakehouse_client,
)

logger = logging.getLogger("dataextraction.kg.bridge")


class KnowledgeGraphIngestionBridge:
    """
    Enterprise ingestion bridge for writing evidence-backed entities
    into PostgreSQL Knowledge Graph schemas and S3/MinIO Lakehouse.
    """

    def __init__(self, s3_lakehouse: Optional[LakehouseObservationClient] = None):
        self.lakehouse = s3_lakehouse or lakehouse_client

    def persist_raw_observation(
        self,
        conn: Any,
        source_name: str,
        source_record_id: str,
        raw_payload: Any,
        extracted_summary: Optional[Dict[str, Any]] = None,
        observed_entity_type: str = "organization",
        observed_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        1. Writes raw payload to MinIO/S3 Parquet partition.
        2. Inserts metadata reference into `kg_observation.observation_metadata`.
        """
        if observed_at is None:
            observed_at = datetime.now(timezone.utc)

        # 1. Lakehouse Offload
        lake_res = self.lakehouse.write_raw_observation(
            source_name=source_name,
            source_record_id=source_record_id,
            raw_payload=raw_payload,
            observed_at=observed_at,
            metadata={"entity_type": observed_entity_type},
        )

        obs_id = str(uuid.uuid4())
        sha256 = lake_res["payload_hash_sha256"]
        s3_uri = lake_res["lakehouse_s3_uri"]
        summary_json = json.dumps(extracted_summary or {})

        # 2. PostgreSQL Metadata Tracking
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO kg_observation.observation_metadata (
                        observation_id, source_name, source_record_id,
                        observed_entity_type, payload_hash_sha256,
                        lakehouse_s3_uri, extracted_summary, observed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (
                        obs_id,
                        source_name,
                        source_record_id,
                        observed_entity_type,
                        sha256,
                        s3_uri,
                        summary_json,
                        observed_at,
                    ),
                )

        return {
            "observation_id": obs_id,
            "lakehouse_s3_uri": s3_uri,
            "payload_hash_sha256": sha256,
            "byte_size": lake_res["byte_size"],
            "source_name": source_name,
        }

    def ingest_organization(
        self,
        conn: Any,
        org_data: Dict[str, Any],
        source_name: str,
        observation_id: Optional[str] = None,
        authority_weight: float = 0.8,
    ) -> str:
        """
        Ingests a canonical organization into `kg_core.organizations`,
        aliases into `kg_core.organization_aliases`, domains into `kg_core.organization_domains`,
        and contacts into `kg_core.contact_emails` and `kg_core.contact_phones`.
        """
        org_id = org_data.get("org_id") or str(uuid.uuid4())
        jurisdiction = (org_data.get("jurisdiction") or "US").upper()
        if jurisdiction not in ("US", "MX", "CA", "GLOBAL"):
            jurisdiction = "US"

        legal_name = (org_data.get("legal_name") or org_data.get("name") or "Unknown Entity").strip()
        display_name = org_data.get("display_name") or legal_name
        primary_domain = org_data.get("primary_domain") or org_data.get("domain")
        tax_id = org_data.get("statutory_tax_id") or org_data.get("ein") or org_data.get("rfc")
        sec_cik = org_data.get("sec_cik") or org_data.get("cik")
        gleif_lei = org_data.get("gleif_lei") or org_data.get("lei")
        naics_raw = str(org_data.get("primary_industry_naics") or org_data.get("naics_code") or "").strip()
        naics = "".join(c for c in naics_raw if c.isdigit())[:6] or None
        sic_raw = str(org_data.get("primary_industry_sic") or org_data.get("sic_code") or "").strip()
        sic = "".join(c for c in sic_raw if c.isdigit())[:4] or None
        industry = org_data.get("industry") or org_data.get("primary_industry") or "Commercial Enterprise"
        emp_min = org_data.get("employee_count_min")
        emp_max = org_data.get("employee_count_max")
        annual_rev = org_data.get("annual_revenue_usd")
        total_funding = org_data.get("total_funding_usd")
        quality_score = org_data.get("data_quality_score", 80)

        # Apollo.io Extended Attributes
        logo_url = org_data.get("logo_url")
        linkedin_url = org_data.get("linkedin_url")
        social_urls = json.dumps(org_data.get("social_urls") or {}) if isinstance(org_data.get("social_urls"), dict) else org_data.get("social_urls") or "{}"
        keywords = org_data.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        dept_headcount = json.dumps(org_data.get("departmental_headcount") or {}) if isinstance(org_data.get("departmental_headcount"), dict) else org_data.get("departmental_headcount") or "{}"
        latest_funding = org_data.get("latest_funding_stage")
        funding_events = json.dumps(org_data.get("funding_events") or []) if isinstance(org_data.get("funding_events"), list) else org_data.get("funding_events") or "[]"
        ticker = org_data.get("publicly_traded_symbol")
        exchange = org_data.get("publicly_traded_exchange")
        technologies = json.dumps(org_data.get("technologies") or []) if isinstance(org_data.get("technologies"), list) else org_data.get("technologies") or "[]"
        description = org_data.get("short_description")

        with conn.cursor() as cur:
            # 1. Upsert Canonical Organization into Master MDM
            cur.execute(
                """
                INSERT INTO master_dataextraction.organizations (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    statutory_tax_id, sec_cik, gleif_lei, primary_industry_naics,
                    primary_industry_sic, industry, employee_count_min, employee_count_max,
                    annual_revenue_usd, total_funding_usd, data_quality_score,
                    logo_url, linkedin_url, social_urls, keywords, departmental_headcount,
                    latest_funding_stage, funding_events, publicly_traded_symbol,
                    publicly_traded_exchange, technologies, short_description, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s::jsonb, %s, %s::jsonb,
                    %s, %s::jsonb, %s,
                    %s, %s::jsonb, %s, CLOCK_TIMESTAMP()
                )
                ON CONFLICT (org_id, jurisdiction) DO UPDATE SET
                    display_name = COALESCE(EXCLUDED.display_name, master_dataextraction.organizations.display_name),
                    primary_domain = COALESCE(EXCLUDED.primary_domain, master_dataextraction.organizations.primary_domain),
                    statutory_tax_id = COALESCE(EXCLUDED.statutory_tax_id, master_dataextraction.organizations.statutory_tax_id),
                    sec_cik = COALESCE(EXCLUDED.sec_cik, master_dataextraction.organizations.sec_cik),
                    gleif_lei = COALESCE(EXCLUDED.gleif_lei, master_dataextraction.organizations.gleif_lei),
                    primary_industry_naics = COALESCE(EXCLUDED.primary_industry_naics, master_dataextraction.organizations.primary_industry_naics),
                    industry = COALESCE(EXCLUDED.industry, master_dataextraction.organizations.industry),
                    annual_revenue_usd = COALESCE(EXCLUDED.annual_revenue_usd, master_dataextraction.organizations.annual_revenue_usd),
                    total_funding_usd = COALESCE(EXCLUDED.total_funding_usd, master_dataextraction.organizations.total_funding_usd),
                    data_quality_score = GREATEST(EXCLUDED.data_quality_score, master_dataextraction.organizations.data_quality_score),
                    logo_url = COALESCE(EXCLUDED.logo_url, master_dataextraction.organizations.logo_url),
                    linkedin_url = COALESCE(EXCLUDED.linkedin_url, master_dataextraction.organizations.linkedin_url),
                    social_urls = CASE WHEN EXCLUDED.social_urls != '{}'::jsonb THEN EXCLUDED.social_urls ELSE master_dataextraction.organizations.social_urls END,
                    keywords = CASE WHEN cardinality(EXCLUDED.keywords) > 0 THEN EXCLUDED.keywords ELSE master_dataextraction.organizations.keywords END,
                    departmental_headcount = CASE WHEN EXCLUDED.departmental_headcount != '{}'::jsonb THEN EXCLUDED.departmental_headcount ELSE master_dataextraction.organizations.departmental_headcount END,
                    latest_funding_stage = COALESCE(EXCLUDED.latest_funding_stage, master_dataextraction.organizations.latest_funding_stage),
                    funding_events = CASE WHEN EXCLUDED.funding_events != '[]'::jsonb THEN EXCLUDED.funding_events ELSE master_dataextraction.organizations.funding_events END,
                    publicly_traded_symbol = COALESCE(EXCLUDED.publicly_traded_symbol, master_dataextraction.organizations.publicly_traded_symbol),
                    publicly_traded_exchange = COALESCE(EXCLUDED.publicly_traded_exchange, master_dataextraction.organizations.publicly_traded_exchange),
                    technologies = CASE WHEN EXCLUDED.technologies != '[]'::jsonb THEN EXCLUDED.technologies ELSE master_dataextraction.organizations.technologies END,
                    short_description = COALESCE(EXCLUDED.short_description, master_dataextraction.organizations.short_description),
                    updated_at = CLOCK_TIMESTAMP()
                RETURNING org_id;
                """,
                (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    tax_id, sec_cik, gleif_lei, naics, sic, industry, emp_min, emp_max,
                    annual_rev, total_funding, quality_score,
                    logo_url, linkedin_url, social_urls, keywords, dept_headcount,
                    latest_funding, funding_events, ticker,
                    exchange, technologies, description
                ),
            )
            res = cur.fetchone()
            if res:
                org_id = str(res[0])

            # 2. Ingest Organization Aliases (e.g. DBA, trade names, former names)
            aliases = org_data.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            trade_name = org_data.get("trade_name")
            if trade_name and trade_name not in aliases and trade_name != legal_name:
                aliases.append(trade_name)

            for alias in aliases:
                if not alias or not str(alias).strip():
                    continue
                alias_clean = str(alias).strip()
                cur.execute(
                    """
                    INSERT INTO master_dataextraction.organization_aliases (
                        org_id, jurisdiction, alias_name, alias_type, clean_name
                    ) VALUES (%s, %s, %s, 'trade_name', %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (org_id, jurisdiction, alias_clean, alias_clean.lower()),
                )

            # 3. Ingest Organization Domains (Multi-domain topology)
            domains = org_data.get("all_domains") or []
            if primary_domain and primary_domain not in domains:
                domains.append(primary_domain)

            for dom in domains:
                if not dom or not str(dom).strip():
                    continue
                dom_clean = str(dom).strip().lower()
                is_prim = (dom_clean == (primary_domain or "").lower())
                cur.execute(
                    """
                    INSERT INTO master_dataextraction.organization_domains (
                        org_id, jurisdiction, domain_name, is_primary, last_verified_at
                    ) VALUES (%s, %s, %s, %s, CLOCK_TIMESTAMP())
                    ON CONFLICT (org_id, domain_name) DO UPDATE SET
                        is_primary = EXCLUDED.is_primary,
                        last_verified_at = CLOCK_TIMESTAMP();
                    """,
                    (org_id, jurisdiction, dom_clean, is_prim),
                )

            # 4. Ingest Contact Emails
            emails = org_data.get("emails") or []
            if isinstance(emails, str):
                emails = [emails]
            for email in emails:
                if not email or "@" not in str(email):
                    continue
                email_clean = str(email).strip().lower()
                domain_part = email_clean.split("@")[-1]
                cur.execute(
                    """
                    INSERT INTO master_dataextraction.contact_emails (
                        email_address, normalized_domain, org_id, deliverability_status
                    ) VALUES (%s, %s, %s, 'untested')
                    ON CONFLICT (email_address) DO UPDATE SET
                        org_id = COALESCE(master_dataextraction.contact_emails.org_id, EXCLUDED.org_id);
                    """,
                    (email_clean, domain_part, org_id),
                )

            # 5. Ingest Contact Phones
            phones = org_data.get("phones") or []
            if isinstance(phones, str):
                phones = [phones]
            for phone in phones:
                if not phone or not str(phone).strip():
                    continue
                phone_raw = str(phone).strip()
                # Basic E.164 normalization fallback
                digits = "".join(c for c in phone_raw if c.isdigit())
                if len(digits) >= 10:
                    e164 = f"+1{digits[-10:]}" if jurisdiction == "US" else f"+52{digits[-10:]}"
                    cur.execute(
                        """
                        INSERT INTO master_dataextraction.contact_phones (
                            phone_e164, country_code, national_number, org_id
                        ) VALUES (%s, %s, %s, %s)
                        ON CONFLICT DO NOTHING;
                        """,
                        (e164, "+1" if jurisdiction == "US" else "+52", digits[-10:], org_id),
                    )

            # 6. Record Field Lineage (Mandatory Enterprise Provenance)
            if observation_id:
                try:
                    effective_obs_id = str(uuid.UUID(str(observation_id)))
                except (ValueError, AttributeError):
                    effective_obs_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(observation_id)))
            else:
                effective_obs_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{source_name}:{org_id}"))

            provenance_fields = [
                ("legal_name", legal_name),
                ("primary_domain", primary_domain),
                ("statutory_tax_id", tax_id),
                ("primary_industry_naics", naics),
            ]
            if emails:
                provenance_fields.append(("primary_email", emails[0]))
            if phones:
                provenance_fields.append(("primary_phone", phones[0]))

            for field_name, val in provenance_fields:
                if val:
                    try:
                        cur.execute("SAVEPOINT lineage_sp;")
                        cur.execute(
                            """
                            INSERT INTO kg_lineage.field_provenance (
                                entity_id, field_name, chosen_value, source_name,
                                observation_id, authority_weight, asserted_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, CLOCK_TIMESTAMP())
                            ON CONFLICT (entity_id, field_name) DO UPDATE SET
                                chosen_value = EXCLUDED.chosen_value,
                                observation_id = EXCLUDED.observation_id,
                                authority_weight = EXCLUDED.authority_weight,
                                asserted_at = CLOCK_TIMESTAMP()
                            WHERE EXCLUDED.authority_weight >= kg_lineage.field_provenance.authority_weight;
                            """,
                            (org_id, field_name, str(val), source_name, effective_obs_id, authority_weight),
                        )
                        cur.execute("RELEASE SAVEPOINT lineage_sp;")
                    except Exception as prov_err:
                        cur.execute("ROLLBACK TO SAVEPOINT lineage_sp;")
                        logger.debug("Lineage provenance insertion notice: %s", prov_err)

            # 7. Update Search Projection (for CDC / OpenSearch 2.x streaming)
            cur.execute(
                """
                INSERT INTO kg_search.company_search_projection (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    all_domains, all_aliases, industry_naics, quality_score, last_projected_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, CLOCK_TIMESTAMP()
                )
                ON CONFLICT (org_id) DO UPDATE SET
                    legal_name = EXCLUDED.legal_name,
                    display_name = EXCLUDED.display_name,
                    primary_domain = EXCLUDED.primary_domain,
                    all_domains = EXCLUDED.all_domains,
                    all_aliases = EXCLUDED.all_aliases,
                    quality_score = EXCLUDED.quality_score,
                    sync_version = kg_search.company_search_projection.sync_version + 1,
                    last_projected_at = CLOCK_TIMESTAMP();
                """,
                (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    domains, aliases, naics, quality_score,
                ),
            )

        return org_id

    def ingest_working_organization(
        self,
        conn: Any,
        org_data: Dict[str, Any],
        source_name: str = "pipeline",
        canonical_cluster_id: Optional[str] = None,
        identity_confidence: float = 1.0,
    ) -> str:
        """
        Sprint 2: Ingests or updates a pre-master canonical entity into
        `staging_dataextraction.working_organizations`.
        Pre-master records remain in the working layer for enrichment (Agents 7, 4)
        and Bayesian governance scoring (Agent 5) before atomic promotion to master.
        """
        org_id = str(org_data.get("org_id") or org_data.get("id") or uuid.uuid4())
        jurisdiction = (org_data.get("jurisdiction") or "US").upper()
        if jurisdiction not in ("US", "MX", "CA", "GLOBAL"):
            jurisdiction = "US"

        legal_name = (org_data.get("legal_name") or org_data.get("name") or "Unknown Entity").strip()
        display_name = org_data.get("display_name") or org_data.get("name") or legal_name
        primary_domain = org_data.get("primary_domain") or org_data.get("domain")
        website = org_data.get("website") or (f"https://{primary_domain}" if primary_domain else None)
        tax_id = org_data.get("statutory_tax_id") or org_data.get("ein") or org_data.get("rfc")
        sec_cik = org_data.get("sec_cik") or org_data.get("cik")
        gleif_lei = org_data.get("gleif_lei") or org_data.get("lei")
        naics = str(org_data.get("naics_code") or org_data.get("primary_industry_naics") or "")[:10] or None
        sic = str(org_data.get("sic_code") or org_data.get("primary_industry_sic") or "")[:10] or None
        industry = org_data.get("industry") or org_data.get("primary_industry") or "Commercial Enterprise"
        emp_min = org_data.get("employee_count_min") or org_data.get("employee_min")
        emp_max = org_data.get("employee_count_max") or org_data.get("employee_max")
        annual_rev = org_data.get("annual_revenue_usd")
        
        # Phone numbers & Locations formatting
        phones = org_data.get("phones") or []
        if isinstance(phones, str):
            phones = [phones]
        phones_json = json.dumps(phones) if isinstance(phones, list) else json.dumps([])

        locations = org_data.get("locations") or []
        if isinstance(locations, str):
            locations = [locations]
        locations_json = json.dumps(locations) if isinstance(locations, list) else json.dumps([])

        cluster_id = canonical_cluster_id or org_data.get("canonical_cluster_id") or org_id
        quality_score = int(org_data.get("data_quality_score") or 0)
        trust_score = float(org_data.get("trust_score") or 0.0)
        gov_status = org_data.get("governance_status") or "IN_ENRICHMENT"
        sources = [source_name] if isinstance(source_name, str) else ["REGISTRY"]
        lineage = org_data.get("lineage_ids") or []
        lineage_json = json.dumps(lineage) if isinstance(lineage, list) else json.dumps([])

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging_dataextraction.working_organizations (
                    org_id, legal_name, display_name, primary_domain, website,
                    statutory_tax_id, sec_cik, gleif_lei, jurisdiction, industry,
                    naics_code, sic_code, employee_count_min, employee_count_max,
                    annual_revenue_usd, phones, locations, canonical_cluster_id,
                    identity_confidence, email_verification_status,
                    executive_enrichment_status, data_quality_score, trust_score,
                    governance_status, contributing_sources, lineage_ids,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s::jsonb, %s::jsonb, %s,
                    %s, 'PENDING',
                    'PENDING', %s, %s,
                    %s, %s, %s::jsonb,
                    NOW(), NOW()
                )
                ON CONFLICT (org_id) DO UPDATE SET
                    display_name = COALESCE(EXCLUDED.display_name, staging_dataextraction.working_organizations.display_name),
                    primary_domain = COALESCE(EXCLUDED.primary_domain, staging_dataextraction.working_organizations.primary_domain),
                    website = COALESCE(EXCLUDED.website, staging_dataextraction.working_organizations.website),
                    statutory_tax_id = COALESCE(EXCLUDED.statutory_tax_id, staging_dataextraction.working_organizations.statutory_tax_id),
                    sec_cik = COALESCE(EXCLUDED.sec_cik, staging_dataextraction.working_organizations.sec_cik),
                    industry = COALESCE(EXCLUDED.industry, staging_dataextraction.working_organizations.industry),
                    employee_count_min = COALESCE(EXCLUDED.employee_count_min, staging_dataextraction.working_organizations.employee_count_min),
                    employee_count_max = COALESCE(EXCLUDED.employee_count_max, staging_dataextraction.working_organizations.employee_count_max),
                    annual_revenue_usd = COALESCE(EXCLUDED.annual_revenue_usd, staging_dataextraction.working_organizations.annual_revenue_usd),
                    data_quality_score = GREATEST(EXCLUDED.data_quality_score, staging_dataextraction.working_organizations.data_quality_score),
                    canonical_cluster_id = COALESCE(EXCLUDED.canonical_cluster_id, staging_dataextraction.working_organizations.canonical_cluster_id),
                    identity_confidence = GREATEST(EXCLUDED.identity_confidence, staging_dataextraction.working_organizations.identity_confidence),
                    contributing_sources = array_cat(staging_dataextraction.working_organizations.contributing_sources, EXCLUDED.contributing_sources),
                    updated_at = NOW()
                RETURNING org_id;
                """,
                (
                    org_id, legal_name, display_name, primary_domain, website,
                    tax_id, sec_cik, gleif_lei, jurisdiction, industry,
                    naics, sic, emp_min, emp_max,
                    annual_rev, phones_json, locations_json, cluster_id,
                    identity_confidence, quality_score, trust_score,
                    gov_status, sources, lineage_json,
                ),
            )
            res = cur.fetchone()
            if res:
                org_id = str(res[0])
        return org_id

    def ingest_working_person(
        self,
        conn: Any,
        person_data: Dict[str, Any],
        org_id: str,
        confidence_score: float = 0.85,
    ) -> str:
        """
        Sprint 2: Ingests an executive or decision maker into `staging_dataextraction.working_persons`.
        Foreign key org_id references `staging_dataextraction.working_organizations(org_id)`.
        """
        person_id = str(person_data.get("person_id") or person_data.get("id") or uuid.uuid4())
        full_name = (person_data.get("full_name") or person_data.get("name") or "Unknown Individual").strip()
        first_name = person_data.get("first_name")
        last_name = person_data.get("last_name")
        title = person_data.get("title") or person_data.get("official_title") or "Executive"
        seniority = person_data.get("seniority") or person_data.get("seniority_level")
        department = person_data.get("department")
        primary_email = person_data.get("primary_email") or person_data.get("email") or person_data.get("work_email")
        primary_phone = person_data.get("primary_phone") or person_data.get("phone") or person_data.get("direct_phone")
        linkedin_url = person_data.get("linkedin_url") or person_data.get("primary_linkedin_url")
        conf = float(person_data.get("confidence_score") or confidence_score)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging_dataextraction.working_persons (
                    person_id, org_id, full_name, first_name, last_name,
                    title, seniority, department, primary_email, primary_phone,
                    linkedin_url, confidence_score, governance_status, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, 'IN_ENRICHMENT', NOW()
                )
                ON CONFLICT (person_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    title = COALESCE(EXCLUDED.title, staging_dataextraction.working_persons.title),
                    seniority = COALESCE(EXCLUDED.seniority, staging_dataextraction.working_persons.seniority),
                    department = COALESCE(EXCLUDED.department, staging_dataextraction.working_persons.department),
                    primary_email = COALESCE(EXCLUDED.primary_email, staging_dataextraction.working_persons.primary_email),
                    primary_phone = COALESCE(EXCLUDED.primary_phone, staging_dataextraction.working_persons.primary_phone),
                    linkedin_url = COALESCE(EXCLUDED.linkedin_url, staging_dataextraction.working_persons.linkedin_url),
                    confidence_score = GREATEST(EXCLUDED.confidence_score, staging_dataextraction.working_persons.confidence_score)
                RETURNING person_id;
                """,
                (
                    person_id, org_id, full_name, first_name, last_name,
                    title, seniority, department, primary_email, primary_phone,
                    linkedin_url, conf,
                ),
            )
            res = cur.fetchone()
            if res:
                person_id = str(res[0])
        return person_id

    def ingest_working_email(
        self,
        conn: Any,
        email_data: Dict[str, Any],
        org_id: str,
    ) -> str:
        """
        Sprint 2: Ingests a discovered and tested mailbox into `staging_dataextraction.working_emails`.
        """
        email_addr = (email_data.get("email_address") or email_data.get("email") or "").strip().lower()
        if not email_addr or "@" not in email_addr:
            return ""
        mailbox_user = email_addr.split("@")[0]
        email_domain = email_addr.split("@")[-1]
        deliverability = email_data.get("deliverability_status") or "PENDING"
        conf_score = int(email_data.get("confidence_score") or 0)
        is_catchall = bool(email_data.get("is_catchall", False))
        mx_record = email_data.get("mx_record")
        discovery_source = email_data.get("discovery_source") or "WEBSITE_CRAWL"

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO staging_dataextraction.working_emails (
                    org_id, email_address, mailbox_user, email_domain,
                    deliverability_status, confidence_score, is_catchall,
                    mx_record, smtp_verified_at, discovery_source, created_at
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, NOW(), %s, NOW()
                )
                ON CONFLICT (org_id, email_address) DO UPDATE SET
                    deliverability_status = EXCLUDED.deliverability_status,
                    confidence_score = EXCLUDED.confidence_score,
                    is_catchall = EXCLUDED.is_catchall,
                    mx_record = COALESCE(EXCLUDED.mx_record, staging_dataextraction.working_emails.mx_record),
                    smtp_verified_at = NOW()
                RETURNING working_email_id;
                """,
                (
                    org_id, email_addr, mailbox_user, email_domain,
                    deliverability, conf_score, is_catchall,
                    mx_record, discovery_source,
                ),
            )
            res = cur.fetchone()
            return str(res[0]) if res else ""

    def ingest_corporate_hierarchy(
        self,
        conn: Any,
        parent_org_id: str,
        child_org_id: str,
        hierarchy_type: str = "subsidiary",
        ownership_percentage: Optional[float] = None,
        direct_parent: bool = True,
        valid_from: Optional[datetime] = None,
        confidence_score: float = 0.95,
    ) -> str:
        """
        Ingests parent-child or branch relationship into `kg_graph.corporate_hierarchies`.
        """
        hierarchy_id = str(uuid.uuid4())
        v_from = valid_from or datetime.now(timezone.utc).date()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kg_graph.corporate_hierarchies (
                    hierarchy_id, parent_org_id, child_org_id, hierarchy_type,
                    ownership_percentage, direct_parent, valid_from, confidence_score
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING hierarchy_id;
                """,
                (
                    hierarchy_id, parent_org_id, child_org_id, hierarchy_type,
                    ownership_percentage, direct_parent, v_from, confidence_score,
                ),
            )
            res = cur.fetchone()
            if res:
                hierarchy_id = str(res[0])
        return hierarchy_id

    def ingest_org_technology(
        self,
        conn: Any,
        org_id: str,
        tech_name: str,
        category: str = "Cloud & Infrastructure",
        detection_method: str = "http_header_signature",
        confidence_score: float = 0.90,
    ) -> str:
        """
        Ingests detected technology stack into `kg_core.technologies` and `kg_graph.org_technologies`.
        """
        slug = tech_name.strip().lower().replace(" ", "-")
        tech_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kg_core.technologies (tech_id, name, category, slug)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET slug = EXCLUDED.slug
                RETURNING tech_id;
                """,
                (tech_id, tech_name, category, slug),
            )
            res = cur.fetchone()
            if res:
                tech_id = str(res[0])

            cur.execute(
                """
                INSERT INTO kg_graph.org_technologies (
                    org_id, tech_id, first_detected_at, last_detected_at,
                    detection_method, confidence_score, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, true)
                ON CONFLICT (org_id, tech_id) DO UPDATE SET
                    last_detected_at = EXCLUDED.last_detected_at,
                    is_active = true;
                """,
                (org_id, tech_id, now, now, detection_method, confidence_score),
            )
        return tech_id

    def ingest_person_and_employment(
        self,
        conn: Any,
        person_data: Dict[str, Any],
        org_id: Optional[str] = None,
        source_name: str = "enrichment",
        observation_id: Optional[str] = None,
    ) -> str:
        """
        Ingests a person into `kg_core.persons` and their active or historic
        employment tenure into `kg_graph.employment_relationships`.
        """
        person_id = person_data.get("person_id") or str(uuid.uuid4())
        full_name = (person_data.get("full_name") or person_data.get("name") or "Unknown Individual").strip()
        first_name = person_data.get("first_name")
        last_name = person_data.get("last_name")
        title = person_data.get("title") or person_data.get("official_title") or "Executive"
        seniority = person_data.get("seniority_level")
        department = person_data.get("department")
        departments = person_data.get("departments") or ([department] if department else [])
        if isinstance(departments, str):
            departments = [d.strip() for d in departments.split(",") if d.strip()]
        headline = person_data.get("headline")
        photo_url = person_data.get("photo_url")
        linkedin = person_data.get("linkedin_url") or person_data.get("primary_linkedin_url")
        email = person_data.get("email") or person_data.get("primary_email") or person_data.get("work_email")
        email_status = person_data.get("email_status", "UNKNOWN")
        email_conf = person_data.get("email_confidence_score") or 0
        phone = person_data.get("phone") or person_data.get("direct_phone") or person_data.get("primary_phone_e164")
        city = person_data.get("city")
        state = person_data.get("state")
        state_code = person_data.get("state_code")
        country = person_data.get("country") or "United States"
        is_current = person_data.get("is_current", True)

        with conn.cursor() as cur:
            # 1. Upsert Person into Master MDM
            cur.execute(
                """
                INSERT INTO master_dataextraction.persons (
                    person_id, full_name, first_name, last_name, primary_linkedin_url,
                    primary_email, primary_phone_e164, current_primary_org_id,
                    current_primary_title, seniority_level, department, departments,
                    headline, photo_url, email_status, email_confidence_score,
                    city, state, state_code, country_code, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, CLOCK_TIMESTAMP()
                )
                ON CONFLICT (person_id) DO UPDATE SET
                    primary_linkedin_url = COALESCE(EXCLUDED.primary_linkedin_url, master_dataextraction.persons.primary_linkedin_url),
                    primary_email = COALESCE(EXCLUDED.primary_email, master_dataextraction.persons.primary_email),
                    primary_phone_e164 = COALESCE(EXCLUDED.primary_phone_e164, master_dataextraction.persons.primary_phone_e164),
                    current_primary_org_id = COALESCE(EXCLUDED.current_primary_org_id, master_dataextraction.persons.current_primary_org_id),
                    current_primary_title = COALESCE(EXCLUDED.current_primary_title, master_dataextraction.persons.current_primary_title),
                    seniority_level = COALESCE(EXCLUDED.seniority_level, master_dataextraction.persons.seniority_level),
                    department = COALESCE(EXCLUDED.department, master_dataextraction.persons.department),
                    departments = CASE WHEN cardinality(EXCLUDED.departments) > 0 THEN EXCLUDED.departments ELSE master_dataextraction.persons.departments END,
                    headline = COALESCE(EXCLUDED.headline, master_dataextraction.persons.headline),
                    photo_url = COALESCE(EXCLUDED.photo_url, master_dataextraction.persons.photo_url),
                    email_status = COALESCE(EXCLUDED.email_status, master_dataextraction.persons.email_status),
                    email_confidence_score = GREATEST(EXCLUDED.email_confidence_score, master_dataextraction.persons.email_confidence_score),
                    city = COALESCE(EXCLUDED.city, master_dataextraction.persons.city),
                    state = COALESCE(EXCLUDED.state, master_dataextraction.persons.state),
                    state_code = COALESCE(EXCLUDED.state_code, master_dataextraction.persons.state_code),
                    updated_at = CLOCK_TIMESTAMP()
                RETURNING person_id;
                """,
                (
                    person_id, full_name, first_name, last_name, linkedin,
                    email, phone, org_id,
                    title, seniority, department, departments,
                    headline, photo_url, email_status, email_conf,
                    city, state, state_code, country[:2].upper() if len(country or "") >= 2 else "US",
                ),
            )
            res = cur.fetchone()
            if res:
                person_id = str(res[0])

            # 2. Ingest Employment Relationship (if org_id is provided)
            if org_id:
                valid_from = person_data.get("valid_from") or datetime.now(timezone.utc).date()
                cur.execute(
                    """
                    INSERT INTO kg_graph.employment_relationships (
                        person_id, org_id, title, normalized_title,
                        department, seniority_level, is_current, valid_from, headline
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT DO NOTHING;
                    """,
                    (
                        person_id, org_id, title, title.strip().title(),
                        department, seniority, is_current, valid_from, headline
                    ),
                )

            # 3. Direct Contact Email Link
            if email and "@" in str(email):
                email_clean = str(email).strip().lower()
                cur.execute(
                    """
                    INSERT INTO master_dataextraction.contact_emails (
                        email_address, normalized_domain, person_id, org_id
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (email_address) DO UPDATE SET
                        person_id = COALESCE(master_dataextraction.contact_emails.person_id, EXCLUDED.person_id),
                        org_id = COALESCE(master_dataextraction.contact_emails.org_id, EXCLUDED.org_id);
                    """,
                    (email_clean, email_clean.split("@")[-1], person_id, org_id),
                )

        return person_id


# Singleton instance
kg_ingestion_bridge = KnowledgeGraphIngestionBridge()
kg_bridge = kg_ingestion_bridge

__all__ = [
    "KnowledgeGraphIngestionBridge",
    "kg_ingestion_bridge",
    "kg_bridge",
]
