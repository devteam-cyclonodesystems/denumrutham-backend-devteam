import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

import app.models
from app.core.database import AsyncSessionLocal
from app.models.domain import User
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

async def dump_users():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).options(joinedload(User.system_role)))
        users = res.scalars().all()
        print(f"Total Users: {len(users)}")
        for u in users:
            print(f" - USER_ID: {u.user_id}")
            print(f"   Email:   {u.email}")
            print(f"   Role:    {u.role}")
            print(f"   SysRole: {u.system_role.name if u.system_role else 'None'}")
            print(f"   Status:  {u.status}")
            print(f"   Active:  {u.is_active}")
            print("-" * 20)

if __name__ == "__main__":
    asyncio.run(dump_users())
