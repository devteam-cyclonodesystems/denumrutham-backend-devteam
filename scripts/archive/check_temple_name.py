
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.archana import EnterpriseArchanaBooking
from app.models.domain import Temple
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.ref_id == 'AR-20260515-0007'))
        b = res.scalar()
        print(f"BOOKING TEMPLE_ID: {b.temple_id}")
        
        res = await db.execute(select(Temple).filter(Temple.id == b.temple_id))
        t = res.scalar()
        print(f"TEMPLE NAME IN DB: {t.name if t else 'NOT FOUND'}")

if __name__ == "__main__":
    asyncio.run(check())
