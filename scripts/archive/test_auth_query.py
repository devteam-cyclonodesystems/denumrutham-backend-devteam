import asyncio
from app.core.database import AsyncSessionLocal
from app.models.domain import User
from sqlalchemy import select

async def test_auth_query(username: str):
    async with AsyncSessionLocal() as db:
        print(f"Testing find for: '{username}'")
        result = await db.execute(select(User).filter(User.user_id == username))
        user = result.scalars().first()
        if user:
            print(f"FOUND: {user.user_id} (ID: {user.id})")
        else:
            print("NOT FOUND")
            # List all users for debugging
            result = await db.execute(select(User.user_id))
            all_ids = result.scalars().all()
            print(f"Current User IDs in DB: {all_ids}")

if __name__ == "__main__":
    asyncio.run(test_auth_query("superadmin"))
