import asyncio
from app.core.database import AsyncSessionLocal
from app.models.domain import Booking
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Booking).limit(10))
        bookings = result.scalars().all()
        print(f"Total bookings sample: {len(bookings)}")
        for b in bookings:
            print(f"ID: {b.id} | Tenant: {b.tenant_id} | Amount: {b.total_amount}")

if __name__ == "__main__":
    asyncio.run(main())
