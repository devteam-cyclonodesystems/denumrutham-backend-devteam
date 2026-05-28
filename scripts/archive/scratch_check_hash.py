import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

import app.models
from app.core.database import AsyncSessionLocal
from app.models.domain import User
from sqlalchemy.future import select

async def check_hash():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).filter(User.user_id == 'admin'))
        user = res.scalars().first()
        if user:
            print(f"USER_ID: {user.user_id}")
            print(f"HASH:    {user.password_hash}")
        else:
            print("User not found")

if __name__ == "__main__":
    asyncio.run(check_hash())
