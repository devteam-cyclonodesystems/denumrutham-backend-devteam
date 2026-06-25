import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, JSON, Index, text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class BankAccountStatus(str, enum.Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    DISABLED = "DISABLED"

class PlatformFinancialAccount(Base):
    __tablename__ = "platform_financial_accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_name = Column(String(150), nullable=False)
    account_identifier = Column(Text, nullable=False)  # IBAN, UPI, Razorpay Merchant ID
    account_type = Column(String(50), nullable=False)  # BANK, UPI, ESCROW, GATEWAY
    bank_name = Column(String(150), nullable=True)
    ifsc_code = Column(String(11), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

class TempleBankAccount(Base):
    __tablename__ = "temple_bank_accounts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    account_holder_name = Column(String(255), nullable=False)
    bank_name = Column(String(150), nullable=False)
    account_number_enc = Column(Text, nullable=False)  # AES-256 encrypted account number
    ifsc_code = Column(String(11), nullable=False)
    account_type = Column(String(30), nullable=False, default="SAVINGS")  # 'SAVINGS', 'CURRENT'
    cancelled_cheque_url = Column(Text, nullable=True)
    proof_uploaded_at = Column(DateTime(timezone=True), nullable=True)
    
    # Logical Versioning & Effective Date Tracking
    version = Column(Integer, nullable=False, default=1)
    superseded_by = Column(UUID(as_uuid=True), ForeignKey("temple_bank_accounts.id"), nullable=True)
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    
    verification_status = Column(Enum(BankAccountStatus), nullable=False, default=BankAccountStatus.PENDING)
    verified_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    
    is_active = Column(Boolean, nullable=False, default=False)
    is_primary = Column(Boolean, nullable=False, default=False)
    submitted_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

class OnlineSettlementLedger(Base):
    __tablename__ = "online_settlement_ledger"
    
    __table_args__ = (
        Index(
            "uq_ledger_credit_booking",
            "booking_id",
            unique=True,
            postgresql_where=text("entry_type = 'CREDIT'"),
            sqlite_where=text("entry_type = 'CREDIT'")
        ),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("enterprise_archana_bookings.id"), nullable=False)
    payment_id = Column(UUID(as_uuid=True), ForeignKey("archana_booking_payments.id"), nullable=False)
    entry_type = Column(String(30), nullable=False)  # 'CREDIT', 'REFUND_DEBIT', etc.
    
    # Immutability Notice: The following financial amount fields must NEVER be updated once written.
    archana_amount = Column(Float, nullable=False)
    temple_net_amount = Column(Float, nullable=False)
    
    gross_convenience_fee = Column(Float, nullable=False)
    taxable_fee = Column(Float, nullable=False)
    gst_component = Column(Float, nullable=False)
    cgst_component = Column(Float, nullable=False)
    sgst_component = Column(Float, nullable=False)
    
    gateway_fee = Column(Float, default=0.0)
    gateway_tax = Column(Float, default=0.0)
    
    net_platform_revenue = Column(Float, nullable=False)
    total_charged_to_devotee = Column(Float, nullable=False)
    
    # Mutable settlement metadata fields:
    settlement_batch_id = Column(UUID(as_uuid=True), ForeignKey("settlement_batches.id"), nullable=True, index=True)
    is_settled = Column(Boolean, nullable=False, default=False, index=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    
    gateway_payment_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    notes = Column(Text, nullable=True)
    
    # Idempotency safety
    idempotency_key = Column(String(255), unique=True, nullable=True)

class SettlementBatch(Base):
    __tablename__ = "settlement_batches"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    batch_ref = Column(String(100), unique=True, nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    
    transaction_count = Column(Integer, nullable=False, default=0)
    total_archana_amount = Column(Float, nullable=False, default=0.0)
    total_refunds = Column(Float, nullable=False, default=0.0)
    net_payout_amount = Column(Float, nullable=False)
    
    status = Column(String(30), nullable=False, default="PENDING")  # 'PENDING', 'APPROVED', 'PROCESSING', 'COMPLETED'
    
    approved_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    
    payout_method = Column(String(20), default="NEFT")
    payout_reference = Column(String(100), nullable=True)  # Bank UTR / Transaction Reference
    
    # Track the exact bank account version used for this payout
    bank_account_id = Column(UUID(as_uuid=True), ForeignKey("temple_bank_accounts.id"), nullable=True)
    
    payout_initiated_at = Column(DateTime(timezone=True), nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    notes = Column(Text, nullable=True)
    
    # Idempotency safety
    idempotency_key = Column(String(255), unique=True, nullable=True)

    __table_args__ = (
        UniqueConstraint("temple_id", "period_start", "period_end", name="uq_temple_period"),
    )

class SettlementBatchItem(Base):
    __tablename__ = "settlement_batch_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("settlement_batches.id", ondelete="CASCADE"), nullable=False)
    ledger_entry_id = Column(UUID(as_uuid=True), ForeignKey("online_settlement_ledger.id"), unique=True, nullable=False)
