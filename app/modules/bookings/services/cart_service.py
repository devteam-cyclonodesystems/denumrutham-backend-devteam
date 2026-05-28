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
        """Mark cart as checked out."""
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
        cart.status = "checked_out"
        
        from app.models.domain import Payment, ServiceBooking, ServiceBookingStatus
        import uuid
        
        # Create a ServiceBooking for the entire cart checkout (this might logically need one per item, but aggregating for simplicity in the mockup)
        # Using the first service_id if available, otherwise None
        first_service = next((item.service_id for item in cart.items if item.service_id), None)
        
        booking = ServiceBooking(
            temple_id=temple_id,
            devotee_user_id=user_id,
            service_id=first_service if first_service else uuid.uuid4(), # Fallback for pure store items without service
            booking_date=utcnow(),
            amount=total,
            status=ServiceBookingStatus.PENDING,
            notes="Cart checkout"
        )
        db.add(booking)
        await db.flush()

        payment = Payment(
            temple_id=temple_id,
            reference_id=uuid.uuid4(),
            amount=total,
            provider_ref="mock_gateway_ref",
            service_booking_id=booking.id,
            transaction_id=str(uuid.uuid4())
        )
        db.add(payment)

        await db.commit()

        return {
            "message": "Checkout successful, payment pending",
            "cart_id": str(cart.id),
            "booking_id": str(booking.id),
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
