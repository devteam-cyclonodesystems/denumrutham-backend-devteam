import asyncio
from app.core.database import AsyncSessionLocal
from app.models.domain import User
from app.core.security import get_password_hash
from sqlalchemy.future import select

async def reset():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).filter(User.user_id == 'superadmin'))
        user = res.scalars().first()
        if not user:
            print("User 'superadmin' not found.")
            return

        user.password_hash = get_password_hash("superadmin123")
        await db.commit()
        print("Password for 'superadmin' reset to 'superadmin123'")

if __name__ == "__main__":
    asyncio.run(reset())
