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


class ChangeRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"




class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    role = Column(String, nullable=True)
    module_name = Column(String, nullable=True)
    action = Column(String, nullable=False)
    action_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    ip_address = Column(String, nullable=True)
    details = Column(Text)
    approval_id = Column(UUID(as_uuid=True), ForeignKey("approval_requests.id"), nullable=True)
    content_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    module = Column(String, nullable=False)
    entity_id = Column(String, nullable=True)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    request_payload = Column(JSON, nullable=False)
    status = Column(String, default="pending")  # pending/approved/rejected
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class Notification(Base):
    __tablename__ = "notifications"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    role = Column(String, nullable=True)  # Role-based delivery target
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    
    
# ====================================================================
# DEVOTEE PORTAL — New Models
# ====================================================================



class ArchanaBooking(Base):
    """Archana / Pooja booking — matches UI payload exactly."""
    __tablename__ = "archana_bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    ref_number = Column(String, nullable=True)  # e.g. AR01/0226
    devotee_name = Column(String, nullable=False)
    phone = Column(String, default="")
    nakshatra = Column(String, default="")
    items = Column(JSON, default=list)  # [{name, price}]
    family = Column(JSON, default=list)  # [{name, nakshatra, archana}]
    dakshina = Column(Float, default=0.0)
    booking_date = Column(String, nullable=False)
    booking_time = Column(String, default="")
    total = Column(Float, nullable=False, default=0.0)
    payment_mode = Column(String, default="Cash")
    booking_mode = Column(String, default="Counter")
    remarks = Column(Text, default="")
    consent = Column(Boolean, default=False)
    status = Column(String, default="confirmed")  # confirmed | cancelled
    is_active = Column(Boolean, default=True, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(String, default="Admin")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)




class ChangeRequest(Base):
    """Field-level change request for approval-driven updates.
    
    All updates by STAFF go into ChangeRequest instead of live tables.
    TEMPLE_MANAGER approves → apply change, rejects → discard.
    """
    __tablename__ = "change_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String, nullable=False)  # 'temple', 'employee', 'hall', etc.
    entity_id = Column(String, nullable=False)  # UUID of the target entity
    field_name = Column(String, nullable=False)  # e.g. 'contact_number', 'salary'
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=False)
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(String, default="PENDING")  # PENDING / APPROVED / REJECTED
    remarks = Column(Text, nullable=True)
    target_version = Column(Integer, nullable=True)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_change_requests_status", "status"),
        Index("idx_change_requests_entity", "entity_type", "entity_id"),
        Index("idx_change_requests_temple", "temple_id"),
    )


# ====================================================================
# TEMPLE FOLLOWER — Devotee follows a temple
# ====================================================================



class TempleDomainHistory(Base):
    """Tracks domain changes for URL stability and resolution."""
    __tablename__ = "temple_domain_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False)
    old_domain = Column(String, nullable=False)
    new_domain = Column(String, nullable=False)
    changed_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_domain_history_old_domain", "old_domain"),
    )




class OperationalStateAudit(Base):
    """Tracks every transition in temple operational state."""
    __tablename__ = "operational_state_audits"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    old_state = Column(Enum(TempleOperationalState), nullable=True)
    new_state = Column(Enum(TempleOperationalState), nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reason = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    temple = relationship("Temple")


