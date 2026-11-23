from packages.infrastructure.db_connector import get_connection, release_connection

def check():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT count(*) FROM master_dataextraction.organizations
                WHERE primary_domain LIKE '%soak%'
                   OR primary_domain LIKE '%bench%'
                   OR primary_domain LIKE '%vault-%'
                   OR primary_domain LIKE '%corp-%'
                   OR display_name ~* '^(Acme [0-9]+|Apex [0-9]+|Endurance [0-9]+)'
            """)
            synth_orgs = cur.fetchone()[0]

            cur.execute("""
                SELECT count(*) FROM master_dataextraction.persons
                WHERE primary_email LIKE '%soak%'
                   OR primary_email LIKE '%bench%'
                   OR primary_email LIKE '%vault-%'
                   OR primary_email LIKE '%corp-%'
                   OR full_name ~* '^(Dr\\. Alexander [0-9]+|Director Alex [0-9]+)'
            """)
            synth_persons = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM master_dataextraction.organizations")
            total_orgs = cur.fetchone()[0]

            cur.execute("SELECT count(*) FROM master_dataextraction.persons")
            total_persons = cur.fetchone()[0]

            # Check us_leads
            try:
                cur.execute("""
                    SELECT count(*) FROM us_leads
                    WHERE company_name ~* '^(Acme [0-9]+|Apex [0-9]+|Endurance [0-9]+)'
                       OR website ~* '(soak|bench|vault-|corp-)'
                """)
                us_synth = cur.fetchone()[0]
            except Exception as e:
                conn.rollback()
                us_synth = f"Error: {e}"

            print(f"Total Orgs: {total_orgs:,} | Synthetic Orgs in Master: {synth_orgs}")
            print(f"Total Persons: {total_persons:,} | Synthetic Persons in Master: {synth_persons}")
            print(f"Synthetic in us_leads: {us_synth}")

    finally:
        release_connection(conn)

if __name__ == "__main__":
    check()
