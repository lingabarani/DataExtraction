from packages.infrastructure.db_connector import get_connection

conn = get_connection()
cur = conn.cursor()

cur.execute("""
    SELECT count(*) 
    FROM public.companies c
    WHERE NOT EXISTS (
        SELECT 1 FROM master_dataextraction.organizations o 
        WHERE (o.primary_domain = c.domain AND c.domain IS NOT NULL)
           OR LOWER(o.display_name) = LOWER(c.name)
    );
""")
unpromoted = cur.fetchone()[0]
print(f"Unpromoted companies in public.companies: {unpromoted}")

