import glob
import os
import sqlite3

def inspect():
    files = glob.glob('**/*.sqlite', recursive=True) + glob.glob('**/*.db', recursive=True)
    for p in files:
        if any(x in p for x in ['.venv', 'node_modules', '.git']):
            continue
        sz = os.path.getsize(p)
        print(f"FILE: {p} ({sz} bytes)")
        try:
            conn = sqlite3.connect(p)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            print("  Tables:", tables)
            for t in tables:
                try:
                    cur.execute(f"SELECT count(*) FROM \"{t}\"")
                    print(f"    {t}: {cur.fetchone()[0]} rows")
                except Exception as e:
                    pass
            conn.close()
        except Exception as e:
            print("  Error:", e)

if __name__ == '__main__':
    inspect()

