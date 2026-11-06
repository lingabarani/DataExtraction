from packages.infrastructure.db_connector import get_connection

conn = get_connection()
if not conn:
    print("Cannot connect to PostgreSQL")
    exit(1)

cur = conn.cursor()
cur.execute("""
    SELECT table_schema, table_name, table_type 
    FROM information_schema.tables 
    WHERE table_name IN ('us_leads', 'companies', 'staging_companies', 'organizations', 'company_search_projection')
    ORDER BY table_schema, table_name;
""")
for row in cur.fetchall():
    print(row)

cur.execute("""
    SELECT table_schema, table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'staging_dataextraction';
""")
print("\nstaging_dataextraction tables:")
for row in cur.fetchall():
    print(row)

