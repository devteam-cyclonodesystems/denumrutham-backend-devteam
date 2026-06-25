import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, JSON, Index, text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class QueueStatus(str, enum.Enum):
    WAITING = "WAITING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"
    SYNC_PENDING = "SYNC_PENDING"

class CompletionMode(str, enum.Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"

class ArchanaExecutionGroup(Base):
    """
    Internal grouping for rituals performed together physically.
    NOT exposed to UI as 'Batch' or 'Group'.
    """
    __tablename__ = "archana_execution_groups"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    ritual_name_snapshot = Column(String, nullable=True)
    started_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    expected_completion_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Enum(QueueStatus), default=QueueStatus.IN_PROGRESS)
    
    executions = relationship("ArchanaExecution", back_populates="group")

class ArchanaStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    IN_PROGRESS = "IN_PROGRESS"  # Backward compatibility
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SYNCED = "SYNCED"
    OFFLINE_PENDING_SYNC = "OFFLINE_PENDING_SYNC"

class CatalogStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ARCHIVED = "ARCHIVED"

class DeityStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"

class DeityMaster(Base):
    """Master record for Deities (DeityMaster entity)."""
    __tablename__ = "deity_master"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    deity_name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=True)
    icon = Column(String, nullable=True)
    status = Column(Enum(DeityStatus), default=DeityStatus.ACTIVE)
    display_order = Column(Integer, default=0)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'deity_name', name='uq_deity_name_per_tenant'),
    )

    temple = relationship("Temple")

class DeityAudit(Base):
    """Audit log for deity management."""
    __tablename__ = "deity_audit"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    deity_id = Column(UUID(as_uuid=True), ForeignKey("deity_master.id"), nullable=False)
    action = Column(String, nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    old_state = Column(JSON, nullable=True)
    new_state = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow)


class ArchanaCatalog(Base):
    """Catalog of available Archanas and Poojas (ArchanaService entity)."""
    __tablename__ = "archana_catalog"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    deity_id = Column(UUID(as_uuid=True), ForeignKey("deity_master.id"), nullable=True)
    duration_minutes = Column(Integer, default=5)
    remarks = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    status = Column(Enum(CatalogStatus), default=CatalogStatus.APPROVED)
    version = Column(Integer, default=1)
    
    # Workflow metadata
    requested_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    
    daily_limit = Column(Integer, nullable=True)
    description = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    is_online_enabled = Column(Boolean, default=False, nullable=False, server_default=text("false"))
    available_prasadam_modes = Column(JSON, default=list)  # Defaults to ["COLLECT", "NONE"] at app level
    completion_mode = Column(String(30), default="AUTO_WITH_OVERRIDE")

    deity = relationship("DeityMaster")

class CatalogVersion(Base):
    """Historical versioning for ritual prices and metadata (Phase 4)."""
    __tablename__ = "archana_catalog_versions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    catalog_id = Column(UUID(as_uuid=True), ForeignKey("archana_catalog.id"), nullable=False)
    version = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    metadata_snapshot = Column(JSON, nullable=False) # Stores name, deity_id, duration
    effective_from = Column(DateTime(timezone=True), default=utcnow)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

class EnterpriseArchanaBooking(Base):
    """Enterprise-grade Archana Booking header (Booking entity)."""
    __tablename__ = "enterprise_archana_bookings"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    ref_id = Column(String, index=True)
    primary_devotee_id = Column(UUID(as_uuid=True), ForeignKey("devotees.id"), nullable=True)
    primary_devotee_name = Column(String, nullable=False)
    phone_number = Column(String, nullable=True)
    email = Column(String, nullable=True)
    whatsapp_consent = Column(Boolean, default=False)
    booking_date = Column(DateTime(timezone=True), default=utcnow)
    ritual_time = Column(DateTime(timezone=True), nullable=True)
    priority_slot = Column(Boolean, default=False)
    total_amount = Column(Float, default=0.0)
    dakshina = Column(Float, default=0.0)
    delivery_charge = Column(Float, default=0.0)
    grand_total = Column(Float, default=0.0)
    payment_mode = Column(String, default="Cash")
    booking_mode = Column(String, default="Counter")
    prasadam_collection = Column(String, default="Collect Directly", nullable=False)
    status = Column(Enum(ArchanaStatus), default=ArchanaStatus.CONFIRMED)
    remarks = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    assigned_priest_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    idempotency_key = Column(String, nullable=True, index=True)

    devotee_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    online_status = Column(String(30), default="INITIATED")
    booking_channel = Column(String(20), default="COUNTER")
    gateway_order_id = Column(String(100), unique=True, nullable=True)
    payment_expiry_at = Column(DateTime(timezone=True), nullable=True)
    total_payable = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("temple_id", "ref_id", name="uq_archana_booking_ref_id"),
    )

    members = relationship("ArchanaBookingMember", back_populates="booking", cascade="all, delete-orphan")
    payments = relationship("ArchanaBookingPayment", back_populates="booking", cascade="all, delete-orphan")
    queue_entry = relationship("RitualQueue", back_populates="booking", uselist=False)

class ArchanaBookingMember(Base):
    """Individual devotees in a booking (BookingMember entity)."""
    __tablename__ = "archana_booking_members"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("enterprise_archana_bookings.id"), nullable=False)
    name = Column(String, nullable=False)
    nakshatra = Column(String, nullable=True)
    is_primary = Column(Boolean, default=False)
    
    booking = relationship("EnterpriseArchanaBooking", back_populates="members")
    items = relationship("ArchanaBookingItem", back_populates="member", cascade="all, delete-orphan")

class ArchanaBookingItem(Base):
    """Specific archanas booked for a member (BookingItem entity)."""
    __tablename__ = "archana_booking_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    member_id = Column(UUID(as_uuid=True), ForeignKey("archana_booking_members.id"), nullable=False)
    service_id = Column(UUID(as_uuid=True), ForeignKey("archana_catalog.id"), nullable=False)
    quantity = Column(Integer, default=1)
    
    # PHASE 4: IMMUTABLE SNAPSHOTS
    price_at_booking = Column(Float, nullable=False)
    ritual_name_snapshot = Column(String, nullable=True)
    ritual_deity_snapshot = Column(String, nullable=True)
    ritual_duration_snapshot = Column(Integer, nullable=True)
    ritual_version_id = Column(Integer, nullable=True)
    
    total_price = Column(Float, nullable=False)
    
    member = relationship("ArchanaBookingMember", back_populates="items")
    service = relationship("ArchanaCatalog")
    execution = relationship("ArchanaExecution", back_populates="item", uselist=False)

class ArchanaExecution(Base):
    """Tracking individual ritual execution lifecycle (ArchanaExecution entity)."""
    __tablename__ = "archana_executions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    booking_item_id = Column(UUID(as_uuid=True), ForeignKey("archana_booking_items.id"), nullable=False, unique=True)
    queue_id = Column(UUID(as_uuid=True), ForeignKey("ritual_queue.id"), nullable=False)
    
    status = Column(Enum(QueueStatus), default=QueueStatus.WAITING)
    priest_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    
    start_time = Column(DateTime(timezone=True), nullable=True)
    expected_completion_time = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    
    auto_completed = Column(Boolean, default=False)
    completion_mode = Column(Enum(CompletionMode), nullable=True)
    execution_group_id = Column(UUID(as_uuid=True), ForeignKey("archana_execution_groups.id"), nullable=True, index=True)
    version_number = Column(Integer, default=1) # Optimistic locking
    
    started_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    completed_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    group = relationship("ArchanaExecutionGroup", back_populates="executions")
    
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
 
    item = relationship("ArchanaBookingItem", back_populates="execution")
    queue = relationship("RitualQueue", back_populates="executions")
    priest = relationship("Employee")
    started_by = relationship("User", foreign_keys=[started_by_user_id])
    completed_by = relationship("User", foreign_keys=[completed_by_user_id])
    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_user_id])


class ArchanaBookingPayment(Base):
    """Payment details for the booking (BookingPayment entity)."""
    __tablename__ = "archana_booking_payments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("enterprise_archana_bookings.id"), nullable=False)
    amount = Column(Float, nullable=False)
    payment_mode = Column(String, nullable=False)
    transaction_ref = Column(String, nullable=True)
    status = Column(String, default="SUCCESS")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    
    gateway_payment_id = Column(String(100), unique=True, nullable=True)
    gateway_order_id = Column(String(100), nullable=True)
    gateway_method = Column(String(30), nullable=True)
    gateway_fee = Column(Float, default=0.0)
    gateway_tax = Column(Float, default=0.0)
    archana_amount = Column(Float, nullable=True)
    convenience_fee = Column(Float, default=0.0)
    total_amount_charged = Column(Float, nullable=True)
    webhook_payload = Column(JSON, nullable=True)
    webhook_received_at = Column(DateTime(timezone=True), nullable=True)
    settlement_status = Column(String(30), default="PENDING")

    booking = relationship("EnterpriseArchanaBooking", back_populates="payments")

class RitualQueue(Base):
    """Operational ritual queue system (RitualQueue entity)."""
    __tablename__ = "ritual_queue"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("enterprise_archana_bookings.id"), nullable=False, unique=True)
    token_number = Column(String, nullable=False)
    status = Column(Enum(QueueStatus), default=QueueStatus.WAITING)
    priest_id = Column(UUID(as_uuid=True), ForeignKey("employees.id"), nullable=True)
    priority = Column(Integer, default=0)
    estimated_start_time = Column(DateTime(timezone=True), nullable=True)
    actual_start_time = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    
    booking = relationship("EnterpriseArchanaBooking", back_populates="queue_entry")
    executions = relationship("ArchanaExecution", back_populates="queue", cascade="all, delete-orphan")

class ArchanaBookingAudit(Base):
    """Specialized audit log for bookings (BookingAudit entity)."""
    __tablename__ = "archana_booking_audit"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("enterprise_archana_bookings.id"), nullable=False)
    action = Column(String, nullable=False)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    old_state = Column(JSON, nullable=True)
    new_state = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow)

class ArchanaSyncState(Base):
    """Sync metadata for hybrid readiness (BookingSyncState entity)."""
    __tablename__ = "archana_sync_state"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    sync_status = Column(String, default="SYNCED")
    version = Column(Integer, default=1)

class ArchanaRefund(Base):
    """Operational refund records for cancelled or adjusted bookings."""
    __tablename__ = "archana_refunds"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    ref_id = Column(String, index=True)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("enterprise_archana_bookings.id"), nullable=False, index=True)
    refund_method = Column(String, nullable=False) # Cash, UPI
    refund_status = Column(String, nullable=False) # Full, Partial
    status = Column(String, default="PENDING") # PENDING, APPROVED, CANCELLED
    amount = Column(Float, nullable=False)
    reason = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    
    gateway_refund_id = Column(String(100), unique=True, nullable=True)
    gateway_refund_status = Column(String(50), nullable=True)
    refund_initiated_at = Column(DateTime(timezone=True), nullable=True)
    refund_settled_at = Column(DateTime(timezone=True), nullable=True)
    archana_refund_amount = Column(Float, nullable=True)
    fee_refund_amount = Column(Float, nullable=True)
    total_refund_amount = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("temple_id", "ref_id", name="uq_archana_refund_ref_id"),
    )

    booking = relationship("EnterpriseArchanaBooking")





class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=True)  # NULL means global fallback template
    event_code = Column(String(100), nullable=False)
    channel = Column(String(20), nullable=False)  # 'PUSH', 'SMS', 'EMAIL'
    title_template = Column(String(255), nullable=True)
    body_template = Column(Text, nullable=False)
    language = Column(String(5), nullable=False, default="en")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    
    __table_args__ = (
        UniqueConstraint("temple_id", "event_code", "channel", "language", name="uq_notification_template"),
    )


class NotificationDeliveryLog(Base):
    __tablename__ = "notification_delivery_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    outbox_event_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # Corresponds to ActivityOutbox.id
    recipient_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    channel = Column(String(20), nullable=False)
    recipient_address = Column(String(150), nullable=False)
    status = Column(String(20), nullable=False, default="SENT")  # 'SENT', 'FAILED'
    failure_reason = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

