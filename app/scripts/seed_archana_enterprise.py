import asyncio
import logging
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, Employee
from app.models.archana import (
    ArchanaCatalog, 
    EnterpriseArchanaBooking, 
    ArchanaBookingMember, 
    ArchanaBookingItem, 
    RitualQueue, 
    ArchanaStatus, 
    QueueStatus
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def seed_archana():
    async with AsyncSessionLocal() as db:
        # Get first approved temple
        temple_res = await db.execute(select(Temple).filter(Temple.status == "APPROVED").limit(1))
        temple = temple_res.scalar()
        if not temple:
            logger.error("No approved temple found. Please run seed_complete first.")
            return

        # Check if catalog already exists
        catalog_check = await db.execute(select(ArchanaCatalog).filter(ArchanaCatalog.temple_id == temple.id).limit(1))
        if catalog_check.scalar():
            logger.info("Archana catalog already seeded.")
            return

        logger.info(f"Seeding Archana catalog for temple: {temple.name}")

        services = [
            ("Sahasranama Archana", 150.0, "Archana", 10),
            ("Bhagya Sooktha Archana", 100.0, "Archana", 5),
            ("Neyvilakku", 50.0, "Offering", 2),
            ("Pushpanjali", 30.0, "Archana", 3),
            ("Ganapathy Homam", 500.0, "Havan", 30),
            ("Mritunjaya Homam", 1500.0, "Havan", 60),
            ("Swayamvara Parvathy Archana", 250.0, "Archana", 15),
            ("Vidya Rajagopala Archana", 200.0, "Archana", 10),
        ]

        catalog_items = []
        for name, price, cat, dur in services:
            item = ArchanaCatalog(
                temple_id=temple.id,
                name=name,
                price=price,
                category=cat,
                duration_minutes=dur,
                is_active=True
            )
            db.add(item)
            catalog_items.append(item)
        
        await db.flush()
        logger.info(f"Seeded {len(catalog_items)} catalog items.")

        # Seed some sample bookings
        logger.info("Seeding sample bookings...")
        
        # Get a priest if exists
        priest_res = await db.execute(select(Employee).filter(Employee.temple_id == temple.id).limit(1))
        priest = priest_res.scalar()

        bookings_data = [
            ("Amrith Nath", "Uthradam", [catalog_items[0], catalog_items[2]]),
            ("Meera Nair", "Rohini", [catalog_items[1]]),
            ("Rohan Das", "Aswathy", [catalog_items[3], catalog_items[4]]),
        ]

        for i, (name, star, items) in enumerate(bookings_data):
            ref_id = f"AR-20260511-{str(i+1).zfill(4)}"
            booking = EnterpriseArchanaBooking(
                temple_id=temple.id,
                ref_id=ref_id,
                primary_devotee_name=name,
                phone_number="9876543210",
                booking_date=datetime.now(timezone.utc),
                status=ArchanaStatus.CONFIRMED,
                total_amount=sum(item.price for item in items),
                grand_total=sum(item.price for item in items),
                payment_mode="Cash",
                booking_mode="Counter"
            )
            
            member = ArchanaBookingMember(name=name, nakshatra=star, is_primary=True)
            for item in items:
                b_item = ArchanaBookingItem(
                    service_id=item.id,
                    quantity=1,
                    price_at_booking=item.price,
                    total_price=item.price
                )
                member.items.append(b_item)
            booking.members.append(member)
            db.add(booking)
            await db.flush()

            # Add to queue
            queue = RitualQueue(
                temple_id=temple.id,
                booking_id=booking.id,
                token_number=f"T-{str(i+101)}",
                status=QueueStatus.WAITING if i > 0 else QueueStatus.IN_PROGRESS,
                priest_id=priest.id if priest else None
            )
            db.add(queue)

        await db.commit()
        logger.info("Archana enterprise seeding complete.")

if __name__ == "__main__":
    asyncio.run(seed_archana())
