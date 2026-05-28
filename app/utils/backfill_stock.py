import asyncio
import logging
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.domain import InventoryItem, KalavaraStock

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_stock")

async def backfill():
    async with AsyncSessionLocal() as session:
        # Load all inventory items
        result = await session.execute(select(InventoryItem))
        items = result.scalars().all()
        logger.info(f"Found {len(items)} items in kalavara_inventory_items")

        backfilled_count = 0
        skipped_count = 0

        for item in items:
            # Check if stock already exists
            stock_result = await session.execute(
                select(KalavaraStock).where(
                    KalavaraStock.item_id == item.id,
                    KalavaraStock.temple_id == item.temple_id
                )
            )
            existing_stock = stock_result.scalars().first()

            if not existing_stock:
                # Create a new stock row
                new_stock = KalavaraStock(
                    temple_id=item.temple_id,
                    item_id=item.id,
                    quantity=item.stock or 0.0,
                    location_id=item.location_id,
                    version_number=1
                )
                session.add(new_stock)
                backfilled_count += 1
            else:
                skipped_count += 1

        if backfilled_count > 0:
            await session.commit()
            logger.info(f"Successfully backfilled {backfilled_count} items into kalavara_stock")
        else:
            logger.info("No items needed backfilling")
            
        logger.info(f"Skipped {skipped_count} existing stock rows")

if __name__ == "__main__":
    asyncio.run(backfill())
