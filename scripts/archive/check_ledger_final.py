
import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT COUNT(*) FROM financial_ledger WHERE reference_id LIKE 'AR-%'"))
        print(f"LEDGER COUNT: {res.scalar()}")

if __name__ == "__main__":
    asyncio.run(check())
