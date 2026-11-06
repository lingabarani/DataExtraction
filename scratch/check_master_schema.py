from packages.infrastructure.db_connector import get_connection

conn = get_connection()
cur = conn.cursor()

for table in ["organizations", "persons"]:
    cur.execute(f"""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'master_dataextraction' AND table_name = '{table}'
        ORDER BY ordinal_position;
    """)
    cols = [f"{r[0]} ({r[1]})" for r in cur.fetchall()]
    print(f"\nmaster_dataextraction.{table} ({len(cols)} columns):")
    print(", ".join(cols))

