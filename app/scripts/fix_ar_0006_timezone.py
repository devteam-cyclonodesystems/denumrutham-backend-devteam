import sys
import os
import asyncio
from datetime import timedelta, timezone

sys.path.append(os.path.abspath('backend'))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.archana import EnterpriseArchanaBooking, ArchanaBookingAudit

async def main():
    async with AsyncSessionLocal() as session:
        booking_res = await session.execute(
            select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.ref_id == "AR-20260522-0006")
        )
        booking = booking_res.scalar_one_or_none()
        if not booking:
            print("Booking AR-20260522-0006 not found.")
            return

        print("Before fix:")
        print(f"Ref ID: {booking.ref_id}")
        print(f"Ritual Time: {booking.ritual_time} (tz: {booking.ritual_time.tzinfo if booking.ritual_time else None})")

        # Correcting timezone shift by subtracting 5 hours and 30 minutes
        old_time = booking.ritual_time
        # Ensure it has timezone info (it should be UTC-aware)
        if old_time.tzinfo is None:
            old_time = old_time.replace(tzinfo=timezone.utc)
        
        new_time = old_time - timedelta(hours=5, minutes=30)
        booking.ritual_time = new_time

        # Log audit for timezone correction
        audit = ArchanaBookingAudit(
            booking_id=booking.id,
            action="TIMEZONE_CORRECTION",
            actor_id=None,  # System script
            old_state={"ritual_time": old_time.isoformat()},
            new_state={"ritual_time": new_time.isoformat(), "reason": "TimeZone Stabilization Refactor - AR-0006 correction"}
        )
        session.add(audit)

        await session.commit()
        await session.refresh(booking)

        print("\nAfter fix:")
        print(f"Ref ID: {booking.ref_id}")
        print(f"Ritual Time: {booking.ritual_time} (tz: {booking.ritual_time.tzinfo if booking.ritual_time else None})")
        print("\nDatabase correction successfully committed.")

if __name__ == "__main__":
    asyncio.run(main())
