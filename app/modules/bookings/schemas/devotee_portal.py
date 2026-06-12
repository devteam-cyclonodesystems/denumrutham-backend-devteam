from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional, List
from datetime import datetime
from app.modules.bookings.models.booking_models import ServiceType, ServiceBookingStatus, PaymentMethod, NotificationMode, BookingSource
from app.modules.billing.models.billing_models import PaymentStatus

# ---------- Devotee Auth ----------
class DevoteeRegister(BaseModel):
    phone_number: str
    password: str
    name: str


class DevoteeProfileUpdate(BaseModel):
    name: Optional[str] = None
    nakshatra: Optional[str] = None
    gothram: Optional[str] = None
    address: Optional[str] = None


class DevoteeProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    user_id: UUID4
    name: str
    nakshatra: Optional[str] = ""
    gothram: Optional[str] = ""
    address: Optional[str] = ""
    created_at: datetime


# ---------- Temple Listing (card view) ----------
class TempleListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    name: str
    domain: Optional[str] = ""
    location: Optional[str] = ""
    district: Optional[str] = ""
    state: Optional[str] = ""
    image_url: Optional[str] = ""


class TempleListResponse(BaseModel):
    temples: List[TempleListItem]
    total: int


# ---------- Temple Profile (full detail) ----------
class TempleImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    image_url: str
    caption: Optional[str] = ""
    category: str


class TempleProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    name: str
    domain: str
    description: Optional[str] = ""
    history: Optional[str] = ""
    location: Optional[str] = ""
    district: Optional[str] = ""
    state: Optional[str] = ""
    country: Optional[str] = "India"
    contact_number: Optional[str] = ""
    email: Optional[str] = ""
    opening_time: Optional[str] = "06:00"
    closing_time: Optional[str] = "20:00"
    live_stream_url: Optional[str] = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    upi_id: Optional[str] = ""
    image_url: Optional[str] = ""
    main_deity: Optional[str] = ""
    deities: Optional[List[str]] = []
    facebook_url: Optional[str] = ""
    instagram_url: Optional[str] = ""
    youtube_url: Optional[str] = ""
    twitter_url: Optional[str] = ""
    website_url: Optional[str] = ""
    festivals_description: Optional[str] = ""
    images: List[TempleImageResponse] = []


# ---------- Temple Services ----------
class TempleServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    service_name: str
    service_type: ServiceType
    price: float
    description: Optional[str] = ""
    active: bool


# ---------- Service Booking ----------
class ServiceBookingCreate(BaseModel):
    temple_id: UUID4
    service_id: UUID4
    booking_date: str  # ISO date string
    devotee_name: str
    devotee_phone: str
    notes: Optional[str] = ""
    notification_mode: NotificationMode = NotificationMode.EMAIL
    notification_destination: Optional[str] = None
    dakshina_amount: float = 0.0
    booking_source: BookingSource = BookingSource.WEB_PUBLIC
    booking_metadata: dict = {}


class ServiceBookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    service_id: UUID4
    booking_date: datetime
    amount: float
    status: ServiceBookingStatus
    devotee_name: Optional[str] = ""
    devotee_phone: Optional[str] = ""
    notes: Optional[str] = ""
    notification_mode: NotificationMode
    notification_destination: Optional[str] = None
    dakshina_amount: float
    booking_source: BookingSource
    booking_metadata: dict
    created_at: datetime
    # Enriched fields (set in the API)
    service_name: Optional[str] = None
    temple_name: Optional[str] = None


# ---------- Payment ----------
class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    amount: float
    payment_method: Optional[PaymentMethod] = None
    status: PaymentStatus
    service_booking_id: Optional[UUID4] = None
    upi_id: Optional[str] = ""
    created_at: Optional[datetime] = None
