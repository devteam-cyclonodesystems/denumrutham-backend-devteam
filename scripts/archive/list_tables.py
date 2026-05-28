
import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"))
        print(f"TABLES: {[ r[0] for r in res.fetchall() ]}")

if __name__ == "__main__":
    asyncio.run(check())
