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
        naics = org_data.get("primary_industry_naics") or org_data.get("naics_code")
        sic = org_data.get("primary_industry_sic") or org_data.get("sic_code")
        emp_min = org_data.get("employee_count_min")
        emp_max = org_data.get("employee_count_max")
        quality_score = org_data.get("data_quality_score", 80)

        with conn.cursor() as cur:
            # 1. Upsert Canonical Organization
            cur.execute(
                """
                INSERT INTO kg_core.organizations (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    statutory_tax_id, sec_cik, gleif_lei, primary_industry_naics,
                    primary_industry_sic, employee_count_min, employee_count_max,
                    data_quality_score, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, CLOCK_TIMESTAMP()
                )
                ON CONFLICT (org_id, jurisdiction) DO UPDATE SET
                    display_name = COALESCE(EXCLUDED.display_name, kg_core.organizations.display_name),
                    primary_domain = COALESCE(EXCLUDED.primary_domain, kg_core.organizations.primary_domain),
                    statutory_tax_id = COALESCE(EXCLUDED.statutory_tax_id, kg_core.organizations.statutory_tax_id),
                    sec_cik = COALESCE(EXCLUDED.sec_cik, kg_core.organizations.sec_cik),
                    gleif_lei = COALESCE(EXCLUDED.gleif_lei, kg_core.organizations.gleif_lei),
                    primary_industry_naics = COALESCE(EXCLUDED.primary_industry_naics, kg_core.organizations.primary_industry_naics),
                    data_quality_score = GREATEST(EXCLUDED.data_quality_score, kg_core.organizations.data_quality_score),
                    updated_at = CLOCK_TIMESTAMP()
                RETURNING org_id;
                """,
                (
                    org_id, jurisdiction, legal_name, display_name, primary_domain,
                    tax_id, sec_cik, gleif_lei, naics, sic, emp_min, emp_max,
                    quality_score,
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
                    INSERT INTO kg_core.organization_aliases (
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
                    INSERT INTO kg_core.organization_domains (
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
                    INSERT INTO kg_core.contact_emails (
                        email_address, normalized_domain, org_id, deliverability_status
                    ) VALUES (%s, %s, %s, 'untested')
                    ON CONFLICT (email_address) DO UPDATE SET
                        org_id = COALESCE(kg_core.contact_emails.org_id, EXCLUDED.org_id);
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
                        INSERT INTO kg_core.contact_phones (
                            phone_e164, country_code, national_number, org_id
                        ) VALUES (%s, %s, %s, %s)
                        ON CONFLICT DO NOTHING;
                        """,
                        (e164, "+1" if jurisdiction == "US" else "+52", digits[-10:], org_id),
                    )

            # 6. Record Field Lineage
            if observation_id:
                for field_name, val in [("legal_name", legal_name), ("primary_domain", primary_domain), ("statutory_tax_id", tax_id)]:
                    if val:
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
                            (org_id, field_name, str(val), source_name, observation_id, authority_weight),
                        )

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
        linkedin = person_data.get("linkedin_url") or person_data.get("primary_linkedin_url")
        email = person_data.get("email") or person_data.get("primary_email")
        is_current = person_data.get("is_current", True)

        with conn.cursor() as cur:
            # 1. Upsert Person
            cur.execute(
                """
                INSERT INTO kg_core.persons (
                    person_id, full_name, first_name, last_name, primary_linkedin_url,
                    primary_email, current_primary_org_id, current_primary_title,
                    seniority_level, department, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, CLOCK_TIMESTAMP()
                )
                ON CONFLICT (person_id) DO UPDATE SET
                    primary_linkedin_url = COALESCE(EXCLUDED.primary_linkedin_url, kg_core.persons.primary_linkedin_url),
                    primary_email = COALESCE(EXCLUDED.primary_email, kg_core.persons.primary_email),
                    current_primary_org_id = COALESCE(EXCLUDED.current_primary_org_id, kg_core.persons.current_primary_org_id),
                    current_primary_title = COALESCE(EXCLUDED.current_primary_title, kg_core.persons.current_primary_title),
                    updated_at = CLOCK_TIMESTAMP()
                RETURNING person_id;
                """,
                (
                    person_id, full_name, first_name, last_name, linkedin,
                    email, org_id, title, seniority, department,
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
                        department, seniority_level, is_current, valid_from
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    ON CONFLICT DO NOTHING;
                    """,
                    (
                        person_id, org_id, title, title.strip().title(),
                        department, seniority, is_current, valid_from,
                    ),
                )

            # 3. Direct Contact Email Link
            if email and "@" in str(email):
                email_clean = str(email).strip().lower()
                cur.execute(
                    """
                    INSERT INTO kg_core.contact_emails (
                        email_address, normalized_domain, person_id, org_id
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (email_address) DO UPDATE SET
                        person_id = COALESCE(kg_core.contact_emails.person_id, EXCLUDED.person_id),
                        org_id = COALESCE(kg_core.contact_emails.org_id, EXCLUDED.org_id);
                    """,
                    (email_clean, email_clean.split("@")[-1], person_id, org_id),
                )

        return person_id


# Singleton instance
kg_ingestion_bridge = KnowledgeGraphIngestionBridge()

__all__ = [
    "KnowledgeGraphIngestionBridge",
    "kg_ingestion_bridge",
]
