import asyncio
import sys
import os

sys.path.append(os.path.abspath('c:/Denumrutham/backend'))

from sqlalchemy import text
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.archana import EnterpriseArchanaBooking

async def check():
    async with AsyncSessionLocal() as session:
        # Set RLS session context for background/superadmin bypass
        await session.execute(text("SELECT set_config('app.current_temple_id', 'SYSTEM', false)"))
        await session.execute(text("SELECT set_config('app.current_role', 'SUPER_ADMIN', false)"))
        
        # Check Bookings
        res = await session.execute(select(EnterpriseArchanaBooking))
        bookings = res.scalars().all()
        print(f"Total Bookings: {len(bookings)}")
        for b in bookings:
            print(f"  Booking: ref_id: {b.ref_id}, temple_id: {b.temple_id}, status: {b.status}")

if __name__ == '__main__':
    asyncio.run(check())
