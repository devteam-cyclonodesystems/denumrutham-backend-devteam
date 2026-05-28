
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.archana import ArchanaCatalog
from sqlalchemy import select

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(ArchanaCatalog).filter(ArchanaCatalog.name.ilike('%RITUAL ITEM%')))
        items = res.scalars().all()
        for i in items:
            print(f"ITEM: {i.id}, NAME: {i.name}, TEMPLE: {i.temple_id}")

if __name__ == "__main__":
    asyncio.run(check())
