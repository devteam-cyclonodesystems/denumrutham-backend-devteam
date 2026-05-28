
import uuid
from sqlalchemy import Column, String, DateTime, JSON, Index, Boolean, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from app.db.session import Base
from datetime import datetime, timezone

def utcnow():
    return datetime.now(timezone.utc)

class ProcessedEvent(Base):
    """
    Phase 7: Distributed Event Resilience.
    Tracks processed event IDs to ensure idempotency.
    """
    __tablename__ = "processed_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    processed_at = Column(DateTime(timezone=True), default=utcnow)
    payload = Column(JSON, nullable=True)
    status = Column(String, default="success") # success / failed
    error_message = Column(String, nullable=True)

class SyncCheckpoint(Base):
    """
    Phase 8: Offline Conflict Reconciliation.
    Tracks the last known good sync state per tenant/device.
    """
    __tablename__ = "sync_checkpoints"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String, nullable=False)
    last_sync_at = Column(DateTime(timezone=True), default=utcnow)
    last_version = Column(Integer, default=0)
    
    __table_args__ = (
        Index("idx_sync_checkpoint_device", "temple_id", "device_id", unique=True),
    )

class ConflictReport(Base):
    """
    Phase 8: Offline Conflict Reconciliation.
    Audit log for resolved conflicts.
    """
    __tablename__ = "conflict_reports"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    resolution_strategy = Column(String, nullable=False) # server_wins / client_wins / manual
    conflict_details = Column(JSON, nullable=False)
    resolved_at = Column(DateTime(timezone=True), default=utcnow)
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
