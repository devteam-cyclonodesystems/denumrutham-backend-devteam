import asyncio
from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, Booking
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Temple))
        temples = result.scalars().all()
        print(f"Total temples: {len(temples)}")
        for t in temples:
            print(f"Temple ID: {t.id} | Name: {t.name}")
            
            # Count bookings for this temple
            res_b = await db.execute(select(Booking).filter(Booking.tenant_id == t.id))
            b_count = len(res_b.scalars().all())
            print(f"  -> Bookings count in DB for this ID: {b_count}")

if __name__ == "__main__":
    asyncio.run(main())
