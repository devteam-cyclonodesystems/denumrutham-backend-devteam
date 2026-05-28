import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, JSON, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import enum
from app.db.session import Base
from app.models.domain import utcnow


class BookingHold(Base):
    """Temporary reservation lock."""
    __tablename__ = "booking_holds"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    hall_id = Column(UUID(as_uuid=True), ForeignKey("halls.id"), nullable=False, index=True)
    held_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    session_id = Column(String, nullable=True) # for anonymous guests or specific sessions
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    
    __table_args__ = (
        Index("idx_booking_hold_valid", "hall_id", "start_time", "end_time"),
    )

class PaymentLedger(Base):
    """Centralized payment tracker for a booking."""
    __tablename__ = "payment_ledgers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("hall_bookings.id"), nullable=False, unique=True)
    total_amount = Column(Float, nullable=False, default=0.0)
    paid_amount = Column(Float, nullable=False, default=0.0)
    due_amount = Column(Float, nullable=False, default=0.0)
    refunded_amount = Column(Float, nullable=False, default=0.0)
    status = Column(String, default="PENDING") # PENDING, PARTIAL, COMPLETED, REFUNDED
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class PaymentTransaction(Base):
    """Individual payment installment or refund."""
    __tablename__ = "payment_transactions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    ledger_id = Column(UUID(as_uuid=True), ForeignKey("payment_ledgers.id"), nullable=False)
    transaction_type = Column(String, nullable=False) # PAYMENT, REFUND
    amount = Column(Float, nullable=False)
    payment_mode = Column(String, nullable=False) # CASH, UPI, CARD, TRANSFER
    reference_number = Column(String, nullable=True)
    status = Column(String, default="SUCCESS") # PENDING, SUCCESS, FAILED
    processed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class RefundTransaction(Base):
    """Specific refund details."""
    __tablename__ = "refund_transactions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_transaction_id = Column(UUID(as_uuid=True), ForeignKey("payment_transactions.id"), nullable=False, unique=True)
    reason = Column(Text, nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class BookingAuditLog(Base):
    """Audit trail for all booking modifications."""
    __tablename__ = "booking_audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("hall_bookings.id"), nullable=False, index=True)
    action = Column(String, nullable=False) # CREATED, UPDATED, STATUS_CHANGED, PAYMENT_ADDED
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    previous_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    ip_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class BookingStatusHistory(Base):
    """Timeline of booking status transitions."""
    __tablename__ = "booking_status_history"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("hall_bookings.id"), nullable=False, index=True)
    old_status = Column(String, nullable=True)
    new_status = Column(String, nullable=False)
    changed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class BookingConflict(Base):
    """Persisted record of resolved or pending booking conflicts."""
    __tablename__ = "booking_conflicts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    hall_id = Column(UUID(as_uuid=True), ForeignKey("halls.id"), nullable=False)
    primary_booking_id = Column(UUID(as_uuid=True), ForeignKey("hall_bookings.id"), nullable=False)
    overlapping_booking_id = Column(UUID(as_uuid=True), ForeignKey("hall_bookings.id"), nullable=True)
    conflict_type = Column(String, nullable=False) # HARD_OVERLAP, SOFT_OVERLAP
    status = Column(String, default="PENDING") # PENDING, RESOLVED, IGNORED
    resolution_notes = Column(Text, nullable=True)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

class VenueSlot(Base):
    """Pre-defined bookable slots for a venue (e.g., Morning, Evening)."""
    __tablename__ = "venue_slots"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    hall_id = Column(UUID(as_uuid=True), ForeignKey("halls.id"), nullable=False)
    name = Column(String, nullable=False) # e.g. "Morning Slot", "Full Day"
    start_time = Column(String, nullable=False) # HH:MM format
    end_time = Column(String, nullable=False) # HH:MM format
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class PricingRule(Base):
    """Advanced pricing engine rules."""
    __tablename__ = "pricing_rules"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    hall_id = Column(UUID(as_uuid=True), ForeignKey("halls.id"), nullable=True)
    name = Column(String, nullable=False)
    rule_type = Column(String, nullable=False) # SEASONAL, WEEKEND, VIP, MEMBER
    adjustment_type = Column(String, nullable=False) # PERCENTAGE, FIXED_AMOUNT
    adjustment_value = Column(Float, nullable=False) # e.g., -10 for 10% discount
    is_active = Column(Boolean, default=True)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)

class BookingPolicy(Base):
    """Temple-specific rules for bookings (e.g. blackout dates, capacity limits)."""
    __tablename__ = "booking_policies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    hall_id = Column(UUID(as_uuid=True), ForeignKey("halls.id"), nullable=True)
    policy_type = Column(String, nullable=False) # BLACKOUT_DATE, MAX_DURATION, MIN_NOTICE
    policy_value = Column(JSON, nullable=False) # e.g., {"start_date": "2023-01-01", "end_date": "2023-01-05"}
    is_active = Column(Boolean, default=True)
    message = Column(String, nullable=True) # Error message to show on violation
    created_at = Column(DateTime(timezone=True), default=utcnow)
