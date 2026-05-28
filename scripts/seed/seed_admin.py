import uuid
import logging
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import get_password_hash
from app.models.domain import User
from app.models.system_rbac import SystemRole

logger = logging.getLogger("Seed.Admin")

async def seed_admin(db: AsyncSession) -> User:
    # 1. Ensure SUPER_ADMIN role exists
    result = await db.execute(select(SystemRole).filter(SystemRole.name == "SUPER_ADMIN"))
    super_admin_role = result.scalars().first()
    if not super_admin_role:
        logger.error("[Seed] [Admin] [FAILED] - SUPER_ADMIN role not found in system_roles. Please run RBAC seed first.")
        raise ValueError("SUPER_ADMIN role not found in system_roles. Run RBAC seed first.")

    # 2. Check if admin user already exists
    admin_id = "admin"
    admin_email = "admin@denumrutham.com"
    result = await db.execute(select(User).filter((User.user_id == admin_id) | (User.email == admin_email)))
    admin = result.scalars().first()
    
    if admin:
        logger.info("[Seed] [Admin] [EXISTS] - Super Admin already exists.")
        return admin

    # 3. Create Super Admin
    temp_pass = "DenumruthamAdmin@2026"
    admin = User(
        id=uuid.uuid4(),
        user_id=admin_id,
        name="Global Super Admin",
        email=admin_email,
        phone="+919999999999",
        password_hash=get_password_hash(temp_pass),
        role="SUPER_ADMIN",
        system_role_id=super_admin_role.id,
        status="ACTIVE",
        is_active=True,
        approval_status="APPROVED",
    )
    db.add(admin)
    await db.flush()
    logger.info(f"[Seed] [Admin] [CREATED] - Username: {admin_id}, Password: {temp_pass}")
    return admin
