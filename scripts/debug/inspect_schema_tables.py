import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from packages.infrastructure.db_connector import get_db_cursor

with get_db_cursor() as (conn, cur):
    for schema in ['raw_dataextraction', 'staging_dataextraction', 'identity_resolution', 'master_dataextraction', 'search_dataextraction']:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE' ORDER BY table_name;",
            (schema,)
        )
        tables = [t[0] for t in cur.fetchall()]
        print(f"{schema} ({len(tables)} tables):", tables[:8], "..." if len(tables) > 8 else "")

