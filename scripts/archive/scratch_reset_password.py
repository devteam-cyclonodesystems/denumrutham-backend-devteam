import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

import app.models
from app.core.database import AsyncSessionLocal
from app.models.domain import User
from app.core.security import get_password_hash, verify_password
from sqlalchemy.future import select

async def reset_admin_password():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).filter(User.user_id == 'admin'))
        user = res.scalars().first()
        if not user:
            print("Admin user not found.")
            return

        password = "AdminPassword123!"
        new_hash = get_password_hash(password)
        user.password_hash = new_hash
        await db.commit()
        print(f"Password for 'admin' reset to '{password}'")
        
        # Verify immediately
        matches = verify_password(password, new_hash)
        print(f"Verification test: {'SUCCESS' if matches else 'FAILED'}")

if __name__ == "__main__":
    asyncio.run(reset_admin_password())
