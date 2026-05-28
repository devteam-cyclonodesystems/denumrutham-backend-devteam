from datetime import datetime, timezone, timedelta
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.domain import Temple, InventoryInvoice, ProcurementGRN, StoreSalesOrder, InventoryStockLedger

def get_ist_now():
    # Temple operational timezone is Asia/Kolkata (IST)
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist)

async def generate_document_number(db: AsyncSession, temple_id: UUID, prefix: str) -> str:
    """
    Generates a race-free daily sequential document number using a parent record lock.
    Format: {PREFIX}-{YYMMDD}-{SEQ} (e.g., INV-260523-01, GRN-260523-01)
    """
    # 1. Lock the temple row to serialize number generation for this tenant
    temple_res = await db.execute(
        select(Temple).filter(Temple.id == temple_id).with_for_update()
    )
    temple = temple_res.scalars().first()
    if not temple:
        raise ValueError("Temple not found for document sequence generation")

    # 2. Get daily date string in YYMMDD format
    now_ist = get_ist_now()
    date_str = now_ist.strftime("%y%m%d")
    
    # Calculate start and end of current day in UTC (for querying database records stored in UTC)
    start_of_day = datetime(now_ist.year, now_ist.month, now_ist.day, 0, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)
    end_of_day = datetime(now_ist.year, now_ist.month, now_ist.day, 23, 59, 59, tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)

    # 3. Query document count based on prefix
    count = 0
    if prefix == "INV":
        count_res = await db.execute(
            select(func.count(InventoryInvoice.id)).filter(
                InventoryInvoice.temple_id == temple_id,
                InventoryInvoice.created_at >= start_of_day,
                InventoryInvoice.created_at <= end_of_day
            )
        )
        count = count_res.scalar() or 0
    elif prefix == "GRN":
        count_res = await db.execute(
            select(func.count(ProcurementGRN.id)).filter(
                ProcurementGRN.temple_id == temple_id,
                ProcurementGRN.created_at >= start_of_day,
                ProcurementGRN.created_at <= end_of_day
            )
        )
        count = count_res.scalar() or 0
    elif prefix == "SO":
        count_res = await db.execute(
            select(func.count(StoreSalesOrder.id)).filter(
                StoreSalesOrder.temple_id == temple_id,
                StoreSalesOrder.created_at >= start_of_day,
                StoreSalesOrder.created_at <= end_of_day
            )
        )
        count = count_res.scalar() or 0
    else:
        # Default fallback to ledger counts for adjustments/misc
        count_res = await db.execute(
            select(func.count(InventoryStockLedger.id)).filter(
                InventoryStockLedger.temple_id == temple_id,
                InventoryStockLedger.timestamp >= start_of_day,
                InventoryStockLedger.timestamp <= end_of_day
            )
        )
        count = count_res.scalar() or 0

    # 4. Return formatted daily sequential ID
    seq = str(count + 1).zfill(3)
    return f"{prefix}-{date_str}-{seq}"
