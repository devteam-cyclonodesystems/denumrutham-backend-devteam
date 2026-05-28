import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.domain import (
    StoreStockReservation, StoreStock, InventoryStockLedger,
    InventoryMovementType, AuditLog, StoreProduct
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tms.tasks.background_jobs")

def utcnow():
    return datetime.now(timezone.utc)

async def cleanup_expired_reservations():
    """Background task to release expired stock reservations."""
    logger.info("Running cleanup worker for stale reservations...")
    async with AsyncSessionLocal() as session:
        # Fetch active reservations that have expired
        now = utcnow()
        result = await session.execute(
            select(StoreStockReservation)
            .filter(
                StoreStockReservation.reservation_status == "RESERVED",
                StoreStockReservation.expires_at < now
            )
        )
        expired_reservations = result.scalars().all()
        logger.info(f"Found {len(expired_reservations)} expired reservations")

        released_count = 0

        for reservation in expired_reservations:
            try:
                # Transition status to RELEASED
                reservation.reservation_status = "RELEASED"

                # Restore available stock
                stock_result = await session.execute(
                    select(StoreStock).filter(
                        StoreStock.product_id == reservation.product_id,
                        StoreStock.temple_id == reservation.temple_id
                    )
                )
                stock = stock_result.scalars().first()
                if stock:
                    before_stock = stock.quantity
                    after_stock = before_stock + reservation.quantity_reserved
                    stock.quantity = after_stock
                    stock.version_number += 1
                else:
                    # In case stock row doesn't exist, create it
                    stock = StoreStock(
                        temple_id=reservation.temple_id,
                        product_id=reservation.product_id,
                        quantity=reservation.quantity_reserved,
                        location_id=reservation.location_id,
                        version_number=1
                    )
                    session.add(stock)
                    await session.flush()
                    before_stock = 0.0
                    after_stock = reservation.quantity_reserved

                # Fetch product name for ledger
                prod_result = await session.execute(
                    select(StoreProduct).filter(StoreProduct.id == reservation.product_id)
                )
                product = prod_result.scalars().first()
                product_name = product.name if product else "Unknown Product"

                # Generate ledger event (AUCTION_RELEASE)
                ledger_entry = InventoryStockLedger(
                    temple_id=reservation.temple_id,
                    domain_type="STORE",
                    store_product_id=reservation.product_id,
                    kalavara_item_id=None,
                    item_name=product_name,
                    location_id=reservation.location_id or (stock.location_id if stock else None),
                    movement_type=InventoryMovementType.AUCTION_RELEASE,
                    quantity_change=reservation.quantity_reserved,
                    before_stock=before_stock,
                    after_stock=after_stock,
                    reference_type="RESERVATION_RELEASE",
                    reference_id=str(reservation.id),
                    remarks=f"Stale reservation {reservation.id} expired and stock released"
                )
                session.add(ledger_entry)

                # Generate Audit Log
                audit_entry = AuditLog(
                    temple_id=reservation.temple_id,
                    user_id=None,
                    role="SYSTEM",
                    module_name="STORE",
                    action="RELEASE_RESERVATION",
                    action_type="SYSTEM",
                    entity_id=str(reservation.id),
                    details=f"Released reservation {reservation.id} of {reservation.quantity_reserved} units of product {reservation.product_id} due to expiry"
                )
                session.add(audit_entry)

                released_count += 1
            except Exception as e:
                logger.error(f"Error releasing reservation {reservation.id}: {e}")
                # Rollback this iteration's changes if needed, but continue other items
                continue

        if released_count > 0:
            await session.commit()
            logger.info(f"Released {released_count} stale reservations successfully")
        else:
            logger.info("No stale reservations found")

async def start_reservation_cleanup_loop(interval_seconds: int = 60):
    """Loop runner for reservation cleanup."""
    while True:
        try:
            await cleanup_expired_reservations()
        except Exception as e:
            logger.error(f"Error in cleanup worker loop: {e}")
        await asyncio.sleep(interval_seconds)
