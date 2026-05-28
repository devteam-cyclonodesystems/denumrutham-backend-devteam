
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.archana import EnterpriseArchanaBooking, ArchanaBookingItem, ArchanaBookingMember
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(EnterpriseArchanaBooking)
            .filter(EnterpriseArchanaBooking.ref_id == 'AR-20260515-0007')
            .options(selectinload(EnterpriseArchanaBooking.members).selectinload(ArchanaBookingMember.items))
        )
        b = res.scalar()
        if not b:
            print("Booking not found")
            return
        for m in b.members:
            for i in m.items:
                print(f"ITEM: {i.service_id}, SNAPSHOT: {i.ritual_name_snapshot}")

if __name__ == "__main__":
    asyncio.run(check())
