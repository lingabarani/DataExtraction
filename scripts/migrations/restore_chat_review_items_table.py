import psycopg2

conn = psycopg2.connect('postgresql://dex_user:7903@127.0.0.1:5432/dataextraction')
cur = conn.cursor()

cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_schema = 'chat_dataextraction' AND table_name = '_archived_chat_review_items'
    ORDER BY ordinal_position
""")
cols = cur.fetchall()
print("Archived cols:", cols)

# Check if chat_review_items exists
cur.execute("""
    SELECT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'chat_dataextraction' AND table_name = 'chat_review_items'
    )
""")
exists = cur.fetchone()[0]
print("chat_review_items exists:", exists)

if not exists:
    cur.execute("""
        CREATE TABLE chat_dataextraction.chat_review_items (
            LIKE chat_dataextraction._archived_chat_review_items INCLUDING ALL
        );
    """)
    conn.commit()
    print("Created chat_dataextraction.chat_review_items from archive template successfully!")

conn.close()
