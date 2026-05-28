import asyncio
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.domain import User
from sqlalchemy import select

async def list_users():
    print(f"DATABASE_URL: {settings.DATABASE_URL}")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()
        print(f"Total users: {len(users)}")
        for u in users:
            print(f"|{u.user_id}| (Role: {u.role}, Tenant: {u.tenant_id})")

if __name__ == "__main__":
    asyncio.run(list_users())
