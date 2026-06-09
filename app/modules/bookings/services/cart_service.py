"""
Cart Service — Shopping cart and address management.
"""
import logging
from uuid import UUID
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.models.domain import Cart, CartItem, Address, TempleService as TempleServiceModel

logger = logging.getLogger(__name__)


class CartService:
    """Cart CRUD operations."""

    # ── Get or Create Active Cart ─────────────────────────────────────
    @staticmethod
    async def get_or_create_cart(
        db: AsyncSession, user_id: UUID, temple_id: UUID
    ) -> Cart:
        """Get the active cart for a user+temple, or create one."""
        result = await db.execute(
            select(Cart)
            .options(selectinload(Cart.items))
            .filter(
                Cart.user_id == user_id,
                Cart.temple_id == temple_id,
                Cart.status == "active",
                Cart.is_active == True,
            )
        )
        cart = result.scalars().first()

        if not cart:
            cart = Cart(user_id=user_id, temple_id=temple_id, status="active")
            db.add(cart)
            await db.flush()
            await db.refresh(cart)

        return cart

    # ── Get Cart ──────────────────────────────────────────────────────
    @staticmethod
    async def get_cart(db: AsyncSession, user_id: UUID, temple_id: UUID) -> dict:
        """Get the active cart with items and total."""
        cart = await CartService.get_or_create_cart(db, user_id, temple_id)
        
        # Reload with items
        result = await db.execute(
            select(Cart)
            .options(selectinload(Cart.items))
            .filter(Cart.id == cart.id)
        )
        cart = result.scalars().first()
        
        total = sum(item.unit_price * item.quantity for item in cart.items)

        return {
            "id": cart.id,
            "user_id": cart.user_id,
            "temple_id": cart.temple_id,
            "status": cart.status,
            "items": cart.items,
            "total_amount": round(total, 2),
            "created_at": cart.created_at,
        }

    # ── Add Item to Cart ──────────────────────────────────────────────
    @staticmethod
    async def add_item(
        db: AsyncSession,
        user_id: UUID,
        temple_id: UUID,
        service_id: Optional[UUID],
        item_name: str,
        quantity: int,
        unit_price: float,
        notes: str = "",
    ) -> CartItem:
        """Add an item to the user's active cart."""
        cart = await CartService.get_or_create_cart(db, user_id, temple_id)

        # If service_id provided, verify it exists
        if service_id:
            srv_result = await db.execute(
                select(TempleServiceModel).filter(
                    TempleServiceModel.id == service_id,
                    TempleServiceModel.temple_id == temple_id,
                )
            )
            srv = srv_result.scalars().first()
            if not srv:
                raise HTTPException(status_code=404, detail="Service not found")
            # Use service price
            unit_price = srv.price
            item_name = srv.service_name

        item = CartItem(
            cart_id=cart.id,
            service_id=service_id,
            item_name=item_name,
            quantity=quantity,
            unit_price=unit_price,
            notes=notes,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)

        return item

    # ── Update Cart Item Quantity ──────────────────────────────────────
    @staticmethod
    async def update_item(
        db: AsyncSession,
        user_id: UUID,
        item_id: UUID,
        quantity: int,
    ) -> CartItem:
        """Update the quantity of a cart item."""
        result = await db.execute(
            select(CartItem)
            .join(Cart)
            .filter(
                CartItem.id == item_id,
                Cart.user_id == user_id,
                Cart.status == "active",
            )
        )
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail="Cart item not found")

        if quantity <= 0:
            await db.delete(item)
        else:
            item.quantity = quantity

        await db.commit()
        if quantity > 0:
            await db.refresh(item)
        return item

    # ── Remove Cart Item ──────────────────────────────────────────────
    @staticmethod
    async def remove_item(db: AsyncSession, user_id: UUID, item_id: UUID) -> dict:
        """Remove an item from the cart."""
        result = await db.execute(
            select(CartItem)
            .join(Cart)
            .filter(
                CartItem.id == item_id,
                Cart.user_id == user_id,
                Cart.status == "active",
            )
        )
        item = result.scalars().first()
        if not item:
            raise HTTPException(status_code=404, detail="Cart item not found")

        await db.delete(item)
        await db.commit()

        return {"message": "Item removed from cart"}

    # ── Clear Cart ────────────────────────────────────────────────────
    @staticmethod
    async def clear_cart(db: AsyncSession, user_id: UUID, temple_id: UUID) -> dict:
        """Remove all items from the active cart."""
        cart = await CartService.get_or_create_cart(db, user_id, temple_id)
        
        result = await db.execute(
            select(CartItem).filter(CartItem.cart_id == cart.id)
        )
        items = result.scalars().all()
        for item in items:
            await db.delete(item)
        
        await db.commit()
        return {"message": "Cart cleared"}

    # ── Checkout ──────────────────────────────────────────────────────
    @staticmethod
    async def checkout(db: AsyncSession, user_id: UUID, temple_id: UUID) -> dict:
        """Mark cart as checked out and process both poojas and store products."""
        from sqlalchemy import func
        from app.modules.bookings.models.booking_models import ServiceBooking, ServiceBookingStatus, utcnow
        from app.modules.inventory.models.inventory_models import StoreSalesOrder, StoreSalesOrderItem, StoreStock, InventoryStockLedger, InventoryMovementType
        from app.models.domain import StoreProduct, Payment
        from app.modules.billing.models.billing_models import PaymentStatus
        import uuid

        result = await db.execute(
            select(Cart)
            .options(selectinload(Cart.items))
            .filter(
                Cart.user_id == user_id,
                Cart.temple_id == temple_id,
                Cart.status == "active",
            )
        )
        cart = result.scalars().first()
        if not cart or not cart.items:
            raise HTTPException(status_code=400, detail="Cart is empty")

        total = sum(i.unit_price * i.quantity for i in cart.items)
        
        # Partition cart items
        pooja_items = [i for i in cart.items if i.service_id is not None]
        store_items = [i for i in cart.items if i.product_id is not None]
        
        checkout_id = uuid.uuid4()
        booking = None
        order = None
        
        # 1. Process Poojas
        if pooja_items:
            first_service = pooja_items[0].service_id
            pooja_total = sum(i.unit_price * i.quantity for i in pooja_items)
            booking = ServiceBooking(
                id=checkout_id,
                temple_id=temple_id,
                devotee_user_id=user_id,
                service_id=first_service,
                booking_date=utcnow(),
                amount=pooja_total,
                status=ServiceBookingStatus.PENDING,
                notes="Cart checkout poojas"
            )
            db.add(booking)
            await db.flush()
            
        # 2. Process Store items (with concurrency-safe stock locking and deduction)
        if store_items:
            store_total = sum(i.unit_price * i.quantity for i in store_items)
            
            # Generate sequential order number
            year = utcnow().year
            count_result = await db.execute(
                select(func.count(StoreSalesOrder.id)).filter(
                    StoreSalesOrder.temple_id == temple_id,
                )
            )
            seq = (count_result.scalar() or 0) + 1
            order_number = f"ORD-{year}-{seq:06d}"
            
            order = StoreSalesOrder(
                id=checkout_id if not booking else uuid.uuid4(),
                temple_id=temple_id,
                order_number=order_number,
                customer_name="Devotee Client",
                total_amount=store_total,
                payment_mode="UPI",
                status="Completed",
                payment_status="PENDING",
                created_by=user_id,
                idempotency_key=str(checkout_id)
            )
            db.add(order)
            await db.flush()
            
            # Deduct stock and log movements
            for item in store_items:
                # Lock stock row using with_for_update()
                stock_stmt = select(StoreStock).filter(
                    StoreStock.product_id == item.product_id,
                    StoreStock.temple_id == temple_id
                ).with_for_update()
                stock_res = await db.execute(stock_stmt)
                stock = stock_res.scalar_one_or_none()
                
                if not stock or stock.quantity < item.quantity:
                    # Get product name
                    prod_stmt = select(StoreProduct).filter(StoreProduct.id == item.product_id)
                    prod_res = await db.execute(prod_stmt)
                    prod = prod_res.scalar_one_or_none()
                    prod_name = prod.name if prod else str(item.product_id)
                    raise HTTPException(
                        status_code=400,
                        detail=f"Insufficient stock for product '{prod_name}'. Requested: {item.quantity}, Available: {stock.quantity if stock else 0.0}"
                    )
                    
                before_qty = stock.quantity
                after_qty = before_qty - item.quantity
                stock.quantity = after_qty
                
                # Fetch product name for ledger
                prod_stmt = select(StoreProduct).filter(StoreProduct.id == item.product_id)
                prod_res = await db.execute(prod_stmt)
                prod = prod_res.scalar_one_or_none()
                prod_name = prod.name if prod else "Store Product"
                
                ledger = InventoryStockLedger(
                    temple_id=temple_id,
                    domain_type="STORE",
                    store_product_id=item.product_id,
                    item_name=prod_name,
                    location_id=stock.location_id,
                    movement_type=InventoryMovementType.SALE,
                    performed_by=user_id,
                    quantity_change=-float(item.quantity),
                    before_stock=before_qty,
                    after_stock=after_qty,
                    reference_type="SALE",
                    reference_id=str(order.id),
                    remarks=f"Devotee checkout sale for order {order_number}"
                )
                db.add(ledger)
                
                # Create order item
                order_item = StoreSalesOrderItem(
                    order_id=order.id,
                    product_id=item.product_id,
                    quantity=float(item.quantity),
                    unit_price=item.unit_price,
                    total_price=item.unit_price * item.quantity
                )
                db.add(order_item)
                
        # 3. Mark cart as checked out
        cart.status = "checked_out"
        
        # 4. Create Payment record
        payment = Payment(
            temple_id=temple_id,
            reference_id=checkout_id,
            amount=total,
            provider_ref="mock_gateway_ref",
            status=PaymentStatus.PENDING,
            service_booking_id=booking.id if booking else None
        )
        db.add(payment)
        
        await db.commit()
        
        return {
            "message": "Checkout successful, payment pending",
            "cart_id": str(cart.id),
            "booking_id": str(booking.id) if booking else None,
            "order_id": str(order.id) if order else None,
            "payment_id": str(payment.id),
            "total_amount": round(total, 2),
            "items_count": len(cart.items),
        }


class AddressService:
    """Address CRUD for self and gift delivery."""

    @staticmethod
    async def create_address(db: AsyncSession, user_id: UUID, data: dict) -> Address:
        """Create a new address."""
        addr = Address(user_id=user_id, **data)
        
        # If setting as default, unset other defaults
        if data.get("is_default"):
            existing = await db.execute(
                select(Address).filter(
                    Address.user_id == user_id,
                    Address.is_default == True,
                    Address.is_active == True,
                )
            )
            for a in existing.scalars().all():
                a.is_default = False

        db.add(addr)
        await db.commit()
        await db.refresh(addr)
        return addr

    @staticmethod
    async def list_addresses(db: AsyncSession, user_id: UUID) -> list:
        """List all addresses for a user."""
        result = await db.execute(
            select(Address).filter(Address.user_id == user_id, Address.is_active == True).order_by(Address.is_default.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def update_address(db: AsyncSession, user_id: UUID, address_id: UUID, data: dict) -> Address:
        """Update an existing address."""
        result = await db.execute(
            select(Address).filter(Address.id == address_id, Address.user_id == user_id, Address.is_active == True)
        )
        addr = result.scalars().first()
        if not addr:
            raise HTTPException(status_code=404, detail="Address not found")

        for key, value in data.items():
            if value is not None:
                setattr(addr, key, value)

        if data.get("is_default"):
            existing = await db.execute(
                select(Address).filter(
                    Address.user_id == user_id,
                    Address.id != address_id,
                    Address.is_default == True,
                    Address.is_active == True,
                )
            )
            for a in existing.scalars().all():
                a.is_default = False

        await db.commit()
        await db.refresh(addr)
        return addr

    @staticmethod
    async def delete_address(db: AsyncSession, user_id: UUID, address_id: UUID) -> dict:
        """Delete an address."""
        result = await db.execute(
            select(Address).filter(Address.id == address_id, Address.user_id == user_id, Address.is_active == True)
        )
        addr = result.scalars().first()
        if not addr:
            raise HTTPException(status_code=404, detail="Address not found")

        from app.models.domain import utcnow
        addr.is_active = False
        addr.deleted_at = utcnow()
        await db.commit()
        return {"message": "Address deleted"}
