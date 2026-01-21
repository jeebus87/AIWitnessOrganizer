import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

async def get_failed():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text('''
            SELECT id, filename, processing_error
            FROM documents
            WHERE matter_id = 12982
            AND is_processed = FALSE
            AND processing_error IS NOT NULL
        '''))
        rows = result.fetchall()
        if not rows:
            print("No failed documents found")
            return
        for row in rows:
            print(f"Document ID: {row[0]}")
            print(f"Filename: {row[1]}")
            print(f"Error: {row[2][:500] if row[2] else 'None'}")
            print("-" * 60)

asyncio.run(get_failed())
