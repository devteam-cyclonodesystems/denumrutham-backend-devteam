import asyncio
import os
import sys
import uuid
from sqlalchemy import select

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.domain import Temple, User, TempleProfile

async def add_requested_data():
    print("Adding Temple and Admin user...")
    async with AsyncSessionLocal() as db:
        # 1. Add Temple
        temple_name = "Mallottu Sree Bhadrakali Devi Temple"
        temple_domain = "mallottu-bhadrakali"
        
        result = await db.execute(select(Temple).where(Temple.name == temple_name))
        temple = result.scalars().first()
        
        if not temple:
            temple = Temple(
                name=temple_name,
                domain=temple_domain,
                location="Mallottu, Thrissur",
                state="Kerala",
                status="active"
            )
            db.add(temple)
            await db.flush()
            print(f"  [OK] Created Temple: {temple_name}")
            
            # Add basic profile
            profile = TempleProfile(
                temple_id=temple.id,
                description="Ancient temple dedicated to Goddess Bhadrakali.",
                district="Thrissur",
                state="Kerala"
            )
            db.add(profile)
        else:
            print(f"  [INFO] Temple '{temple_name}' already exists.")

        # 2. Add User
        user_id = "admin"
        password = "admin123"
        
        result = await db.execute(select(User).where(User.user_id == user_id))
        user = result.scalars().first()
        
        if not user:
            user = User(
                user_id=user_id,
                password_hash=get_password_hash(password),
                role="SUPERADMIN",
                temple_id=temple.id
            )
            db.add(user)
            print(f"  [OK] Created User: {user_id} (SUPERADMIN)")
        else:
            user.role = "SUPERADMIN"
            user.password_hash = get_password_hash(password)
            user.temple_id = temple.id
            print(f"  [OK] Updated existing User '{user_id}' to SUPERADMIN.")

        await db.commit()
    print("Done.")

if __name__ == "__main__":
    asyncio.run(add_requested_data())
