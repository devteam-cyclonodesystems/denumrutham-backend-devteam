
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.archana import ArchanaCatalog
from app.models.domain import Temple
from sqlalchemy import select

async def check_data():
    async with AsyncSessionLocal() as db:
        # Check Temples
        res = await db.execute(select(Temple))
        temples = res.scalars().all()
        print(f"TEMPLES: {[ (t.id, t.name) for t in temples ]}")
        
        # Check Catalog
        res = await db.execute(select(ArchanaCatalog))
        items = res.scalars().all()
        print(f"CATALOG ITEMS: {[ (i.id, i.name) for i in items ]}")

if __name__ == "__main__":
    asyncio.run(check_data())
