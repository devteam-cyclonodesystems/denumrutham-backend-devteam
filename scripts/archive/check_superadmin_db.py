import asyncio
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.domain import User

async def check():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).filter(User.user_id == "superadmin"))
        user = result.scalars().first()
        if user:
            print(f"FOUND: {user.user_id}, Role: {user.role}, Temple ID: {user.temple_id}")
        else:
            print("NOT FOUND")

if __name__ == "__main__":
    asyncio.run(check())
