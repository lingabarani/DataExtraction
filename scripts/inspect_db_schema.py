import psycopg2

conn = psycopg2.connect('postgresql://postgres:7903@localhost:5432/dataextraction')
cur = conn.cursor()
cur.execute("SELECT source_name, count(*) FROM raw_dataextraction.scraper_payloads GROUP BY source_name;")
print('Raw source counts:', cur.fetchall())

cur.execute("SELECT count(*) FROM mexico_leads;")
print('mexico_leads:', cur.fetchone()[0])
cur.execute("SELECT count(*) FROM us_leads;")
print('us_leads:', cur.fetchone()[0])
cur.execute("SELECT count(*) FROM people;")
print('people:', cur.fetchone()[0])
cur.execute("SELECT count(*) FROM companies;")
print('companies:', cur.fetchone()[0])

cur.execute("SELECT full_name, title, email, phone, company_name, domain FROM mexico_leads LIMIT 5;")
print('mexico_leads sample:')
for r in cur.fetchall():
    print(' ', r)
