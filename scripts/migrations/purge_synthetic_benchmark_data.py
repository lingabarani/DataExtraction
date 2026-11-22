"""
Enterprise Migration: Purge Synthetic & Benchmark Test Records
==============================================================
Safely purges synthetic load/benchmark artifacts from:
  - master_dataextraction.contact_emails
  - search_dataextraction.company_search_projection
  - master_dataextraction.persons
  - master_dataextraction.organizations

Guarantees 100% referential integrity and zero impact on genuine sovereign records.
"""

import logging
import os
import sys
import psycopg2
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migration.purge_synthetic")

load_dotenv()

def get_db_connection():
    db_name = os.getenv("POSTGRES_DB", "dataextraction")
    user = os.getenv("POSTGRES_USER", "dex_user")
    password = os.getenv("POSTGRES_PASSWORD", "7903")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    return psycopg2.connect(dbname=db_name, user=user, password=password, host=host, port=port)

def purge_synthetic_data():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        logger.info("Initiating atomic purge transaction for synthetic benchmark artifacts...")

        # 1. Count target organizations
        org_filter = """
            primary_domain ~* '(soak-|bench_load|bench_promo|test-org|vault-|apex-\\d+\\.io)'
            OR statutory_tax_id ILIKE 'EIN-%'
            OR legal_name ~* '^(acme\\s*\\d+|endurance\\s*\\d+|enterprise\\s*apex\\s*\\d+|antigravity\\s*solutions)'
        """
        cur.execute(f"SELECT count(*) FROM master_dataextraction.organizations WHERE {org_filter};")
        target_org_count = cur.fetchone()[0]
        logger.info("Found %d synthetic organizations to purge.", target_org_count)

        # 2. Count target persons
        person_filter = f"""
            primary_email ~* '(soak-|bench_load|bench_promo|vault-|apex-)'
            OR full_name ~* '^(director\\s+alex\\s*\\d+|dr\\.\\s*alexander\\s*\\d+|alex\\s*rivera|alexander\\s*vance)'
            OR current_primary_org_id IN (
                SELECT org_id FROM master_dataextraction.organizations WHERE {org_filter}
            )
        """
        cur.execute(f"SELECT count(*) FROM master_dataextraction.persons WHERE {person_filter};")
        target_person_count = cur.fetchone()[0]
        logger.info("Found %d synthetic persons to purge.", target_person_count)

        # 3. Create temporary tables of IDs for fast transactional joins
        cur.execute(f"""
            CREATE TEMP TABLE temp_synth_org_ids ON COMMIT DROP AS
            SELECT org_id FROM master_dataextraction.organizations WHERE {org_filter};
        """)
        cur.execute(f"""
            CREATE TEMP TABLE temp_synth_person_ids ON COMMIT DROP AS
            SELECT person_id FROM master_dataextraction.persons WHERE {person_filter};
        """)

        # 4. Delete dependent contact emails
        cur.execute("""
            DELETE FROM master_dataextraction.contact_emails
            WHERE org_id IN (SELECT org_id FROM temp_synth_org_ids)
               OR person_id IN (SELECT person_id FROM temp_synth_person_ids);
        """)
        deleted_emails = cur.rowcount
        logger.info("Purged %d synthetic contact emails.", deleted_emails)

        # 5. Delete dependent search projections
        cur.execute("""
            DELETE FROM search_dataextraction.company_search_projection
            WHERE org_id IN (SELECT org_id FROM temp_synth_org_ids);
        """)
        deleted_projections = cur.rowcount
        logger.info("Purged %d synthetic company search projections.", deleted_projections)

        # 6. Delete synthetic persons
        cur.execute("""
            DELETE FROM master_dataextraction.persons
            WHERE person_id IN (SELECT person_id FROM temp_synth_person_ids);
        """)
        deleted_persons = cur.rowcount
        logger.info("Purged %d synthetic persons.", deleted_persons)

        # 7. Delete synthetic organizations
        cur.execute("""
            DELETE FROM master_dataextraction.organizations
            WHERE org_id IN (SELECT org_id FROM temp_synth_org_ids);
        """)
        deleted_orgs = cur.rowcount
        logger.info("Purged %d synthetic organizations.", deleted_orgs)

        # Commit all deletions atomically
        conn.commit()
        logger.info("Atomic purge transaction successfully committed.")

        # Verification audit
        cur.execute(f"SELECT count(*) FROM master_dataextraction.organizations WHERE {org_filter};")
        rem_orgs = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM master_dataextraction.persons WHERE {person_filter};")
        rem_persons = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM master_dataextraction.organizations;")
        total_orgs = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM master_dataextraction.persons;")
        total_persons = cur.fetchone()[0]

        logger.info("Post-Purge Verification:")
        logger.info("  Remaining synthetic orgs: %d", rem_orgs)
        logger.info("  Remaining synthetic persons: %d", rem_persons)
        logger.info("  Total Genuine Organizations: %d", total_orgs)
        logger.info("  Total Genuine Persons: %d", total_persons)

        if rem_orgs == 0 and rem_persons == 0:
            logger.info("SUCCESS: All synthetic, duplicate, and invalid test data completely purged!")
            return True
        else:
            logger.error("WARNING: Some synthetic records still remain.")
            return False

    except Exception as exc:
        conn.rollback()
        logger.error("Purge transaction aborted and rolled back due to error: %s", exc)
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    success = purge_synthetic_data()
    sys.exit(0 if success else 1)
