import uuid
import logging
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_password_hash
from app.models.domain import User, Temple, UserTemple, TempleProfile
from app.models.operational_states import TempleOperationalState
from app.models.system_rbac import SystemRole

logger = logging.getLogger("Seed.Temples")

async def seed_temples(db: AsyncSession, admin: User) -> Temple:
    # 1. Check if temple already exists
    temple_name = "Sree Dharma Sastha Demo Temple"
    temple_domain = "demo-temple"
    
    result = await db.execute(select(Temple).filter((Temple.name == temple_name) | (Temple.domain == temple_domain)))
    temple = result.scalars().first()
    
    if temple:
        logger.info("[Seed] [Temple] [EXISTS] - Demo Temple already exists.")
        return temple

    # 2. Create Temple
    temple = Temple(
        id=uuid.uuid4(),
        name=temple_name,
        domain=temple_domain,
        location="Sabarimala, Kerala",
        state="Kerala",
        district="Pathanamthitta",
        contact_number="+914842345678",
        email="info@demotemple.org",
        description="A beautiful demo temple for platform testing.",
        temple_code="TMP-20260528-001",
        status="APPROVED",
        is_active=True,
        operational_state=TempleOperationalState.ACTIVE,
        created_by=admin.id,
        approved_by=admin.id,
    )
    db.add(temple)
    await db.flush()
    logger.info(f"[Seed] [Temple] [CREATED] - Sree Dharma Sastha Demo Temple (Code: {temple.temple_code})")

    # 3. Create Temple Profile
    profile = TempleProfile(
        temple_id=temple.id,
        description="A beautiful demo temple for platform testing.",
        history="Established in 2026 for verifying SaaS platform capabilities.",
        location=temple.location,
        district=temple.district,
        state=temple.state,
        contact_number=temple.contact_number,
        email=temple.email,
        opening_time="04:00",
        closing_time="22:00",
    )
    db.add(profile)
    
    # 4. Create a Demo Temple Manager user
    manager_role = await db.execute(select(SystemRole).filter(SystemRole.name == "TEMPLE_ADMIN"))
    manager_role_obj = manager_role.scalars().first()
    
    manager_id = "manager"
    manager_email = "manager@demotemple.org"
    
    manager_result = await db.execute(select(User).filter((User.user_id == manager_id) | (User.email == manager_email)))
    manager = manager_result.scalars().first()
    
    if not manager:
        manager_pass = "ManagerPass@2026"
        manager = User(
            id=uuid.uuid4(),
            user_id=manager_id,
            name="Demo Temple Manager",
            email=manager_email,
            phone="+919999999998",
            password_hash=get_password_hash(manager_pass),
            role="TEMPLE_MANAGER",
            system_role_id=manager_role_obj.id if manager_role_obj else None,
            status="ACTIVE",
            is_active=True,
            temple_id=temple.id,
            approval_status="APPROVED",
        )
        db.add(manager)
        await db.flush()
        
        # UserTemple mapping
        mapping = UserTemple(
            id=uuid.uuid4(),
            user_id=manager.id,
            temple_id=temple.id,
            role="TEMPLE_MANAGER",
            is_active=True,
        )
        db.add(mapping)
        logger.info(f"[Seed] [Manager] [CREATED] - Username: {manager_id}, Password: {manager_pass}")
    else:
        logger.info("[Seed] [Manager] [EXISTS] - Temple Manager already exists.")
        
    await db.flush()
    return temple
