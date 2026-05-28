import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.domain import InventoryItem, Supplier

async def run():
    async with AsyncSessionLocal() as db:
        items = await db.execute(select(InventoryItem))
        print('ITEMS:', [(i.name, i.temple_id, i.unit_price) for i in items.scalars()])
        
        sups = await db.execute(select(Supplier))
        print('SUPS:', [(s.name, s.temple_id, s.items_supplied) for s in sups.scalars()])

asyncio.run(run())
