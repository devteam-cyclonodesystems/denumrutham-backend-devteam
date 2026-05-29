from pydantic import BaseModel, ConfigDict, EmailStr, UUID4, field_validator
from typing import Optional, List
from datetime import datetime
from app.modules.bookings.models.booking_models import BookingStatus, TicketStatus
from app.modules.billing.models.billing_models import PaymentStatus
from app.modules.temple_management.models.temple_models import TempleApprovalStatus
import re


# ---------- Auth ----------
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    sub: str | None = None
    temple_id: str | None = None
    role: str | None = None
    username: str | None = None
    user_status: str | None = None
    security_version: int | None = None
    iat: int | None = None
    force_password_change: bool | None = False


# ---------- Temple ----------
class TempleBase(BaseModel):
    name: str
    domain: str


class TempleCreate(TempleBase):
    location: Optional[str] = ""
    status: Optional[TempleApprovalStatus] = TempleApprovalStatus.PENDING


class TempleCreateFull(BaseModel):
    """Full temple creation schema with all fields and validation."""
    name: str
    location: Optional[str] = ""
    state: Optional[str] = ""
    address_line_1: Optional[str] = ""
    address_line_2: Optional[str] = ""
    district: Optional[str] = ""
    pincode: Optional[str] = ""
    contact_number: Optional[str] = ""
    alternate_contact: Optional[str] = ""
    email: Optional[str] = ""
    description: Optional[str] = ""
    status: Optional[TempleApprovalStatus] = TempleApprovalStatus.PENDING

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v):
        if v and v.strip():
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(pattern, v.strip()):
                raise ValueError("Invalid email format")
        return v

    @field_validator("contact_number", "alternate_contact")
    @classmethod
    def validate_phone_format(cls, v):
        if v and v.strip():
            cleaned = re.sub(r'[\s\-\(\)\+]', '', v)
            if not re.match(r'^\d{7,15}$', cleaned):
                raise ValueError("Invalid phone number format (7-15 digits expected)")
        return v

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v):
        if v and v.strip():
            if not re.match(r'^\d{5,10}$', v.strip()):
                raise ValueError("Invalid pincode format")
        return v


class TempleUpdateFull(BaseModel):
    """Full temple update schema — all fields optional."""
    name: Optional[str] = None
    location: Optional[str] = None
    state: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    district: Optional[str] = None
    pincode: Optional[str] = None
    contact_number: Optional[str] = None
    alternate_contact: Optional[str] = None
    email: Optional[str] = None
    description: Optional[str] = None
    status: Optional[TempleApprovalStatus] = None

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v):
        if v and v.strip():
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(pattern, v.strip()):
                raise ValueError("Invalid email format")
        return v

    @field_validator("contact_number", "alternate_contact")
    @classmethod
    def validate_phone_format(cls, v):
        if v and v.strip():
            cleaned = re.sub(r'[\s\-\(\)\+]', '', v)
            if not re.match(r'^\d{7,15}$', cleaned):
                raise ValueError("Invalid phone number format (7-15 digits expected)")
        return v


class TempleUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    location: Optional[str] = None
    status: Optional[TempleApprovalStatus] = None


class TempleResponse(TempleBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    location: Optional[str] = ""
    status: Optional[TempleApprovalStatus] = TempleApprovalStatus.PENDING
    created_at: datetime


# ---------- User ----------
class UserCreate(BaseModel):
    user_id: str
    password: str
    role: Optional[str] = "STAFF"


# ---------- Devotee ----------
class DevoteeCreate(BaseModel):
    first_name: str
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    star_sign_nakshatram: Optional[str] = None
    gotram: Optional[str] = None


class DevoteeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    first_name: str
    last_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    star_sign_nakshatram: Optional[str] = None
    gotram: Optional[str] = None
    created_at: datetime


# ---------- Pooja ----------
class PoojaCreate(BaseModel):
    name: str
    base_price: float
    is_active: bool = True


class PoojaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    name: str
    base_price: float
    is_active: bool


# ---------- Booking ----------
class BookingCreate(BaseModel):
    devotee_id: UUID4
    total_amount: float


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    devotee_id: UUID4
    total_amount: float
    status: BookingStatus
    created_at: datetime


# ---------- Donation ----------
class DonationCreate(BaseModel):
    devotee_id: Optional[UUID4] = None
    amount: float
    notes: Optional[str] = None


class DonationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    devotee_id: Optional[UUID4] = None
    amount: float
    notes: Optional[str] = None
    created_at: datetime


# ---------- QR / Ticket ----------
class QRValidationRequest(BaseModel):
    qr_hash: str
    scanner_location: str


class QRValidationResponse(BaseModel):
    valid: bool
    ticket_status: Optional[str] = None
    message: str

# ---------- Administrative Actions ----------
class TempleActionRequest(BaseModel):
    """Schema for administrative actions like suspension or reactivation."""
    reason: Optional[str] = "Administrative action triggered via SuperAdmin"
