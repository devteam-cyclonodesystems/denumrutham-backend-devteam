import asyncio
from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, Booking, Donation
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Temple))
        temples = result.scalars().all()
        print(f"Total temples: {len(temples)}")
        for t in temples:
            print(f"NAME: {t.name}")
            print(f"ID  : {t.id}")
            
            res_b = await db.execute(select(Booking).where(Booking.tenant_id == t.id))
            b_count = len(res_b.scalars().all())
            print(f"  -> Bookings: {b_count}")
            
            res_d = await db.execute(select(Donation).where(Donation.tenant_id == t.id))
            donations = res_d.scalars().all()
            d_total = sum(d.amount for d in donations)
            print(f"  -> Donations: ₹{d_total}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())
