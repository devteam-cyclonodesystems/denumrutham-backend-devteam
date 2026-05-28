import asyncio
import sys
sys.path.insert(0, '.')
from app.core.database import engine
from sqlalchemy import text

async def main():
    async with engine.connect() as conn:
        r = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND (tablename LIKE '%payment%' OR tablename LIKE '%audit%' OR tablename LIKE '%booking%' OR tablename LIKE '%ledger%')"))
        print("=== Relevant Tables ===")
        for row in r:
            print(f"  {row[0]}")

asyncio.run(main())
