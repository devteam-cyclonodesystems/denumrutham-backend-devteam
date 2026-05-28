import asyncio
from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.domain import User
from app.models.system_rbac import SystemRole
from sqlalchemy.future import select
from uuid import UUID

async def fix_admin_accounts():
    print("Repairing System Governance Accounts...")
    async with AsyncSessionLocal() as db:
        # 1. Fetch System Roles
        role_res = await db.execute(select(SystemRole).filter(SystemRole.name == "SUPER_ADMIN"))
        super_admin_role = role_res.scalars().first()
        
        # 2. Fix 'superadmin' legacy account
        res = await db.execute(select(User).filter(User.user_id == 'superadmin'))
        user = res.scalars().first()
        if user:
            user.password_hash = get_password_hash("superadmin123")
            user.status = "ACTIVE"
            user.is_active = True
            user.role = "SUPER_ADMIN" # Unified role
            if super_admin_role:
                user.system_role_id = super_admin_role.id
            print(f"Fixed 'superadmin' account (Role: {user.role}, Status: {user.status})")
        
        # 3. Fix 'superadmin@denumrutham.com' account
        res = await db.execute(select(User).filter(User.user_id == 'superadmin@denumrutham.com'))
        user_email = res.scalars().first()
        if user_email:
            user_email.password_hash = get_password_hash("superadmin123")
            user_email.status = "ACTIVE"
            user_email.is_active = True
            user_email.role = "SUPER_ADMIN"
            if super_admin_role:
                user_email.system_role_id = super_admin_role.id
            print(f"Fixed 'superadmin@denumrutham.com' account (Role: {user_email.role}, Status: {user_email.status})")

        # 4. Ensure all Temple Admins are active
        res = await db.execute(select(User).filter(User.role.in_(['ADMIN', 'TEMPLE_MANAGER'])))
        admins = res.scalars().all()
        for admin in admins:
            admin.is_active = True
            admin.status = "ACTIVE"
        print(f"Activated {len(admins)} temple administrators.")

        await db.commit()
    print("System Governance Accounts repaired successfully.")

if __name__ == "__main__":
    asyncio.run(fix_admin_accounts())
