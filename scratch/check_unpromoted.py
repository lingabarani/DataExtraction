from packages.infrastructure.db_connector import get_connection

conn = get_connection()
cur = conn.cursor()

# Check unpromoted leads in public.us_leads
cur.execute("""
    SELECT count(*) 
    FROM public.us_leads l
    WHERE NOT EXISTS (
        SELECT 1 FROM master_dataextraction.persons p 
        WHERE p.primary_email = l.email AND l.email IS NOT NULL
    );
""")
unpromoted_with_email = cur.fetchone()[0]

cur.execute("""
    SELECT count(*) 
    FROM public.us_leads l
    WHERE NOT EXISTS (
        SELECT 1 FROM master_dataextraction.organizations o 
        WHERE o.primary_domain = l.domain AND l.domain IS NOT NULL
    );
""")
unpromoted_with_domain = cur.fetchone()[0]

print(f"Unpromoted leads by email: {unpromoted_with_email}")
print(f"Unpromoted leads by domain: {unpromoted_with_domain}")

