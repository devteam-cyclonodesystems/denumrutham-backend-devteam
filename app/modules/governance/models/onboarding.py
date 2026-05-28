"""
Temple Onboarding Staging Models — registration requests held until
Super Admin approval.

These tables ensure no temple or manager user appears in production
tables until explicitly approved. The approval flow atomically
promotes staging records → production records.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base


def utcnow():
    return datetime.now(timezone.utc)


class TempleRequest(Base):
    """
    Staging record for a temple registration request.

    Status lifecycle: PENDING → APPROVED | REJECTED
    Domain must be unique across both temple_requests and temples.
    """
    __tablename__ = "temple_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_name = Column(String, nullable=False)
    domain = Column(String, unique=True, nullable=False)
    contact = Column(String, default="")
    alt_contact = Column(String, default="")
    address = Column(String, default="")
    state = Column(String, default="")
    district = Column(String, default="")
    pincode = Column(String, default="")
    email = Column(String, default="")
    status = Column(String, default="PENDING", nullable=False)  # PENDING / APPROVED / REJECTED

    # Approval metadata
    rejection_reason = Column(Text, nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    
    # --- Phase 1: Critical Fixes (Additive) ---
    rejected_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    rejected_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_temple_requests_status", "status"),
        Index("idx_temple_requests_domain", "domain"),
    )


class UserRequest(Base):
    """
    Staging record for the manager user accompanying a temple request.

    Created alongside TempleRequest. Promoted to a real User record
    only when the linked TempleRequest is approved.
    """
    __tablename__ = "user_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="TEMPLE_ADMIN", nullable=False)
    temple_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("temple_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String, default="PENDING", nullable=False)  # PENDING / APPROVED / REJECTED
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_user_requests_temple_request", "temple_request_id"),
        Index("idx_user_requests_status", "status"),
    )
