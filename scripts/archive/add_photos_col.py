import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def migrate():
    async with AsyncSessionLocal() as db:
        await db.execute(text("ALTER TABLE halls ADD COLUMN IF NOT EXISTS photos JSONB DEFAULT '[]'"))
        await db.commit()
        print("OK: photos column added")

asyncio.run(migrate())
