"""Check and apply database migration."""
import os
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# Check if firebase_uid exists
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name = 'users' AND column_name = 'firebase_uid'
""")
if cur.fetchone():
    print("Found firebase_uid column, renaming to clio_user_id...")
    cur.execute("ALTER TABLE users RENAME COLUMN firebase_uid TO clio_user_id")
    cur.execute("DROP INDEX IF EXISTS ix_users_firebase_uid")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_clio_user_id ON users(clio_user_id)")
    print("Migration complete!")
else:
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'clio_user_id'
    """)
    if cur.fetchone():
        print("clio_user_id column already exists, no migration needed.")
    else:
        print("ERROR: Neither firebase_uid nor clio_user_id column exists!")

conn.close()
