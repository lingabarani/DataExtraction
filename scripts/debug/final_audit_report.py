import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from packages.infrastructure.db_connector import get_db_cursor

with get_db_cursor() as (conn, cur):
    print("=" * 80)
    print("DATA EXTRACTION ENTERPRISE DATABASE AUDIT: VERIFIED LIVE COUNTS")
    print("=" * 80)
    
    cur.execute("SELECT COUNT(*) FROM raw_dataextraction.scraper_payloads;")
    total_raw = cur.fetchone()[0]
    print(f"\n1. RAW LAYER (raw_dataextraction.scraper_payloads) : {total_raw:,} records")

    cur.execute("""
        SELECT source_name, COUNT(*), MIN(ingested_at), MAX(ingested_at)
        FROM raw_dataextraction.scraper_payloads
        GROUP BY source_name
        ORDER BY count(*) DESC;
    """)
    for row in cur.fetchall():
        print(f"   • {row[0]:<25} : {row[1]:>8,} payloads | {row[2].strftime('%Y-%m-%d %H:%M:%S')} to {row[3].strftime('%H:%M:%S')}")
        
    cur.execute("SELECT COUNT(*) FROM staging_dataextraction.staging_companies;")
    total_staging_co = cur.fetchone()[0]
    print(f"\n2. STAGING COMPANIES (staging_dataextraction.staging_companies) : {total_staging_co:,} records")

    cur.execute("""
        SELECT source, COUNT(*)
        FROM staging_dataextraction.staging_companies
        GROUP BY source
        ORDER BY count(*) DESC;
    """)
    for row in cur.fetchall():
        print(f"   • {row[0]:<25} : {row[1]:>8,} companies")

    cur.execute("SELECT COUNT(*) FROM staging_dataextraction.scraper_tiles;")
    tiles_count = cur.fetchone()[0]
    print(f"\n3. GEOSPATIAL TILES (staging_dataextraction.scraper_tiles) : {tiles_count:,} tiles")

    cur.execute("SELECT COUNT(*) FROM staging_dataextraction.scraper_results;")
    places_count = cur.fetchone()[0]
    print(f"4. GEOSPATIAL PLACES (staging_dataextraction.scraper_results) : {places_count:,} places")

    cur.execute("SELECT COUNT(*) FROM master_dataextraction.organizations;")
    master_count = cur.fetchone()[0]
    print(f"\n5. MASTER MDM (master_dataextraction.organizations) : {master_count:,} canonical organizations")

    print("\n" + "=" * 80)
    print("SAMPLE STORED RECORDS IN raw_dataextraction.scraper_payloads:")
    print("=" * 80)
    for src in ['OPEN_DIRECTORIES_SF', 'SEC_EDGAR', 'FDIC_BANKS', 'CMS_NPI']:
        cur.execute(
            "SELECT payload_id, source_name, natural_key, payload_hash, substring(raw_body from 1 for 120) "
            "FROM raw_dataextraction.scraper_payloads WHERE source_name = %s LIMIT 1;",
            (src,)
        )
        r = cur.fetchone()
        if r:
            print(f"[{r[1]}]")
            print(f"   Payload ID : {r[0]}")
            print(f"   Natural Key: {r[2]}")
            print(f"   SHA256 Hash: {r[3]}")
            print(f"   Raw Body   : {r[4]}...\n")

