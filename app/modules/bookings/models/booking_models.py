import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, Time, UniqueConstraint, Date, JSON, Index, text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database.database import Base
from app.modules.governance.models.operational_states import TempleOperationalState

def utcnow():
    return datetime.now(timezone.utc)


class BookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"




class TicketStatus(str, enum.Enum):
    ISSUED = "ISSUED"
    SCANNED = "SCANNED"


# --- New enums for Devotee Portal ---


class ServiceType(str, enum.Enum):
    ARCHANA = "ARCHANA"
    OFFERING = "OFFERING"
    HALL_BOOKING = "HALL_BOOKING"
    DONATION = "DONATION"
    STORE = "STORE"




class ServiceBookingStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    CANCELLED = "CANCELLED"




class PaymentMethod(str, enum.Enum):
    UPI_QR = "UPI_QR"
    UPI_ID = "UPI_ID"




class Devotee(Base):
    __tablename__ = "devotees"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String)
    phone = Column(String)
    email = Column(String)
    star_sign_nakshatram = Column(String)
    gotram = Column(String)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class Pooja(Base):
    __tablename__ = "poojas"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    base_price = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)




class PoojaSlot(Base):
    __tablename__ = "pooja_slots"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    pooja_id = Column(UUID(as_uuid=True), ForeignKey("poojas.id"), nullable=False)
    slot_date = Column(DateTime(timezone=True), nullable=False)
    max_capacity = Column(Integer, default=50)
    current_booked = Column(Integer, default=0)




class Booking(Base):
    __tablename__ = "bookings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    devotee_id = Column(UUID(as_uuid=True), ForeignKey("devotees.id"), nullable=False)
    total_amount = Column(Float, nullable=False)
    status = Column(Enum(BookingStatus), default=BookingStatus.PENDING)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class Event(Base):
    __tablename__ = "events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    start_date = Column(DateTime(timezone=True), nullable=False)




class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    booking_id = Column(UUID(as_uuid=True), nullable=True)
    qr_hash = Column(String, unique=True, nullable=False)
    status = Column(Enum(TicketStatus), default=TicketStatus.ISSUED)




class ServiceBooking(Base):
    """Booking made by a devotee for a temple service."""
    __tablename__ = "service_bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    devotee_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("temple_services.id"), nullable=False)
    booking_date = Column(DateTime(timezone=True), nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(Enum(ServiceBookingStatus), default=ServiceBookingStatus.PENDING)
    devotee_name = Column(String, default="")
    devotee_phone = Column(String, default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)




class DevoteeProfile(Base):
    """Profile details for a devotee user."""
    __tablename__ = "devotee_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    name = Column(String, nullable=False, default="")
    nakshatra = Column(String, default="")
    gothram = Column(String, default="")
    address = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ====================================================================
# PHASE 1 — NEW MULTI-TENANT MODELS
# ====================================================================



class Hall(Base):
    """Venue / Hall available for booking."""
    __tablename__ = "halls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    capacity = Column(Integer, default=0)
    amenities = Column(String, default="")
    price_per_day = Column(Float, nullable=False, default=0.0)
    image_emoji = Column(String, default="🏛️")
    photos = Column(JSON, default=list)  # Array of photo URLs
    status = Column(String, default="active")
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("temple_id", "name", name="uq_hall_tenant_name"),
    )




class HallBooking(Base):
    """Hall / Venue booking record."""
    __tablename__ = "hall_bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    hall_id = Column(UUID(as_uuid=True), ForeignKey("halls.id"), nullable=False)
    ref_number = Column(String, nullable=True)  # e.g. HB001/0326
    customer_name = Column(String, nullable=False)
    address = Column(String, default="")
    phone = Column(String, default="")
    date = Column(String, nullable=False)  # start date YYYY-MM-DD
    start_time = Column(String, default="")
    end_date = Column(String, nullable=False)
    end_time = Column(String, default="")
    purpose = Column(String, default="")
    amount = Column(Float, nullable=False, default=0.0)
    discount_amount = Column(Float, default=0.0)
    payment_type = Column(String, default="full")  # full | partial
    amount_paid = Column(Float, default=0.0)
    payment_mode = Column(String, default="Cash")
    booking_mode = Column(String, default="Counter")
    remarks = Column(Text, default="")
    status = Column(String, default="pending", index=True)  # pending | confirmed | cancelled
    created_by = Column(String, default="Admin")
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    
    # Phase 10 — Offline/Hybrid Ready Foundation
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_version = Column(Integer, default=1, index=True)
    version_number = Column(Integer, default=1)
    device_origin = Column(String, nullable=True)
    sync_state = Column(String, default="SYNCED") # PENDING, SYNCED, CONFLICT
    payment_status = Column(String, default="PENDING", index=True)




class Cart(Base):
    """Shopping cart for a user."""
    __tablename__ = "carts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    status = Column(String, default="active")  # active / checked_out / abandoned
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    items = relationship("CartItem", back_populates="cart", cascade="all, delete-orphan")




class CartItem(Base):
    """Individual item in a cart."""
    __tablename__ = "cart_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cart_id = Column(UUID(as_uuid=True), ForeignKey("carts.id", ondelete="CASCADE"), nullable=False)
    service_id = Column(UUID(as_uuid=True), ForeignKey("temple_services.id"), nullable=True)
    item_name = Column(String, nullable=False)
    quantity = Column(Integer, default=1)
    unit_price = Column(Float, nullable=False, default=0.0)
    notes = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    cart = relationship("Cart", back_populates="items")




class Address(Base):
    """User address — for self or gift delivery."""
    __tablename__ = "addresses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    address_type = Column(String, default="self")  # 'self' | 'gift'
    recipient_name = Column(String, nullable=False, default="")
    phone = Column(String, default="")
    address_line_1 = Column(String, nullable=False, default="")
    address_line_2 = Column(String, default="")
    city = Column(String, default="")
    state = Column(String, default="")
    pincode = Column(String, default="")
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ====================================================================
# GUEST BOOKING — Unauthenticated booking support
# ====================================================================



class GuestBooking(Base):
    """Booking created by an unauthenticated guest."""
    __tablename__ = "guest_bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("temple_services.id"), nullable=True)
    guest_name = Column(String, nullable=False)
    guest_phone = Column(String, nullable=False)
    guest_email = Column(String, nullable=True)


# ====================================================================
# PHASE 1 HARDENING — NEW MODELS
# ====================================================================

