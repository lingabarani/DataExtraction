"""
DataExtraction Enterprise — GDPR & CCPA Compliance & Suppression Engine
Implements Right-to-be-Forgotten, Consumer Opt-Out suppression, and automated PII scrubbing.
"""

import hashlib
import logging
import sys
from typing import Any, Dict, List, Optional
from packages.infrastructure.db_connector import get_connection, release_connection, DATABASE_TYPE
from packages.infrastructure.audit_trail_repository import AuditTrailRepository

logger = logging.getLogger("dataextraction.compliance")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [COMPLIANCE] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


class ComplianceManager:
    """Enterprise compliance manager enforcing GDPR/CCPA suppression and automated purging."""

    @staticmethod
    def hash_identifier(identifier: str) -> str:
        """Standardized SHA-256 cryptographic hash of normalized identifier."""
        clean = identifier.strip().lower()
        return hashlib.sha256(clean.encode("utf-8")).hexdigest()

    @classmethod
    def register_suppression(
        cls,
        identifier: str,
        identifier_type: str,
        reason: str = "GDPR_FORGOTTEN",
        actor_email: str = "compliance@oneextraction.internal",
    ) -> Dict[str, Any]:
        """Registers a suppression request in kg_audit.suppression_lists."""
        hashed = cls.hash_identifier(identifier)
        clean_type = identifier_type.lower().strip()
        conn = get_connection()

        try:
            cur = conn.cursor()
            if DATABASE_TYPE == "postgresql":
                cur.execute(
                    """
                    INSERT INTO kg_audit.suppression_lists (
                        hashed_identifier, identifier_type, reason, requested_at, is_active
                    )
                    VALUES (%s, %s, %s, NOW(), TRUE)
                    ON CONFLICT (hashed_identifier) DO UPDATE
                    SET is_active = TRUE, reason = EXCLUDED.reason, requested_at = NOW()
                    RETURNING suppression_id;
                    """,
                    (hashed, clean_type, reason),
                )
                suppression_id = str(cur.fetchone()[0])
            else:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS suppression_lists (
                        suppression_id TEXT PRIMARY KEY,
                        hashed_identifier TEXT UNIQUE,
                        identifier_type TEXT,
                        reason TEXT,
                        requested_at TEXT DEFAULT (datetime('now')),
                        is_active INTEGER DEFAULT 1
                    );
                    """
                )
                import uuid
                suppression_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT OR REPLACE INTO suppression_lists (
                        suppression_id, hashed_identifier, identifier_type, reason, is_active
                    )
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (suppression_id, hashed, clean_type, reason),
                )
            conn.commit()
            cur.close()

            AuditTrailRepository.record_access_event(
                user_id="compliance_engine",
                user_email=actor_email,
                action="COMPLIANCE_OPT_OUT",
                resource_type=clean_type,
                resource_id=hashed,
                metadata={"reason": reason, "suppression_id": suppression_id},
            )

            return {
                "success": True,
                "suppression_id": suppression_id,
                "hashed_identifier": hashed,
                "type": clean_type,
                "reason": reason,
            }
        except Exception as exc:
            logger.error("Failed to register suppression: %s", exc)
            if hasattr(conn, "rollback"):
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            release_connection(conn)

    @classmethod
    def is_suppressed(cls, identifier: str) -> bool:
        """Checks if identifier hash exists in the active suppression list."""
        hashed = cls.hash_identifier(identifier)
        conn = get_connection()
        try:
            cur = conn.cursor()
            table_name = "kg_audit.suppression_lists" if DATABASE_TYPE == "postgresql" else "suppression_lists"
            ph = "%s" if DATABASE_TYPE == "postgresql" else "?"
            cur.execute(
                f"SELECT 1 FROM {table_name} WHERE hashed_identifier = {ph} AND is_active = TRUE",
                (hashed,),
            )
            found = cur.fetchone() is not None
            cur.close()
            return found
        except Exception as exc:
            logger.warning("Error checking suppression status: %s", exc)
            return False
        finally:
            release_connection(conn)

    @classmethod
    def execute_purge(
        cls,
        identifier: str,
        identifier_type: str = "email",
        dry_run: bool = False,
        actor_email: str = "compliance@oneextraction.internal",
    ) -> Dict[str, Any]:
        """
        Executes a GDPR/CCPA purge scrubbing or redacting PII records across all lead tables.
        """
        clean_id = identifier.strip().lower()
        clean_type = identifier_type.lower().strip()
        conn = get_connection()
        scrubbed_counts: Dict[str, int] = {
            "us_leads": 0,
            "mexico_leads": 0,
            "people": 0,
            "enrichment_results": 0,
        }

        try:
            cur = conn.cursor()
            ph = "%s" if DATABASE_TYPE == "postgresql" else "?"

            # 1. US Leads
            if clean_type == "email":
                cur.execute(f"SELECT COUNT(*) FROM public.us_leads WHERE LOWER(email) = {ph}", (clean_id,))
                scrubbed_counts["us_leads"] = cur.fetchone()[0]
                if not dry_run and scrubbed_counts["us_leads"] > 0:
                    cur.execute(
                        f"""
                        UPDATE public.us_leads
                        SET email = '[SUPPRESSED_GDPR]',
                            full_name = '[REDACTED_GDPR]',
                            phone = '[SUPPRESSED]',
                            contact = jsonb_set(contact, '{{opt_out}}', 'true'::jsonb),
                            updated_at = NOW()
                        WHERE LOWER(email) = {ph}
                        """,
                        (clean_id,),
                    )
            elif clean_type == "domain":
                cur.execute(f"SELECT COUNT(*) FROM public.us_leads WHERE LOWER(domain) = {ph}", (clean_id,))
                scrubbed_counts["us_leads"] = cur.fetchone()[0]
                if not dry_run and scrubbed_counts["us_leads"] > 0:
                    cur.execute(
                        f"""
                        UPDATE public.us_leads
                        SET email = '[SUPPRESSED_GDPR]',
                            full_name = '[REDACTED_GDPR]',
                            phone = '[SUPPRESSED]',
                            updated_at = NOW()
                        WHERE LOWER(domain) = {ph}
                        """,
                        (clean_id,),
                    )

            # 2. Mexico Leads
            if clean_type == "email":
                cur.execute(f"SELECT COUNT(*) FROM public.mexico_leads WHERE LOWER(email) = {ph}", (clean_id,))
                scrubbed_counts["mexico_leads"] = cur.fetchone()[0]
                if not dry_run and scrubbed_counts["mexico_leads"] > 0:
                    cur.execute(
                        f"""
                        UPDATE public.mexico_leads
                        SET email = '[SUPPRESSED_GDPR]',
                            full_name = '[REDACTED_GDPR]',
                            phone = '[SUPPRESSED]',
                            updated_at = NOW()
                        WHERE LOWER(email) = {ph}
                        """,
                        (clean_id,),
                    )

            # 3. People Table
            if clean_type == "email":
                cur.execute(f"SELECT COUNT(*) FROM public.people WHERE LOWER(email) = {ph}", (clean_id,))
                scrubbed_counts["people"] = cur.fetchone()[0]
                if not dry_run and scrubbed_counts["people"] > 0:
                    cur.execute(
                        f"""
                        UPDATE public.people
                        SET email = '[SUPPRESSED_GDPR]',
                            first_name = '[REDACTED]',
                            last_name = '[REDACTED]',
                            direct_phone = NULL,
                            opt_out_requested = TRUE,
                            updated_at = NOW()
                        WHERE LOWER(email) = {ph}
                        """,
                        (clean_id,),
                    )

            if not dry_run:
                conn.commit()
                # Automatically register suppression
                cls.register_suppression(
                    identifier=clean_id,
                    identifier_type=clean_type,
                    reason="GDPR_PURGE_EXECUTED",
                    actor_email=actor_email,
                )

            cur.close()

            AuditTrailRepository.record_access_event(
                user_id="compliance_engine",
                user_email=actor_email,
                action="COMPLIANCE_PURGE",
                resource_type=clean_type,
                resource_id=cls.hash_identifier(clean_id),
                metadata={
                    "dry_run": dry_run,
                    "scrubbed_counts": scrubbed_counts,
                    "total_affected": sum(scrubbed_counts.values()),
                },
            )

            return {
                "dry_run": dry_run,
                "identifier_type": clean_type,
                "total_affected_records": sum(scrubbed_counts.values()),
                "breakdown": scrubbed_counts,
                "status": "SIMULATED" if dry_run else "EXECUTED_PURGED",
            }
        except Exception as exc:
            logger.error("Error during compliance purge: %s", exc)
            if hasattr(conn, "rollback"):
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            release_connection(conn)

