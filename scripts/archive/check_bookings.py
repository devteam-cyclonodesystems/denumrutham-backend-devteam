
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.archana import EnterpriseArchanaBooking
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(EnterpriseArchanaBooking).order_by(EnterpriseArchanaBooking.created_at.desc()).limit(5))
        bookings = res.scalars().all()
        for b in bookings:
            print(f"REF: {b.ref_id}, DEVOTEE: {b.primary_devotee_name}, AT: {b.created_at}")

if __name__ == "__main__":
    asyncio.run(check())
