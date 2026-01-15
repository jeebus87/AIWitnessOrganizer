"""Check and apply database migration."""
import asyncio
import os

import asyncpg


async def main():
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        return

    # Convert postgresql:// to postgresql:// (asyncpg doesn't need +asyncpg)
    db_url = DATABASE_URL.replace("postgresql://", "postgresql://")

    conn = await asyncpg.connect(db_url)

    # Check if firebase_uid exists
    result = await conn.fetchrow("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'firebase_uid'
    """)

    if result:
        print("Found firebase_uid column, renaming to clio_user_id...")
        await conn.execute("ALTER TABLE users RENAME COLUMN firebase_uid TO clio_user_id")
        await conn.execute("DROP INDEX IF EXISTS ix_users_firebase_uid")
        await conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_clio_user_id ON users(clio_user_id)")
        print("Migration complete!")
    else:
        result = await conn.fetchrow("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'users' AND column_name = 'clio_user_id'
        """)
        if result:
            print("clio_user_id column already exists, no migration needed.")
        else:
            print("ERROR: Neither firebase_uid nor clio_user_id column exists!")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
