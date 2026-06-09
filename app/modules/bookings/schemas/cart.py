"""
Cart, Address & Guest Booking Schemas.
"""
from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional, List
from datetime import datetime


# ── Cart ──────────────────────────────────────────────────────────────

class CartItemCreate(BaseModel):
    """Add an item to cart."""
    service_id: Optional[UUID4] = None
    item_name: str
    quantity: int = 1
    unit_price: float
    notes: Optional[str] = ""


class CartItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    cart_id: UUID4
    service_id: Optional[UUID4] = None
    item_name: str
    quantity: int
    unit_price: float
    notes: Optional[str] = ""
    created_at: datetime


class CartResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    user_id: UUID4
    temple_id: UUID4
    status: str
    items: List[CartItemResponse] = []
    total_amount: float = 0.0
    created_at: datetime


class CartItemUpdate(BaseModel):
    """Update quantity of a cart item."""
    quantity: int


# ── Address ───────────────────────────────────────────────────────────

class AddressCreate(BaseModel):
    """Create a new address."""
    address_type: str = "self"  # 'self' | 'gift'
    recipient_name: str
    phone: Optional[str] = ""
    address_line_1: str
    address_line_2: Optional[str] = ""
    city: str
    state: str
    pincode: str
    is_default: bool = False


class AddressUpdate(BaseModel):
    """Update an existing address."""
    address_type: Optional[str] = None
    recipient_name: Optional[str] = None
    phone: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    is_default: Optional[bool] = None


class AddressResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    user_id: UUID4
    address_type: str
    recipient_name: str
    phone: Optional[str] = ""
    address_line_1: str
    address_line_2: Optional[str] = ""
    city: str
    state: str
    pincode: str
    is_default: bool
    created_at: datetime


from app.modules.bookings.models.booking_models import NotificationMode, BookingSource

# ── Guest Booking ─────────────────────────────────────────────────────

class GuestBookingCreate(BaseModel):
    """Create a booking without authentication."""
    temple_id: UUID4
    service_id: Optional[UUID4] = None
    guest_name: str
    guest_phone: str
    guest_email: Optional[str] = None
    booking_date: str  # ISO date string
    notes: Optional[str] = ""
    notification_mode: NotificationMode = NotificationMode.EMAIL
    notification_destination: Optional[str] = None
    dakshina_amount: float = 0.0
    booking_source: BookingSource = BookingSource.WEB_PUBLIC
    booking_metadata: dict = {}


class GuestBookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    service_id: Optional[UUID4] = None
    guest_name: str
    guest_phone: str
    guest_email: Optional[str] = None
    booking_date: datetime
    amount: float
    status: str
    notes: Optional[str] = ""
    notification_mode: NotificationMode
    notification_destination: Optional[str] = None
    dakshina_amount: float
    booking_source: BookingSource
    booking_metadata: dict
    created_at: datetime
