import asyncio
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models.domain import InventoryItem, Supplier

async def sync():
    async with AsyncSessionLocal() as db:
        sups = await db.execute(select(Supplier))
        for sup in sups.scalars():
            if sup.items_supplied:
                for part in sup.items_supplied.split(','):
                    name = part.split('(')[0].strip()
                    # Case-insensitive lookup
                    item_res = await db.execute(select(InventoryItem).filter(func.lower(InventoryItem.name) == func.lower(name)))
                    existing = item_res.scalars().first()
                    
                    price = 0.0
                    try:
                        price = float(part.split('₹')[1].strip())
                    except: pass
                    
                    if not existing:
                        unit = "unit"
                        try:
                            unit = part.split('(')[1].split(')')[0].strip()
                        except: pass
                        
                        new_item = InventoryItem(
                            temple_id=sup.temple_id,
                            name=name,
                            category="Supplier Item",
                            unit=unit,
                            min_stock=10,
                            stock=0,
                            unit_price=price,
                            remarks="Auto-created case-insensitive sync"
                        )
                        db.add(new_item)
                        print(f"Created: {name} @ {price}")
                    else:
                        existing.unit_price = price
                        print(f"Updated: {existing.name} unit price to {price}")
        await db.commit()

asyncio.run(sync())
