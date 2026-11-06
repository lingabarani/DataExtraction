from packages.infrastructure.db_connector import get_connection

conn = get_connection()
cur = conn.cursor()

for table in ["companies", "us_leads"]:
    cur.execute(f"""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = '{table}'
        ORDER BY ordinal_position;
    """)
    cols = [f"{r[0]} ({r[1]})" for r in cur.fetchall()]
    print(f"\npublic.{table} ({len(cols)} columns):")
    print(", ".join(cols))

