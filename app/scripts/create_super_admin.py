import asyncio
import os
import sys

# Ensure app is importable
sys.path.insert(0, os.getcwd())

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.domain import User
from app.models.system_rbac import SystemRole
from sqlalchemy.future import select

async def main():
    print("🚀 Creating Single Super Admin...")
    
    async with AsyncSessionLocal() as db:
        # 1. Get SUPER_ADMIN role
        result = await db.execute(select(SystemRole).filter(SystemRole.name == "SUPER_ADMIN"))
        role = result.scalars().first()
        
        if not role:
            print("❌ Error: SUPER_ADMIN role not found in system_roles table.")
            print("Please run 'python -m app.scripts.seed_system_rbac' first.")
            return

        # 2. Check for existing super admin
        email = "superadmin@denumrutham.com"
        result = await db.execute(select(User).filter(User.email == email))
        user = result.scalars().first()
        
        if user:
            print(f"ℹ️ User {email} already exists. Updating to ensure clean state...")
            user.user_id = "superadmin"
            user.password_hash = get_password_hash("Superadmin@123")
            user.system_role_id = role.id
            user.status = "ACTIVE"
            user.is_active = True
            user.role = "SUPER_ADMIN" # Sync with legacy field
            user.temple_id = None
        else:
            print(f"🆕 Creating new user: {email}")
            user = User(
                user_id="superadmin",
                email=email,
                name="System Super Admin",
                password_hash=get_password_hash("Superadmin@123"),
                system_role_id=role.id,
                status="ACTIVE",
                is_active=True,
                role="SUPER_ADMIN",
                temple_id=None
            )
            db.add(user)
        
        await db.commit()
        print(f"✅ Success: Super Admin '{email}' created/reset successfully.")
        print("Password: Superadmin@123")

if __name__ == "__main__":
    asyncio.run(main())
