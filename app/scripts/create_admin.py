import asyncio
import uuid
import sys
import os

# Ensure the parent directory containing 'app' is resolvable
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.domain import User, Temple
from app.core.security import get_password_hash
from app.models.rbac import Role, UserRole

async def create_admin():
    async with AsyncSessionLocal() as session:
        # Check if a temple already exists
        result = await session.execute(select(Temple).limit(1))
        temple = result.scalar_one_or_none()
        
        if not temple:
            temple_id = uuid.uuid4()
            temple = Temple(
                id=temple_id,
                name="Default Temple",
                domain="admin_temple_domain"
            )
            session.add(temple)
            await session.flush()
        else:
            temple_id = temple.id

        # Check if admin already exists
        result = await session.execute(select(User).filter_by(user_id="superadmin@temple"))
        admin_user = result.scalar_one_or_none()

        if not admin_user:
            admin_user = User(
                user_id="superadmin@temple",
                password_hash=get_password_hash("admin@123"),
                role="ADMIN",
                temple_id=temple_id
            )
            session.add(admin_user)
            await session.commit()
            print("[SUCCESS] Admin user (superadmin@temple) created successfully")
        else:
            # FIX: Update password hash if user exists
            admin_user.password_hash = get_password_hash("admin@123")
            await session.commit()
            print("[SUCCESS] Admin user (superadmin@temple) updated successfully")
            
        # Check if Festival Coordinator role exists
        result_role = await session.execute(select(Role).filter_by(name="Festival Coordinator", temple_id=temple_id))
        fest_role = result_role.scalar_one_or_none()
        
        if not fest_role:
            print("[INFO] 'Festival Coordinator' role not found. Creating it now...")
            fest_role = Role(name="Festival Coordinator", temple_id=temple_id, description="Coordinates festivals")
            session.add(fest_role)
            await session.flush()
            
        # Check if festcord exists
        result = await session.execute(select(User).filter_by(user_id="festcord@temple"))
        fest_user = result.scalar_one_or_none()

        if not fest_user:
            fest_user = User(
                user_id="festcord@temple",
                password_hash=get_password_hash("festcord123"),
                role="STAFF", # Base role, RBAC adds specific permissions
                temple_id=temple_id
            )
            session.add(fest_user)
            await session.flush() # Get user ID
            
            # Assign role
            user_role = UserRole(user_id=fest_user.id, role_id=fest_role.id, temple_id=temple_id)
            session.add(user_role)
            await session.commit()
            print("[SUCCESS] Test user (festcord@temple) created and assigned Festival Coordinator role")
        else:
            # FIX: Update password hash if user exists
            fest_user.password_hash = get_password_hash("festcord123")
            await session.commit()
            print("[SUCCESS] Test user (festcord@temple) updated successfully")

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            from asyncio import WindowsSelectorEventLoopPolicy
            asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
        except ImportError:
            pass
    asyncio.run(create_admin())