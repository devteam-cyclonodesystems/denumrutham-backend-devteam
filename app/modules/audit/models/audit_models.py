import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, BigInteger, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.core.database.base import Base

def utcnow():
    return datetime.now(timezone.utc)

class ImmutableActivityLog(Base):
    """Immutable, append-only historical database record of staff action."""
    __tablename__ = "immutable_activity_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    temple_code = Column(String(50), nullable=False)
    tenant_name = Column(String(150), nullable=False)
    module_name = Column(String(100), nullable=False)
    entity_name = Column(String(100), nullable=False)
    entity_id = Column(String(100), nullable=True)
    action_type = Column(String(100), nullable=False)
    action_category = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    before_value = Column(JSON, nullable=True)
    after_value = Column(JSON, nullable=True)
    performed_by_user_id = Column(UUID(as_uuid=True), nullable=False)
    performed_by_name = Column(String(255), nullable=False)
    performed_by_role = Column(String(100), nullable=False)
    
    # Hybrid PII fields
    masked_pii = Column(JSON, nullable=True)
    hashed_pii = Column(JSON, nullable=True)
    
    # Fingerprint fields
    ip_address = Column(String(45), nullable=False)
    device_info = Column(Text, nullable=True)
    browser_info = Column(Text, nullable=True)
    operating_system = Column(String(100), nullable=True)
    
    # Trace elements
    correlation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    request_id = Column(String(100), nullable=True)
    session_id = Column(String(100), nullable=True)
    
    # Severity & Risk Rating
    severity = Column(String(50), nullable=False, default="LOW")
    risk_score = Column(Integer, nullable=False, default=10)
    
    # Cryptographic Chain Validation
    previous_hash = Column(String(64), nullable=False)
    current_hash = Column(String(64), nullable=False)
    audit_chain_index = Column(BigInteger, nullable=False)
    
    # Created Timestamp (part of composite primary key for table partitioning)
    created_utc = Column(DateTime(timezone=True), primary_key=True, default=utcnow, index=True)


class ActivityOutbox(Base):
    """Transactional Outbox buffering activity events to keep transaction routes non-blocking."""
    __tablename__ = "activity_outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), nullable=False)
    module_name = Column(String(100), nullable=False)
    entity_name = Column(String(100), nullable=False)
    entity_id = Column(String(100), nullable=True)
    action_type = Column(String(100), nullable=False)
    action_category = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    before_value = Column(JSON, nullable=True)
    after_value = Column(JSON, nullable=True)
    performed_by_user_id = Column(UUID(as_uuid=True), nullable=False)
    performed_by_name = Column(String(255), nullable=False)
    performed_by_role = Column(String(100), nullable=False)
    masked_pii = Column(JSON, nullable=True)
    hashed_pii = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=False)
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    request_id = Column(String(100), nullable=True)
    severity = Column(String(50), nullable=False, default="LOW")
    risk_score = Column(Integer, nullable=False, default=10)
    created_at = Column(DateTime(timezone=True), default=utcnow)


from sqlalchemy import event

@event.listens_for(ImmutableActivityLog, "before_update")
def block_updates(mapper, connection, target):
    raise PermissionError("Mutation Denied: Activity log entries are strictly immutable.")

@event.listens_for(ImmutableActivityLog, "before_delete")
def block_deletes(mapper, connection, target):
    raise PermissionError("Mutation Denied: Activity log entries are strictly immutable.")
