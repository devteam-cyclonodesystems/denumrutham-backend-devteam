"""
Seed Complete — Production-grade sample data for Temple Management System.

Creates:
- 1 SUPER_ADMIN user
- 2 Temples (1 APPROVED, 1 PENDING)
- 2 TEMPLE_MANAGER users
- 2 STAFF users (1 ACTIVE, 1 PENDING)
- 2 DEVOTEE users
- Sample services, bookings, change requests

Usage:
    python -m app.seed_complete
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.domain import (
    User, Temple, UserTemple, TempleProfile, DevoteeProfile,
    TempleService, ServiceType, ChangeRequest, TempleFollower,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed():
    async with AsyncSessionLocal() as db:
        # ── Check if already seeded ───────────────────────────────────
        existing = await db.execute(select(User).filter(User.role == "SUPERADMIN"))
        if existing.scalars().first():
            logger.info("Database already seeded. Skipping.")
            return

        logger.info("Seeding database with sample data...")

        # ══════════════════════════════════════════════════════════════
        # 1. SUPER_ADMIN
        # ══════════════════════════════════════════════════════════════
        superadmin = User(
            id=uuid4(),
            user_id="admin@tms.com",
            name="System Admin",
            email="admin@tms.com",
            phone=None,
            password_hash=get_password_hash("Admin@123"),
            role="SUPERADMIN",
            status="ACTIVE",
        )
        db.add(superadmin)
        await db.flush()
        logger.info("Created SUPERADMIN: admin@tms.com / Admin@123")

        # ══════════════════════════════════════════════════════════════
        # 2. TEMPLES
        # ══════════════════════════════════════════════════════════════
        temple1 = Temple(
            id=uuid4(),
            name="Mallottu Sree Bhadrakali Devi Temple",
            domain="mallottu-sree-bhadrakali",
            location="Mallottu, Pathanamthitta",
            state="Kerala",
            district="Pathanamthitta",
            contact_number="9876543210",
            email="info@mallottutemple.com",
            description="Ancient temple dedicated to Goddess Bhadrakali",
            status="APPROVED",
            created_by=superadmin.id,
        )
        db.add(temple1)

        temple2 = Temple(
            id=uuid4(),
            name="Sri Krishna Swamy Temple Guruvayur",
            domain="sri-krishna-guruvayur",
            location="Guruvayur, Thrissur",
            state="Kerala",
            district="Thrissur",
            contact_number="9876543211",
            email="info@guruvayurtemple.com",
            description="Famous Krishna temple in Guruvayur",
            status="PENDING",
            created_by=superadmin.id,
        )
        db.add(temple2)
        await db.flush()

        # Temple profiles
        for temple, desc, history in [
            (temple1, "Mallottu Sree Bhadrakali Devi Temple is an ancient temple...",
             "Established centuries ago in the Pathanamthitta district..."),
            (temple2, "The world-famous Sri Krishna Temple at Guruvayur...",
             "One of the most important pilgrimage centers in India..."),
        ]:
            profile = TempleProfile(
                temple_id=temple.id,
                description=desc,
                history=history,
                location=temple.location,
                district=temple.district,
                state=temple.state,
                contact_number=temple.contact_number,
                email=temple.email,
                opening_time="05:00",
                closing_time="21:00",
            )
            db.add(profile)

        logger.info("Created 2 temples (1 APPROVED, 1 PENDING)")

        # ══════════════════════════════════════════════════════════════
        # 3. TEMPLE_MANAGER users
        # ══════════════════════════════════════════════════════════════
        manager1 = User(
            id=uuid4(),
            user_id="manager@mallottu.com",
            name="Rajan Nair",
            email="manager@mallottu.com",
            phone="9111111111",
            password_hash=get_password_hash("Manager@123"),
            role="TEMPLE_MANAGER",
            status="ACTIVE",
            temple_id=temple1.id,
        )
        db.add(manager1)

        manager2 = User(
            id=uuid4(),
            user_id="manager@guruvayur.com",
            name="Krishnan Menon",
            email="manager@guruvayur.com",
            phone="9222222222",
            password_hash=get_password_hash("Manager@123"),
            role="TEMPLE_MANAGER",
            status="ACTIVE",
            temple_id=temple2.id,
        )
        db.add(manager2)
        await db.flush()

        # UserTemple mappings
        for user, temple in [(manager1, temple1), (manager2, temple2)]:
            mapping = UserTemple(user_id=user.id, temple_id=temple.id, role="TEMPLE_MANAGER")
            db.add(mapping)

        logger.info("Created 2 TEMPLE_MANAGER users")

        # ══════════════════════════════════════════════════════════════
        # 4. STAFF users
        # ══════════════════════════════════════════════════════════════
        staff1 = User(
            id=uuid4(),
            user_id="staff@mallottu.com",
            name="Suresh Kumar",
            email="staff@mallottu.com",
            phone="9333333333",
            password_hash=get_password_hash("Staff@123"),
            role="STAFF",
            status="ACTIVE",
            temple_id=temple1.id,
        )
        db.add(staff1)

        staff2_pending = User(
            id=uuid4(),
            user_id="newstaff@mallottu.com",
            name="Arun Mohan",
            email="newstaff@mallottu.com",
            phone="9444444444",
            password_hash=get_password_hash("Staff@123"),
            role="STAFF",
            status="PENDING",
            temple_id=temple1.id,
        )
        db.add(staff2_pending)
        await db.flush()

        for user in [staff1, staff2_pending]:
            mapping = UserTemple(user_id=user.id, temple_id=temple1.id, role="STAFF")
            db.add(mapping)

        logger.info("Created 2 STAFF users (1 ACTIVE, 1 PENDING)")

        # ══════════════════════════════════════════════════════════════
        # 5. DEVOTEE users
        # ══════════════════════════════════════════════════════════════
        devotee1 = User(
            id=uuid4(),
            user_id="9555555555",
            name="Lakshmi Devi",
            email=None,
            phone="9555555555",
            password_hash=get_password_hash("Devotee@123"),
            role="DEVOTEE",
            status="ACTIVE",
        )
        db.add(devotee1)

        devotee2 = User(
            id=uuid4(),
            user_id="devotee@gmail.com",
            name="Raghav Pillai",
            email="devotee@gmail.com",
            phone="9666666666",
            password_hash=get_password_hash("Devotee@123"),
            role="DEVOTEE",
            status="ACTIVE",
        )
        db.add(devotee2)
        await db.flush()

        # Devotee profiles
        for user, nakshatra, gothram in [
            (devotee1, "Ashwini", "Bharadwaja"),
            (devotee2, "Rohini", "Kashyapa"),
        ]:
            profile = DevoteeProfile(
                user_id=user.id,
                name=user.name,
                nakshatra=nakshatra,
                gothram=gothram,
            )
            db.add(profile)

        logger.info("Created 2 DEVOTEE users")

        # ══════════════════════════════════════════════════════════════
        # 6. TEMPLE SERVICES
        # ══════════════════════════════════════════════════════════════
        services_data = [
            ("Ganapathi Homam", ServiceType.ARCHANA, 500.0, temple1.id),
            ("Sahasranama Archana", ServiceType.ARCHANA, 300.0, temple1.id),
            ("Pushpanjali", ServiceType.OFFERING, 100.0, temple1.id),
            ("Vazhipadu - Nivedyam", ServiceType.OFFERING, 250.0, temple1.id),
            ("Community Hall Booking", ServiceType.HALL_BOOKING, 5000.0, temple1.id),
            ("General Donation", ServiceType.DONATION, 0.0, temple1.id),
            ("Prasadam Box", ServiceType.STORE, 150.0, temple1.id),
        ]
        for name, stype, price, tid in services_data:
            srv = TempleService(
                temple_id=tid,
                service_name=name,
                service_type=stype,
                price=price,
                description=f"{name} service",
                active=True,
            )
            db.add(srv)

        logger.info("Created %d temple services", len(services_data))

        # ══════════════════════════════════════════════════════════════
        # 7. TEMPLE FOLLOWERS
        # ══════════════════════════════════════════════════════════════
        follow1 = TempleFollower(user_id=devotee1.id, temple_id=temple1.id)
        follow2 = TempleFollower(user_id=devotee2.id, temple_id=temple1.id)
        db.add(follow1)
        db.add(follow2)
        logger.info("Created 2 temple followers")

        # ══════════════════════════════════════════════════════════════
        # 8. SAMPLE CHANGE REQUEST
        # ══════════════════════════════════════════════════════════════
        cr = ChangeRequest(
            entity_type="temple",
            entity_id=str(temple1.id),
            field_name="contact_number",
            old_value="9876543210",
            new_value="9876543299",
            requested_by=staff1.id,
            status="PENDING",
            temple_id=temple1.id,
        )
        db.add(cr)
        logger.info("Created 1 sample change request")

        # ── Commit everything ─────────────────────────────────────────
        await db.commit()
        logger.info("=" * 60)
        logger.info("SEED DATA COMPLETE")
        logger.info("=" * 60)
        logger.info("")
        logger.info("LOGIN CREDENTIALS:")
        logger.info("  SUPERADMIN:      admin@tms.com / Admin@123")
        logger.info("  TEMPLE_MANAGER:  manager@mallottu.com / Manager@123")
        logger.info("  TEMPLE_MANAGER:  manager@guruvayur.com / Manager@123")
        logger.info("  STAFF (active):  staff@mallottu.com / Staff@123")
        logger.info("  STAFF (pending): newstaff@mallottu.com / Staff@123")
        logger.info("  DEVOTEE:         9555555555 / Devotee@123")
        logger.info("  DEVOTEE:         devotee@gmail.com / Devotee@123")
        logger.info("")


if __name__ == "__main__":
    asyncio.run(seed())
