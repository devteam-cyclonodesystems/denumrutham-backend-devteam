import asyncio
from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, Booking, Donation, Pooja, Devotee, BookingStatus
from sqlalchemy import select, delete

async def main():
    async with AsyncSessionLocal() as db:
        # 1. Find the temple
        result = await db.execute(select(Temple).where(Temple.name.like("%Mallottu%")))
        temple = result.scalars().first()
        if not temple:
            print("Temple Mallottu not found!")
            return
        
        print(f"Aligning data for Temple: {temple.name} (ID: {temple.id})")
        
        # 2. Clear existing entries for this specific temple
        await db.execute(delete(Booking).where(Booking.tenant_id == temple.id))
        await db.execute(delete(Donation).where(Donation.tenant_id == temple.id))
        
        # 3. Create fresh entries
        result = await db.execute(select(Devotee))
        devotee = result.scalars().first()
        if not devotee:
            devotee = Devotee(name="Test Devotee", phone="9999999999")
            db.add(devotee)
            await db.flush()
            
        result = await db.execute(select(Pooja).where(Pooja.tenant_id == temple.id))
        pooja = result.scalars().first()
        if not pooja:
            pooja = Pooja(name="Ganapathi Homam", base_price=500.0, tenant_id=temple.id)
            db.add(pooja)
            await db.flush()
            
        print("Creating 10 bookings...")
        for i in range(10):
            b = Booking(
                tenant_id=temple.id,
                devotee_id=devotee.id,
                total_amount=pooja.base_price,
                status=BookingStatus.CONFIRMED
            )
            db.add(b)
            
        print("Creating ₹50,000 donation...")
        d = Donation(
            tenant_id=temple.id,
            devotee_id=devotee.id,
            amount=50000.0,
            notes="Real-time check donation"
        )
        db.add(d)
        
        await db.commit()
        print("Data alignment complete!")

if __name__ == "__main__":
    asyncio.run(main())
