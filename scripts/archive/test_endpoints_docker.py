import asyncio
from app.core.database import AsyncSessionLocal as SessionLocal
from app.services.hall_service import HallService
from app.models.domain import HallBooking
from sqlalchemy import select

async def main():
    async with SessionLocal() as db:
        # Get one booking to test
        res = await db.execute(select(HallBooking).limit(1))
        booking = res.scalar_one_or_none()
        if not booking:
            print("No bookings found in DB to test!")
            return
        
        print(f"Testing with booking ID: {booking.id}, temple_id: {booking.temple_id}")
        
        try:
            txns = await HallService.get_booking_transactions(db, str(booking.id), str(booking.temple_id))
            print(f"Transactions: {txns}")
        except Exception as e:
            print(f"Failed get_booking_transactions: {e}")
            import traceback; traceback.print_exc()

        try:
            audit = await HallService.get_booking_audit_trail(db, str(booking.id), str(booking.temple_id))
            print(f"Audit Trail: {audit}")
        except Exception as e:
            print(f"Failed get_booking_audit_trail: {e}")
            import traceback; traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
