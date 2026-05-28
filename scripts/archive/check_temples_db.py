import asyncio
from app.core.database import AsyncSessionLocal
from app.models.domain import Temple
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Temple))
        temples = result.scalars().all()
        print(f"Total temples: {len(temples)}")
        for t in temples:
            print(f"ID: {t.id} | Name: {t.name} | Status: {t.status} | Is Active: {t.is_active}")

if __name__ == "__main__":
    asyncio.run(main())
