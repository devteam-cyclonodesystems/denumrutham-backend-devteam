"""
Cart & Address Routes — Shopping cart and delivery address management.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_temple_id
from app.schemas.domain import TokenData
from app.schemas.cart import (
    CartItemCreate, CartResponse, CartItemUpdate,
    AddressCreate, AddressUpdate, AddressResponse,
    GuestBookingCreate, GuestBookingResponse,
)
from app.services.cart_service import CartService, AddressService
from app.models.domain import GuestBooking, TempleService as TempleServiceModel
from app.core.response import api_response
from app.models.domain import GuestBooking, TempleService as TempleServiceModel
from sqlalchemy.future import select
from datetime import datetime, timezone

router = APIRouter()


# ══════════════════════════════════════════════════════════════════════
# CART ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@router.get("/cart")
async def get_cart(
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """Get the active cart for the current user and temple."""
    cart = await CartService.get_cart(db, UUID(current_user.sub), UUID(temple_id))
    return api_response(data=cart.model_dump() if hasattr(cart, 'model_dump') else cart, message="Cart retrieved")


@router.post("/cart/items", status_code=201)
async def add_to_cart(
    data: CartItemCreate,
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """Add an item to the cart."""
    item = await CartService.add_item(
        db=db,
        user_id=UUID(current_user.sub),
        temple_id=UUID(temple_id),
        service_id=data.service_id,
        item_name=data.item_name,
        quantity=data.quantity,
        unit_price=data.unit_price,
        notes=data.notes or "",
    )
    return api_response(data={"item_id": str(item.id)}, message="Item added to cart", status_code=201)


@router.put("/cart/items/{item_id}")
async def update_cart_item(
    item_id: UUID,
    data: CartItemUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update quantity of a cart item."""
    item = await CartService.update_item(
        db=db,
        user_id=UUID(current_user.sub),
        item_id=item_id,
        quantity=data.quantity,
    )
    return api_response(message="Cart item updated")


@router.delete("/cart/items/{item_id}")
async def remove_from_cart(
    item_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove an item from the cart."""
    await CartService.remove_item(db, UUID(current_user.sub), item_id)
    return api_response(message="Cart item removed")


@router.delete("/cart")
async def clear_cart(
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """Clear all items from the cart."""
    await CartService.clear_cart(db, UUID(current_user.sub), UUID(temple_id))
    return api_response(message="Cart cleared")


@router.post("/cart/checkout")
async def checkout(
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """Checkout the cart and create a booking."""
    result = await CartService.checkout(db, UUID(current_user.sub), UUID(temple_id))
    return api_response(data=result, message="Checkout successful")


# ══════════════════════════════════════════════════════════════════════
# ADDRESS ENDPOINTS
# ══════════════════════════════════════════════════════════════════════

@router.get("/addresses")
async def list_addresses(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all addresses for the current user."""
    addrs = await AddressService.list_addresses(db, UUID(current_user.sub))
    return api_response(data=[a.model_dump() if hasattr(a, 'model_dump') else a for a in addrs], message="Addresses retrieved")


@router.post("/addresses", status_code=201)
async def create_address(
    data: AddressCreate,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new address (self or gift)."""
    addr = await AddressService.create_address(
        db, UUID(current_user.sub), data.model_dump()
    )
    return api_response(data=addr.model_dump() if hasattr(addr, 'model_dump') else addr, message="Address created successfully", status_code=201)


@router.put("/addresses/{address_id}")
async def update_address(
    address_id: UUID,
    data: AddressUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing address."""
    addr = await AddressService.update_address(
        db, UUID(current_user.sub), address_id, data.model_dump(exclude_unset=True)
    )
    return api_response(data=addr.model_dump() if hasattr(addr, 'model_dump') else addr, message="Address updated successfully")


@router.delete("/addresses/{address_id}")
async def delete_address(
    address_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await AddressService.delete_address(db, UUID(current_user.sub), address_id)
    return api_response(message="Address deleted")


# ══════════════════════════════════════════════════════════════════════
# GUEST BOOKING (No authentication required)
# ══════════════════════════════════════════════════════════════════════

@router.post("/guest-booking", status_code=201)
async def create_guest_booking(
    data: GuestBookingCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a booking without authentication.
    Public endpoint for guest users.
    """
    # Parse date
    try:
        booking_date = datetime.fromisoformat(data.booking_date)
        if booking_date.tzinfo is None:
            booking_date = booking_date.replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking date format")

    # Get service price if service_id provided
    amount = 0.0
    if data.service_id:
        srv_result = await db.execute(
            select(TempleServiceModel).filter(
                TempleServiceModel.id == data.service_id,
                TempleServiceModel.temple_id == data.temple_id,
                TempleServiceModel.active == True,
            )
        )
        srv = srv_result.scalars().first()
        if not srv:
            raise HTTPException(status_code=404, detail="Service not found")
        amount = srv.price

    booking = GuestBooking(
        temple_id=data.temple_id,
        service_id=data.service_id,
        guest_name=data.guest_name,
        guest_phone=data.guest_phone,
        guest_email=data.guest_email,
        booking_date=booking_date,
        amount=amount,
        notes=data.notes or "",
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    return api_response(
        data=GuestBookingResponse.model_validate(booking).model_dump(), 
        message="Guest booking created successfully", 
        status_code=201
    )
