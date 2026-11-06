from packages.infrastructure.db_connector import get_connection

conn = get_connection()
cur = conn.cursor()

tables = [
    "public.companies",
    "public.us_leads",
    "staging_dataextraction.staging_companies",
    "staging_dataextraction.staging_people",
    "master_dataextraction.organizations",
    "master_dataextraction.persons",
    "kg_search.company_search_projection",
]

for t in tables:
    cur.execute(f"SELECT count(*) FROM {t}")
    print(f"{t}: {cur.fetchone()[0]:,}")

