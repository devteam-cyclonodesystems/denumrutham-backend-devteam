from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional, List
from datetime import datetime


# ---------- Hall ----------
class HallCreate(BaseModel):
    name: str
    capacity: int = 0
    amenities: str = ""
    price_per_day: float = 0.0
    image_emoji: str = "🏛️"
    photos: List[str] = []
    status: str = "active"


class HallUpdate(BaseModel):
    name: Optional[str] = None
    capacity: Optional[int] = None
    amenities: Optional[str] = None
    price_per_day: Optional[float] = None
    image_emoji: Optional[str] = None
    photos: Optional[List[str]] = None
    status: Optional[str] = None
    is_active: Optional[bool] = None


class HallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    name: str
    capacity: int
    amenities: str
    price_per_day: float
    image_emoji: str
    photos: List[str] = []
    status: str
    created_at: datetime


# ---------- Hall Booking ----------
class HallBookingCreate(BaseModel):
    """Matches the exact UI payload from hall-booking.js saveBooking()."""
    hall_id: UUID4
    hall_name: Optional[str] = ""  # denormalized for display
    customer_name: str
    address: str = ""
    phone: str = ""
    date: str  # YYYY-MM-DD
    start_time: str = ""
    end_date: str
    end_time: str = ""
    purpose: str = ""
    amount: float = 0.0
    discount_amount: float = 0.0
    payment_type: str = "full"
    amount_paid: float = 0.0
    payment_mode: str = "Cash"
    booking_mode: str = "Counter"
    remarks: str = ""


class HallBookingUpdate(BaseModel):
    hall_id: Optional[UUID4] = None
    hall_name: Optional[str] = None
    customer_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_date: Optional[str] = None
    end_time: Optional[str] = None
    purpose: Optional[str] = None
    amount: Optional[float] = None
    discount_amount: Optional[float] = None
    payment_type: Optional[str] = None
    amount_paid: Optional[float] = None
    payment_mode: Optional[str] = None
    booking_mode: Optional[str] = None
    remarks: Optional[str] = None
    status: Optional[str] = None


class HallBookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    hall_id: UUID4
    ref_number: Optional[str] = None
    customer_name: str
    address: str
    phone: str
    date: str
    start_time: str
    end_date: str
    end_time: str
    purpose: str
    amount: float
    discount_amount: float
    payment_type: str
    amount_paid: float
    payment_mode: str
    booking_mode: str
    remarks: str
    status: str
    created_by: str
    created_at: datetime


# ---------- Hall Booking Refund ----------
class HallRefundRequest(BaseModel):
    booking_id: str
    amount: float
    refund_method: str = "Cash"
    refund_status: str = "Full"  # Full | Partial
    reason: str = ""


class HallRefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    booking_id: str
    amount: float
    refund_method: str
    refund_status: str
    reason: str
    status: str
    created_at: datetime
