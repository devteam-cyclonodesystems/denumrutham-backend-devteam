import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, Time, UniqueConstraint, Date, JSON, Index, text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database.base import Base
from app.models.operational_states import TempleOperationalState

def utcnow():
    return datetime.now(timezone.utc)


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    PENDING = "PENDING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"




class UserTemple(Base):
    """Maps users to temples they can access. SUPERADMIN bypasses this table."""
    __tablename__ = "user_temples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, default="ADMIN")  # optional per-temple role override
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    temple = relationship("Temple", back_populates="user_temples")

    __table_args__ = (
        UniqueConstraint("user_id", "temple_id", name="uq_user_temple"),
    )




class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=True, index=True)
    user_id = Column(String, unique=True, nullable=False)  # login identifier (backward compat)
    name = Column(String, nullable=False, default="")
    email = Column(String, unique=True, nullable=True, index=True)
    phone = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="STAFF")  # DEVOTEE / TEMPLE_MANAGER / STAFF / SUPER_ADMIN (backward compat)
    system_role_id = Column(UUID(as_uuid=True), ForeignKey("system_roles.id"), nullable=True, index=True)
    status = Column(String, default="ACTIVE")  # ACTIVE / PENDING / PENDING_APPROVAL / REJECTED / SUSPENDED / DISABLED
    availability_status = Column(String, default="AVAILABLE") # AVAILABLE / ON_LEAVE
    otp_code = Column(String, nullable=True)  # mock OTP storage
    otp_expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # --- Phase 5: Staff Onboarding Hardening ---
    approval_status = Column(String, default="PENDING") # PENDING / APPROVED / REJECTED
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejected_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    onboarding_method = Column(String, default="INVITE_TOKEN") # INVITE_TOKEN / DOMAIN_APPROVAL / ADMIN_CREATED
    force_password_change = Column(Boolean, default=False)

    # Extra staff info
    department = Column(String, nullable=True)
    shift = Column(String, nullable=True)
    dob = Column(String, nullable=True)
    salary = Column(Float, nullable=True)
    photo_url = Column(Text, nullable=True)
    media_urls = Column(JSON, nullable=True) # JSON array of strings
    remarks = Column(Text, nullable=True)
    audit_trail = Column(JSON, nullable=True) # JSON list of dicts: {"event": str, "timestamp": str, "notes": str}

    # Relationships
    system_role = relationship("SystemRole", lazy="joined")
    followed_temples = relationship("TempleFollower", back_populates="user")




class PasswordResetToken(Base):
    """Secure tokens for password recovery."""
    __tablename__ = "password_reset_tokens"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    user = relationship("User")




class StaffInvite(Base):
    """Invite-based staff registration to restrict unauthorized access."""
    __tablename__ = "staff_invites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False)
    email = Column(String, nullable=False, index=True)
    token = Column(String, unique=True, nullable=False, index=True)
    role = Column(String, default="STAFF")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_used = Column(Boolean, default=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)




class SecurityAuditEvent(Base):
    """Enterprise-grade security event tracking."""
    __tablename__ = "security_audit_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    event_type = Column(String, nullable=False, index=True)  # FORCE_LOGOUT, SECURITY_RESET, SESSION_REVOKED
    severity = Column(String, default="INFO")  # INFO, WARNING, CRITICAL
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    details = Column(JSON, nullable=True)
    admin_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    temple = relationship("Temple")
    user = relationship("User")


# ====================================================================
# ENTERPRISE INVENTORY PLATFORM MODELS
# ====================================================================

