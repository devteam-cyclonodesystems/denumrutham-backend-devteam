import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, Time, UniqueConstraint, Date, JSON, Index, text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database.database import Base
from app.modules.bookings.models.booking_models import PaymentMethod


def utcnow():
    return datetime.now(timezone.utc)


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PaymentMethod(str, enum.Enum):
    UPI_QR = "UPI_QR"
    CASH = "CASH"
    CARD = "CARD"
    NET_BANKING = "NET_BANKING"


class Donation(Base):
    __tablename__ = "donations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    devotee_id = Column(UUID(as_uuid=True), ForeignKey("devotees.id"), nullable=True)
    amount = Column(Float, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class Payment(Base):
    __tablename__ = "payments"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    reference_id = Column(UUID(as_uuid=True), nullable=False)
    amount = Column(Float, nullable=False)
    provider_ref = Column(String)
    transaction_id = Column(String, unique=True, index=True, nullable=True)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    payment_method = Column(Enum(PaymentMethod), nullable=True)
    service_booking_id = Column(UUID(as_uuid=True), ForeignKey("service_bookings.id"), nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class TransactionType(str, enum.Enum):
    INCOME = "income"
    EXPENSE = "expense"




class TransactionCategory(str, enum.Enum):
    ARCHANA = "archana"
    HALL_BOOKING = "hall_booking"
    SALARY = "salary"
    PURCHASE = "purchase"
    DONATION = "donation"
    OFFERING = "offering"
    STORE = "store"
    OTHER = "other"




class Transaction(Base):
    """Financial transaction — single source of truth for all money flows."""
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    type = Column(Enum(TransactionType), nullable=False)  # income | expense
    category = Column(Enum(TransactionCategory), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(Text, default="")
    reference_id = Column(String, nullable=True)  # e.g. HB001/0326 or AR01/0226
    source = Column(String, default="system")  # system | manual
    date = Column(DateTime(timezone=True), default=utcnow)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class TempleCodeSequence(Base):
    """Race-free daily sequence generator for temple_code."""
    __tablename__ = "temple_code_sequences"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(Date, unique=True, nullable=False, index=True) # YYYY-MM-DD
    last_val = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


