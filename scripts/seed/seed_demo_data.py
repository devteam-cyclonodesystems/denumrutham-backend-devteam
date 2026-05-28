import uuid
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_password_hash
from app.models.domain import (
    User, Temple, TempleService, ServiceType, DevoteeProfile,
    ServiceBooking, ServiceBookingStatus
)
from app.modules.bookings.models.booking_models import Devotee
from app.modules.inventory.models.inventory_models import (
    InventoryLocation, InventoryItem, KalavaraStock, Supplier
)
from app.models.system_rbac import SystemRole

logger = logging.getLogger("Seed.DemoData")

async def seed_demo_data(db: AsyncSession, temple: Temple) -> None:
    # ══════════════════════════════════════════════════════════════
    # 1. Seed Temple Services / Offerings
    # ══════════════════════════════════════════════════════════════
    services_to_seed = [
        {"name": "Maha Ganapathi Homam", "type": ServiceType.ARCHANA, "price": 500.0, "desc": "A powerful fire ritual to remove obstacles"},
        {"name": "Neyyabhishekam", "type": ServiceType.ARCHANA, "price": 250.0, "desc": "Ghee offering to Sree Dharma Sastha"},
        {"name": "Pushpanjali", "type": ServiceType.OFFERING, "price": 50.0, "desc": "Flower offering for prosperity"},
        {"name": "Aravana Payasam Prasadam", "type": ServiceType.STORE, "price": 120.0, "desc": "Traditional sweet payasam prasadam"},
        {"name": "General Temple Donation", "type": ServiceType.DONATION, "price": 0.0, "desc": "Donation for temple maintenance and services"}
    ]
    
    services = []
    for s_data in services_to_seed:
        result = await db.execute(
            select(TempleService).filter_by(temple_id=temple.id, service_name=s_data["name"])
        )
        srv = result.scalars().first()
        if not srv:
            srv = TempleService(
                id=uuid.uuid4(),
                temple_id=temple.id,
                service_name=s_data["name"],
                service_type=s_data["type"],
                price=s_data["price"],
                description=s_data["desc"],
                active=True
            )
            db.add(srv)
            logger.info(f"[Seed] [Service] [CREATED] - {s_data['name']}")
        else:
            logger.info(f"[Seed] [Service] [EXISTS] - {s_data['name']}")
        services.append(srv)
    await db.flush()

    # ══════════════════════════════════════════════════════════════
    # 2. Seed Devotee User & Profile
    # ══════════════════════════════════════════════════════════════
    devotee_id = "devotee"
    devotee_email = "devotee@example.com"
    devotee_phone = "+919876543210"
    
    result = await db.execute(select(User).filter((User.user_id == devotee_id) | (User.email == devotee_email)))
    devotee_user = result.scalars().first()
    
    if not devotee_user:
        devotee_role = await db.execute(select(SystemRole).filter(SystemRole.name == "DEVOTEE"))
        devotee_role_obj = devotee_role.scalars().first()
        
        devotee_user = User(
            id=uuid.uuid4(),
            user_id=devotee_id,
            name="Hari Kumar",
            email=devotee_email,
            phone=devotee_phone,
            password_hash=get_password_hash("DevoteePass@2026"),
            role="DEVOTEE",
            system_role_id=devotee_role_obj.id if devotee_role_obj else None,
            status="ACTIVE",
            is_active=True,
            approval_status="APPROVED"
        )
        db.add(devotee_user)
        await db.flush()
        
        # Devotee Profile
        profile = DevoteeProfile(
            id=uuid.uuid4(),
            user_id=devotee_user.id,
            name=devotee_user.name,
            nakshatra="Rohini",
            gothram="Kashyapa",
            address="Vaikom, Kottayam, Kerala"
        )
        db.add(profile)
        logger.info(f"[Seed] [Devotee] [CREATED] - Username: {devotee_id}, Password: DevoteePass@2026")
    else:
        logger.info("[Seed] [Devotee] [EXISTS] - Devotee already exists.")
    await db.flush()

    # Also seed in the `devotees` table for modular bookings
    result = await db.execute(select(Devotee).filter_by(temple_id=temple.id, phone=devotee_phone))
    devotee_record = result.scalars().first()
    if not devotee_record:
        devotee_record = Devotee(
            id=uuid.uuid4(),
            temple_id=temple.id,
            first_name="Hari",
            last_name="Kumar",
            phone=devotee_phone,
            email=devotee_email,
            star_sign_nakshatram="Rohini",
            gotram="Kashyapa"
        )
        db.add(devotee_record)
        await db.flush()

    # ══════════════════════════════════════════════════════════════
    # 3. Seed Service Bookings
    # ══════════════════════════════════════════════════════════════
    # Check if there are any bookings for this temple
    booking_result = await db.execute(select(ServiceBooking).filter_by(temple_id=temple.id))
    existing_booking = booking_result.scalars().first()
    
    if not existing_booking and services:
        target_service = services[0]  # Maha Ganapathi Homam
        booking = ServiceBooking(
            id=uuid.uuid4(),
            temple_id=temple.id,
            devotee_user_id=devotee_user.id,
            service_id=target_service.id,
            booking_date=datetime.now(timezone.utc) + timedelta(days=2),
            amount=target_service.price,
            status=ServiceBookingStatus.PAID,
            devotee_name=devotee_user.name,
            devotee_phone=devotee_phone,
            notes="Seeded test booking for Ganapathi Homam."
        )
        db.add(booking)
        logger.info(f"[Seed] [Booking] [CREATED] - Booking for {target_service.service_name} created.")
    else:
        logger.info("[Seed] [Booking] [EXISTS] - Booking data exists.")
    await db.flush()

    # ══════════════════════════════════════════════════════════════
    # 4. Seed Inventory Locations, Suppliers, Items, and Stock
    # ══════════════════════════════════════════════════════════════
    # Locations
    result = await db.execute(select(InventoryLocation).filter_by(temple_id=temple.id, name="Main Store"))
    loc_main = result.scalars().first()
    if not loc_main:
        loc_main = InventoryLocation(
            id=uuid.uuid4(),
            temple_id=temple.id,
            name="Main Store",
            description="Central inventory store room",
            is_active=True
        )
        db.add(loc_main)
        logger.info("[Seed] [InventoryLocation] [CREATED] - Main Store")
    else:
        logger.info("[Seed] [InventoryLocation] [EXISTS] - Main Store")

    result = await db.execute(select(InventoryLocation).filter_by(temple_id=temple.id, name="Kitchen"))
    loc_kitchen = result.scalars().first()
    if not loc_kitchen:
        loc_kitchen = InventoryLocation(
            id=uuid.uuid4(),
            temple_id=temple.id,
            name="Kitchen",
            description="Temple kitchen store (Potuppura)",
            is_active=True
        )
        db.add(loc_kitchen)
        logger.info("[Seed] [InventoryLocation] [CREATED] - Kitchen")
    else:
        logger.info("[Seed] [InventoryLocation] [EXISTS] - Kitchen")
    await db.flush()

    # Supplier
    result = await db.execute(select(Supplier).filter_by(temple_id=temple.id, name="Kerala Agro Traders"))
    supplier = result.scalars().first()
    if not supplier:
        supplier = Supplier(
            id=uuid.uuid4(),
            temple_id=temple.id,
            sup_code="TSUP-2026-001",
            name="Kerala Agro Traders",
            contact="+914849876543",
            email="sales@keralaagro.example.com",
            address="Ernakulam, Kerala"
        )
        db.add(supplier)
        logger.info("[Seed] [Supplier] [CREATED] - Kerala Agro Traders")
    else:
        logger.info("[Seed] [Supplier] [EXISTS] - Kerala Agro Traders")
    await db.flush()

    # Inventory Items
    items_to_seed = [
        {"name": "Pachari (Raw Rice)", "category": "Provisions", "unit": "kg", "min": 50.0, "price": 42.0},
        {"name": "Velichenna (Coconut Oil)", "category": "Oils", "unit": "litre", "min": 20.0, "price": 180.0},
        {"name": "Karpuram (Camphor)", "category": "Puja Items", "unit": "packet", "min": 5.0, "price": 95.0}
    ]
    
    for i_data in items_to_seed:
        result = await db.execute(select(InventoryItem).filter_by(temple_id=temple.id, name=i_data["name"]))
        item = result.scalars().first()
        if not item:
            item = InventoryItem(
                id=uuid.uuid4(),
                temple_id=temple.id,
                name=i_data["name"],
                category=i_data["category"],
                unit=i_data["unit"],
                min_stock=i_data["min"],
                unit_price=i_data["price"],
                supplier_id=supplier.id,
                location_id=loc_main.id,
                is_active=True
            )
            db.add(item)
            await db.flush()
            
            # Stock balance
            stock = KalavaraStock(
                id=uuid.uuid4(),
                temple_id=temple.id,
                item_id=item.id,
                quantity=100.0,  # Seed initial stock of 100 units
                location_id=loc_main.id
            )
            db.add(stock)
            logger.info(f"[Seed] [InventoryItem] [CREATED] - {i_data['name']} (Stock: 100)")
        else:
            logger.info(f"[Seed] [InventoryItem] [EXISTS] - {i_data['name']}")
    await db.flush()
