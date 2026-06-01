import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, Time, UniqueConstraint, Date, JSON, Index, text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database.database import Base
from app.modules.governance.models.operational_states import TempleOperationalState
from app.modules.bookings.models.booking_models import ServiceType


def utcnow():
    return datetime.now(timezone.utc)


class TempleApprovalStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ServiceType(str, enum.Enum):
    ARCHANA = "ARCHANA"
    OFFERING = "OFFERING"
    HALL_BOOKING = "HALL_BOOKING"
    DONATION = "DONATION"
    STORE = "STORE"




class Temple(Base):
    __tablename__ = "temples"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    domain = Column(String, nullable=False) # Unique constraint replaced by partial index in __table_args__
    location = Column(String, default="")
    state = Column(String, default="")
    address_line_1 = Column(String, default="")
    address_line_2 = Column(String, default="")
    district = Column(String, default="")
    pincode = Column(String, default="")
    contact_number = Column(String, default="")
    alternate_contact = Column(String, default="")
    email = Column(String, default="")
    description = Column(Text, default="")
    # --- Phase 2: Domain + Identifier Architecture ---
    temple_code = Column(String, unique=True, nullable=True, index=True) # Format: TMP-YYYYMMDD-XXX

    # Dual-status: 'PENDING'/'APPROVED'/'REJECTED' for registration,
    # 'active'/'inactive' for operational (backward compat)
    status = Column(String, nullable=False, default="PENDING")
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    
    # Phase 1 Hardening: Explicit approval audit fields
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Phase 4 Hardening: Advanced Security
    security_version = Column(Integer, default=1, nullable=False)
    last_security_event_at = Column(DateTime(timezone=True), nullable=True)

    # Phase 5: Tenant Operational Governance
    operational_state = Column(Enum(TempleOperationalState), nullable=False, default=TempleOperationalState.ACTIVE)

    __table_args__ = (
        Index("unique_active_domain", "domain", unique=True, postgresql_where=text("deleted_at IS NULL")),
        Index("idx_temples_visible", "id", postgresql_where=text("status = 'APPROVED' AND is_active = TRUE")),
    )

    # Relationships
    profile = relationship("TempleProfile", back_populates="temple", uselist=False)
    images = relationship("TempleImage", back_populates="temple")
    user_temples = relationship("UserTemple", back_populates="temple")
    followers = relationship("TempleFollower", back_populates="temple")




class TempleStatusAudit(Base):
    __tablename__ = "temple_status_audit"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    old_status = Column(String, nullable=False)
    new_status = Column(String, nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime(timezone=True), default=utcnow)
    reason = Column(Text, nullable=True)




class TempleProfile(Base):
    """Extended temple information for the public devotee portal."""
    __tablename__ = "temple_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), unique=True, nullable=False)
    description = Column(Text, default="")
    history = Column(Text, default="")
    location = Column(String, default="")
    district = Column(String, default="")
    state = Column(String, default="")
    country = Column(String, default="India")
    contact_number = Column(String, default="")
    email = Column(String, default="")
    opening_time = Column(String, default="06:00")
    closing_time = Column(String, default="20:00")
    live_stream_url = Column(String, default="")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    upi_id = Column(String, default="")
    image_url = Column(String, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    temple = relationship("Temple", back_populates="profile")




class TempleProfileDraft(Base):
    """
    Staging table for temple profile edits.
    Manager edits → saved here.
    Admin approves → promote to TempleProfile.
    """
    __tablename__ = "temple_profile_drafts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    description = Column(Text, nullable=True)
    history = Column(Text, nullable=True)
    location = Column(String, nullable=True)
    district = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, default="India")
    contact_number = Column(String, nullable=True)
    email = Column(String, nullable=True)
    opening_time = Column(String, nullable=True)
    closing_time = Column(String, nullable=True)
    live_stream_url = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    upi_id = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    
    # Audit
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String, default="PENDING")  # PENDING / APPROVED / REJECTED
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)




class TempleImage(Base):
    """Gallery images for a temple."""
    __tablename__ = "temple_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    image_url = Column(String, nullable=False)
    caption = Column(String, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    temple = relationship("Temple", back_populates="images")




class TempleService(Base):
    """Services offered by a temple (archana, offerings, hall booking, etc.)."""
    __tablename__ = "temple_services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    service_name = Column(String, nullable=False)
    service_type = Column(Enum(ServiceType), nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    description = Column(Text, default="")
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class TempleFollower(Base):
    """Devotee follows a temple for notifications and quick access."""
    __tablename__ = "temple_followers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User", back_populates="followed_temples")
    temple = relationship("Temple", back_populates="followers")

    __table_args__ = (
        UniqueConstraint("user_id", "temple_id", name="uq_temple_follower"),
    )


# ====================================================================
# CART & ADDRESS — Store / booking checkout
# ====================================================================

