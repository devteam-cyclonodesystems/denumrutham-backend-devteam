import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user, get_current_temple_id
from app.schemas.domain import TokenData
from app.schemas.store import (
    StoreProductCreate, StoreProductResponse, StoreProductUpdate,
    StoreSalesOrderCreate, StoreSalesOrderResponse,
    AuctionListingCreate, AuctionListingResponse, AuctionListingUpdate, AuctionBidResponse
)
from app.models.domain import (
    StoreProduct, StoreStock, StoreSalesOrder, StoreSalesOrderItem,
    AuctionListing, StoreStockReservation, InventoryStockLedger,
    InventoryMovementType, AuditLog, ProcurementStatus,
    InventoryInvoice, KalavaraStock, InventoryItem, AuctionBid
)
from app.services.inventory_service import InventoryService
from app.services.transaction_service import TransactionService
from app.utils.number_generator import generate_document_number

router = APIRouter()
logger = logging.getLogger("tms.api.store_routes")

def utcnow():
    return datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# STORE PRODUCTS (Catalog Management)
# ---------------------------------------------------------------------------

@router.post("/products", response_model=StoreProductResponse, tags=["store"])
async def create_product(
    prod_in: StoreProductCreate,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    
    # Create StoreProduct record
    product = StoreProduct(
        temple_id=tid,
        name=prod_in.name,
        category=prod_in.category,
        unit=prod_in.unit,
        unit_price=prod_in.unit_price,
        supplier_id=prod_in.supplier_id,
        barcode=prod_in.barcode,
        sku=prod_in.sku,
        qr_code=prod_in.qr_code,
        media=prod_in.media or [],
        is_active=True,
        is_archived=False
    )
    db.add(product)
    await db.flush()

    # Create StoreStock record with 0 quantity
    stock = StoreStock(
        temple_id=tid,
        product_id=product.id,
        quantity=0.0,
        version_number=1
    )
    db.add(stock)
    
    await db.commit()
    await db.refresh(product)
    return product


@router.put("/products/{product_id}", response_model=StoreProductResponse, tags=["store"])
async def update_product(
    product_id: UUID,
    prod_in: StoreProductUpdate,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    result = await db.execute(
        select(StoreProduct).filter(
            StoreProduct.id == product_id,
            StoreProduct.temple_id == tid,
            StoreProduct.is_archived == False
        )
    )
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Store product not found")

    update_data = prod_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(product, field, value)

    await db.commit()
    await db.refresh(product)
    return product


@router.get("/products", response_model=List[StoreProductResponse], tags=["store"])
async def list_products(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    result = await db.execute(
        select(StoreProduct).filter(
            StoreProduct.temple_id == tid,
            StoreProduct.is_archived == False
        ).order_by(StoreProduct.name)
    )
    return result.scalars().all()


@router.get("/stock", tags=["store"])
async def get_store_stock(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    result = await db.execute(
        select(StoreStock).filter(StoreStock.temple_id == tid)
    )
    stocks = result.scalars().all()
    return [{"product_id": str(s.product_id), "quantity": s.quantity} for s in stocks]


@router.delete("/products/{product_id}", tags=["store"])
async def archive_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    tid = UUID(str(temple_id))
    result = await db.execute(
        select(StoreProduct).filter(
            StoreProduct.id == product_id,
            StoreProduct.temple_id == tid
        )
    )
    product = result.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Store product not found")
        
    product.is_archived = True
    product.archived_at = utcnow()
    if current_user.sub:
        product.archived_by = UUID(str(current_user.sub))
        
    await db.commit()
    return {"status": "success", "message": "Product archived successfully"}


# ---------------------------------------------------------------------------
# SALES ORDERS (Point of Sale / Checkout)
# ---------------------------------------------------------------------------

@router.post("/orders", response_model=StoreSalesOrderResponse, tags=["store"])
async def create_sales_order(
    order_in: StoreSalesOrderCreate,
    x_idempotency_key: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    tid = UUID(str(temple_id))
    user_uuid = UUID(str(current_user.sub)) if current_user.sub else None
    
    # Resolve Idempotency Key
    idempotency_key = order_in.idempotency_key or x_idempotency_key
    if idempotency_key:
        # Check if already processed
        dup_res = await db.execute(
            select(StoreSalesOrder).filter(
                StoreSalesOrder.idempotency_key == idempotency_key,
                StoreSalesOrder.temple_id == tid
            )
        )
        existing_order = dup_res.scalars().first()
        if existing_order:
            logger.info(f"Replay detected for idempotency key: {idempotency_key}. Returning previous success.")
            return existing_order

    # Start a transactional checkout
    async with db.begin_nested():
        # Generate Sales Order Number
        order_number = await generate_document_number(db, tid, "SO")
        
        # Calculate totals & verify stock
        total_amount = 0.0
        order_items = []
        
        for item in order_in.items:
            # Load product
            prod_res = await db.execute(
                select(StoreProduct).filter(
                    StoreProduct.id == item.product_id,
                    StoreProduct.temple_id == tid
                )
            )
            product = prod_res.scalars().first()
            if not product:
                raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
                
            # Load stock balance (with SELECT FOR UPDATE for concurrency safety)
            stock_res = await db.execute(
                select(StoreStock)
                .filter(StoreStock.product_id == item.product_id, StoreStock.temple_id == tid)
                .with_for_update()
            )
            stock = stock_res.scalars().first()
            if not stock or stock.quantity < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock for {product.name}. Available: {stock.quantity if stock else 0}, Requested: {item.quantity}"
                )
                
            # Perform stock deduction (optimistic lock logic on version check)
            before_stock = stock.quantity
            after_stock = before_stock - item.quantity
            
            stock.quantity = after_stock
            stock.version_number += 1  # Concurrency version update
            
            line_total = item.quantity * item.unit_price
            total_amount += line_total
            
            # Record Ledger Movement (Polymorphic safety)
            ledger_entry = InventoryStockLedger(
                temple_id=tid,
                domain_type="STORE",
                store_product_id=item.product_id,
                kalavara_item_id=None,
                item_name=product.name,
                location_id=stock.location_id,
                movement_type=InventoryMovementType.SALE,
                quantity_change=-item.quantity,
                before_stock=before_stock,
                after_stock=after_stock,
                reference_type="SALES_ORDER",
                reference_id=order_number,
                performed_by=user_uuid,
                remarks=f"POS Sale: Order {order_number}",
                idempotency_key=f"{idempotency_key}-{item.product_id}" if idempotency_key else None
            )
            db.add(ledger_entry)
            
            order_items.append(
                StoreSalesOrderItem(
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    total_price=line_total
                )
            )
            
        # Create Sales Order
        sales_order = StoreSalesOrder(
            temple_id=tid,
            order_number=order_number,
            customer_name=order_in.customer_name,
            customer_phone=order_in.customer_phone,
            total_amount=total_amount,
            payment_mode=order_in.payment_mode,
            status="Completed",
            created_by=user_uuid,
            idempotency_key=idempotency_key
        )
        db.add(sales_order)
        await db.flush()
        
        # Link items
        for order_item in order_items:
            order_item.order_id = sales_order.id
            db.add(order_item)

        # Financial Transaction (POS Income)
        if total_amount > 0:
            await TransactionService.create_transaction(
                db=db,
                temple_id=str(tid),
                txn_type="income",
                category="store",
                amount=total_amount,
                description=f"Store POS Order {order_number}",
                reference_id=order_number,
                source="system"
            )

    await db.commit()
    await db.refresh(sales_order)
    return sales_order


@router.get("/orders", response_model=List[StoreSalesOrderResponse], tags=["store"])
async def list_sales_orders(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    result = await db.execute(
        select(StoreSalesOrder).filter(StoreSalesOrder.temple_id == tid).order_by(StoreSalesOrder.created_at.desc())
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# AUCTION LISTINGS & BIDDING
# ---------------------------------------------------------------------------

@router.post("/auctions", response_model=AuctionListingResponse, tags=["store"])
async def create_auction(
    auc_in: AuctionListingCreate,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    
    # Verify product exists
    prod_res = await db.execute(
        select(StoreProduct).filter(StoreProduct.id == auc_in.product_id, StoreProduct.temple_id == tid)
    )
    product = prod_res.scalars().first()
    if not product:
        raise HTTPException(status_code=404, detail="Store product not found")
        
    # Generate sequential auction code
    count_res = await db.execute(
        select(func.count(AuctionListing.id)).filter(AuctionListing.temple_id == tid)
    )
    count = count_res.scalar() or 0
    now_ist = get_ist_now() if 'get_ist_now' in globals() else datetime.now(timezone(timedelta(hours=5, minutes=30)))
    date_str = now_ist.strftime("%y%m%d")
    auction_code = f"AUC-{date_str}-{str(count + 1).zfill(3)}"

    auction = AuctionListing(
        temple_id=tid,
        product_id=auc_in.product_id,
        auction_code=auction_code,
        quantity=auc_in.quantity,
        start_price=auc_in.start_price,
        current_bid=auc_in.start_price,
        start_time=auc_in.start_time,
        end_time=auc_in.end_time,
        remarks=auc_in.remarks,
        media=auc_in.media or [],
        status="AVAILABLE",
        is_active=True
    )
    db.add(auction)
    await db.flush()

    # Auto-seed stock if insufficient for auction quantity
    stock_res = await db.execute(
        select(StoreStock).filter(StoreStock.product_id == auc_in.product_id, StoreStock.temple_id == tid)
    )
    stock = stock_res.scalars().first()
    if not stock:
        stock = StoreStock(
            temple_id=tid,
            product_id=auc_in.product_id,
            quantity=auc_in.quantity,
            version_number=1
        )
        db.add(stock)
    elif stock.quantity < auc_in.quantity:
        stock.quantity = auc_in.quantity
        stock.version_number += 1

    await db.commit()

    # Load fully with selectinloads
    res = await db.execute(
        select(AuctionListing)
        .options(selectinload(AuctionListing.product), selectinload(AuctionListing.bids))
        .filter(AuctionListing.id == auction.id)
    )
    return res.scalars().first()


@router.get("/auctions", response_model=List[AuctionListingResponse], tags=["store"])
async def list_auctions(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    result = await db.execute(
        select(AuctionListing)
        .options(selectinload(AuctionListing.product), selectinload(AuctionListing.bids))
        .filter(
            AuctionListing.temple_id == tid,
            AuctionListing.is_archived == False
        ).order_by(AuctionListing.created_at.desc())
    )
    return result.scalars().all()


@router.put("/auctions/{auction_id}", response_model=AuctionListingResponse, tags=["store"])
async def update_auction(
    auction_id: UUID,
    auc_in: AuctionListingUpdate,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    result = await db.execute(
        select(AuctionListing)
        .options(selectinload(AuctionListing.product), selectinload(AuctionListing.bids))
        .filter(
            AuctionListing.id == auction_id,
            AuctionListing.temple_id == tid,
            AuctionListing.is_archived == False
        )
    )
    auction = result.scalars().first()
    if not auction:
        raise HTTPException(status_code=404, detail="Auction listing not found")

    update_data = auc_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(auction, field, value)

    # Auto-seed stock if quantity is updated and stock is insufficient
    if "quantity" in update_data:
        stock_res = await db.execute(
            select(StoreStock).filter(StoreStock.product_id == auction.product_id, StoreStock.temple_id == tid)
        )
        stock = stock_res.scalars().first()
        if not stock:
            stock = StoreStock(
                temple_id=tid,
                product_id=auction.product_id,
                quantity=auction.quantity,
                version_number=1
            )
            db.add(stock)
        elif stock.quantity < auction.quantity:
            stock.quantity = auction.quantity
            stock.version_number += 1

    await db.commit()
    
    # Reload fully with relationships
    res = await db.execute(
        select(AuctionListing)
        .options(selectinload(AuctionListing.product), selectinload(AuctionListing.bids))
        .filter(AuctionListing.id == auction.id)
    )
    return res.scalars().first()


@router.post("/auctions/{auction_id}/bid", tags=["store"])
async def place_bid_and_reserve(
    auction_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    """Bidding on an auction places a concurrency-safe stock reservation."""
    tid = UUID(str(temple_id))
    bid_amount = float(payload.get("bid_amount", 0.0))
    bidder_name = payload.get("bidder_name") or "Anonymous Bidder"
    user_uuid = UUID(str(current_user.sub)) if current_user.sub else None
    
    # 1. Load Auction listing
    auc_res = await db.execute(
        select(AuctionListing).filter(AuctionListing.id == auction_id, AuctionListing.temple_id == tid)
    )
    auction = auc_res.scalars().first()
    if not auction:
        raise HTTPException(status_code=404, detail="Auction listing not found")
        
    if auction.status not in ["AVAILABLE", "RESERVED"]:
        raise HTTPException(status_code=400, detail="Auction is no longer active")
        
    if bid_amount <= auction.current_bid:
        raise HTTPException(status_code=400, detail=f"Bid must be higher than current bid: {auction.current_bid}")

    # 2. Concurrency-safe Stock check and Reservation
    async with db.begin_nested():
        # Lock stock row
        stock_res = await db.execute(
            select(StoreStock)
            .filter(StoreStock.product_id == auction.product_id, StoreStock.temple_id == tid)
            .with_for_update()
        )
        stock = stock_res.scalars().first()
        if not stock or stock.quantity < auction.quantity:
            raise HTTPException(status_code=400, detail="Insufficient physical stock in warehouse to lock this auction bid")
            
        # Deduct stock and increment version
        before_stock = stock.quantity
        after_stock = before_stock - auction.quantity
        stock.quantity = after_stock
        stock.version_number += 1
        
        # Update Auction Status & Current Bid
        auction.current_bid = bid_amount
        auction.status = "RESERVED"
        
        # Create AuctionBid record
        bid_record = AuctionBid(
            temple_id=tid,
            auction_id=auction.id,
            bidder_name=bidder_name,
            bid_amount=bid_amount,
            created_at=utcnow()
        )
        db.add(bid_record)

        # Create StoreStockReservation
        # Set 10-minute expiry for auction reservation locks
        expires_at = utcnow() + timedelta(minutes=10)
        
        reservation = StoreStockReservation(
            temple_id=tid,
            product_id=auction.product_id,
            quantity_reserved=auction.quantity,
            reservation_status="RESERVED",
            expires_at=expires_at,
            reference_type="AUCTION",
            reference_id=str(auction.id),
            location_id=stock.location_id
        )
        db.add(reservation)
        await db.flush()
        
        # Record reservation movement in Ledger
        prod_res = await db.execute(select(StoreProduct).filter(StoreProduct.id == auction.product_id))
        product = prod_res.scalars().first()
        
        ledger = InventoryStockLedger(
            temple_id=tid,
            domain_type="STORE",
            store_product_id=auction.product_id,
            kalavara_item_id=None,
            item_name=product.name if product else "Product",
            location_id=stock.location_id,
            movement_type=InventoryMovementType.AUCTION_RESERVATION,
            quantity_change=-auction.quantity,
            before_stock=before_stock,
            after_stock=after_stock,
            reference_type="AUCTION_RESERVATION",
            reference_id=str(reservation.id),
            performed_by=user_uuid,
            remarks=f"Auction bid placed by {bidder_name}: Reservation locked for 10 minutes (Expires {expires_at.strftime('%H:%M:%S')})"
        )
        db.add(ledger)
        
    await db.commit()
    return {"status": "success", "current_bid": auction.current_bid, "reservation_id": reservation.id, "expires_at": expires_at}


@router.post("/auctions/{auction_id}/settle", tags=["store"])
async def settle_auction(
    auction_id: UUID,
    payload: dict,
    x_idempotency_key: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    """Settling an auction confirms the reservation and generates the final Sales Order."""
    tid = UUID(str(temple_id))
    user_uuid = UUID(str(current_user.sub)) if current_user.sub else None
    
    idempotency_key = payload.get("idempotency_key") or x_idempotency_key
    if idempotency_key:
        dup_res = await db.execute(
            select(StoreSalesOrder).filter(
                StoreSalesOrder.idempotency_key == idempotency_key,
                StoreSalesOrder.temple_id == tid
            )
        )
        existing_order = dup_res.scalars().first()
        if existing_order:
            logger.info("Replay detected on auction settlement. Returning previous sales order.")
            return existing_order

    # Load Auction
    auc_res = await db.execute(
        select(AuctionListing).filter(AuctionListing.id == auction_id, AuctionListing.temple_id == tid)
    )
    auction = auc_res.scalars().first()
    if not auction or auction.status != "RESERVED":
        raise HTTPException(status_code=400, detail="Auction listing is not in a confirmable (RESERVED) state")
        
    # Load Active Reservation
    res_res = await db.execute(
        select(StoreStockReservation).filter(
            StoreStockReservation.reference_type == "AUCTION",
            StoreStockReservation.reference_id == str(auction.id),
            StoreStockReservation.reservation_status == "RESERVED",
            StoreStockReservation.temple_id == tid
        )
    )
    reservation = res_res.scalars().first()
    if not reservation:
        raise HTTPException(status_code=404, detail="No active reservation lock found for this auction")
        
    res_expires = reservation.expires_at
    now_compare = utcnow() if res_expires.tzinfo is not None else datetime.now(timezone.utc).replace(tzinfo=None)
    if res_expires < now_compare:
        raise HTTPException(status_code=400, detail="Auction reservation lock has expired. Release cleanup required.")

    async with db.begin_nested():
        # Confirm reservation status
        reservation.reservation_status = "CONFIRMED"
        
        # Settle Auction Status
        auction.status = "SOLD"
        auction.is_active = False
        
        # Generate Sales Order
        order_number = await generate_document_number(db, tid, "SO")
        sales_order = StoreSalesOrder(
            temple_id=tid,
            order_number=order_number,
            customer_name=payload.get("customer_name", "Auction Winner"),
            customer_phone=payload.get("customer_phone"),
            total_amount=auction.current_bid,
            payment_mode=payload.get("payment_mode", "UPI"),
            status="Completed",
            created_by=user_uuid,
            idempotency_key=idempotency_key
        )
        db.add(sales_order)
        await db.flush()
        
        # Order Item (Settle reservation quantity)
        sales_item = StoreSalesOrderItem(
            order_id=sales_order.id,
            product_id=auction.product_id,
            quantity=auction.quantity,
            unit_price=auction.current_bid / auction.quantity,
            total_price=auction.current_bid
        )
        db.add(sales_item)
        
        # Record final confirm movement in Ledger
        # (Stock was already deducted when bid was reserved, so quantity_change is 0,
        # we are just registering the confirmation event for audit trail)
        prod_res = await db.execute(select(StoreProduct).filter(StoreProduct.id == auction.product_id))
        product = prod_res.scalars().first()
        
        # Fetch current stock balance to log status
        stock_res = await db.execute(
            select(StoreStock).filter(StoreStock.product_id == auction.product_id, StoreStock.temple_id == tid)
        )
        stock = stock_res.scalars().first()
        current_qty = stock.quantity if stock else 0.0

        ledger = InventoryStockLedger(
            temple_id=tid,
            domain_type="STORE",
            store_product_id=auction.product_id,
            kalavara_item_id=None,
            item_name=product.name if product else "Product",
            location_id=reservation.location_id,
            movement_type=InventoryMovementType.SALE,
            quantity_change=0.0, # Net stock change is zero as stock was deducted at reservation
            before_stock=current_qty,
            after_stock=current_qty,
            reference_type="AUCTION_SETTLED",
            reference_id=order_number,
            performed_by=user_uuid,
            remarks=f"Auction settled: Order {order_number} confirmed with bid amount ₹{auction.current_bid}"
        )
        db.add(ledger)
        
        # Record Income
        await TransactionService.create_transaction(
            db=db,
            temple_id=str(tid),
            txn_type="income",
            category="store",
            amount=auction.current_bid,
            description=f"Store Auction Settlement {order_number} (Code: {auction.auction_code})",
            reference_id=order_number,
            source="system"
        )
        
    await db.commit()
    await db.refresh(sales_order)
    return sales_order


# ---------------------------------------------------------------------------
# OPERATIONAL OBSERVABILITY (System Health Dashboard)
# ---------------------------------------------------------------------------

@router.get("/health-dashboard", tags=["observability"])
async def system_health_dashboard(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    tid = UUID(str(temple_id))
    
    # 1. Scan expired reservations cleanup stats
    released_res_res = await db.execute(
        select(func.count(StoreStockReservation.id)).filter(
            StoreStockReservation.temple_id == tid,
            StoreStockReservation.reservation_status == "RELEASED"
        )
    )
    released_reservations_count = released_res_res.scalar() or 0
    
    active_res_res = await db.execute(
        select(func.count(StoreStockReservation.id)).filter(
            StoreStockReservation.temple_id == tid,
            StoreStockReservation.reservation_status == "RESERVED"
        )
    )
    active_reservations_count = active_res_res.scalar() or 0

    # 2. Procurement Backlog (Uncompleted invoices count)
    backlog_res = await db.execute(
        select(func.count(InventoryInvoice.id)).filter(
            InventoryInvoice.temple_id == tid,
            InventoryInvoice.status != "Completed",
            InventoryInvoice.status != "Cancelled"
        )
    )
    procurement_backlog_count = backlog_res.scalar() or 0

    # 3. Snapshot generation status (Check if a snapshot exists for today)
    from app.models.domain import InventoryDailySnapshot
    today = get_ist_now().date() if 'get_ist_now' in globals() else datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    snapshot_res = await db.execute(
        select(func.count(InventoryDailySnapshot.id)).filter(
            InventoryDailySnapshot.temple_id == tid,
            InventoryDailySnapshot.snapshot_date == today
        )
    )
    has_today_snapshot = (snapshot_res.scalar() or 0) > 0

    # 4. Low stock alert counts
    # Kalavara low stock items
    kalavara_low_res = await db.execute(
        select(func.count(InventoryItem.id)).filter(
            InventoryItem.temple_id == tid,
            InventoryItem.is_archived == False,
            InventoryItem.stock <= InventoryItem.min_stock
        )
    )
    kalavara_low_count = kalavara_low_res.scalar() or 0
    
    # Store low stock items (let's check if store stock is below 10)
    store_low_res = await db.execute(
        select(func.count(StoreStock.id)).filter(
            StoreStock.temple_id == tid,
            StoreStock.quantity <= 10.0
        )
    )
    store_low_count = store_low_res.scalar() or 0
    
    # 5. Concurrency conflict events (Scan from Audit Logs)
    conflict_res = await db.execute(
        select(func.count(AuditLog.id)).filter(
            AuditLog.temple_id == tid,
            AuditLog.action == "CONCURRENCY_CONFLICT"
        )
    )
    concurrency_conflicts_count = conflict_res.scalar() or 0

    # 6. Failed background jobs
    failed_jobs_res = await db.execute(
        select(func.count(AuditLog.id)).filter(
            AuditLog.temple_id == tid,
            AuditLog.action == "FAILED_JOB"
        )
    )
    failed_jobs_count = failed_jobs_res.scalar() or 0

    return {
        "status": "healthy",
        "timestamp": utcnow(),
        "metrics": {
            "stale_reservations_released": released_reservations_count,
            "active_reservations": active_reservations_count,
            "procurement_backlog_invoices": procurement_backlog_count,
            "today_snapshot_generated": has_today_snapshot,
            "kalavara_low_stock_count": kalavara_low_count,
            "store_low_stock_count": store_low_count,
            "concurrency_conflicts_detected": concurrency_conflicts_count,
            "failed_background_jobs": failed_jobs_count
        }
    }

def get_ist_now():
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist)
