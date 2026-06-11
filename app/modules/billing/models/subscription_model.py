import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, backref
from app.core.database.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class SubscriptionStatus(str, enum.Enum):
    PENDING = "PENDING"
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    HALTED = "HALTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, unique=True)
    razorpay_subscription_id = Column(String(80), unique=True, index=True, nullable=True)
    razorpay_plan_id = Column(String(80), nullable=True)
    subscription_plan = Column(String(40), nullable=False, default="FREE")
    status = Column(String(30), nullable=False, default="ACTIVE")
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    trial_start = Column(DateTime(timezone=True), nullable=True)
    trial_end = Column(DateTime(timezone=True), nullable=True)
    grace_period_ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    temple = relationship("Temple", backref=backref("subscription", uselist=False, cascade="all, delete-orphan"))
    events = relationship("SubscriptionEvent", back_populates="subscription", cascade="all, delete-orphan")

class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True)
    event_name = Column(String(80), nullable=False)
    previous_status = Column(String(30), nullable=True)
    new_status = Column(String(30), nullable=True)
    payload_snapshot = Column(JSON, nullable=True)
    received_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationship
    subscription = relationship("Subscription", back_populates="events")
