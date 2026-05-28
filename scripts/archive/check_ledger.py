
import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as db:
        try:
            res = await db.execute(text("SELECT COUNT(*) FROM accounting_ledgers WHERE reference_id LIKE 'AR-%'"))
            print(f"LEDGER COUNT: {res.scalar()}")
        except Exception as e:
            print(f"Error checking ledger: {str(e)}")

if __name__ == "__main__":
    asyncio.run(check())
