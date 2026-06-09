"""Offerings Module — SQLAlchemy Models.

Tables: offering_categories, offerings, offering_payments, offering_receipts,
        offering_audit_logs, offering_inventory_links, offering_reconciliations
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, ForeignKey,
    Boolean, Text, Index, JSON, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from app.core.database.database import Base
def utcnow():
    return datetime.now(timezone.utc)


# ────────────────────────────────────────────────────────────────────
# 1. Offering Category
# ────────────────────────────────────────────────────────────────────
class OfferingCategory(Base):
    """Categorisation of offerings (e.g. Gold, Silver, Cash, Kind)."""
    __tablename__ = "offering_categories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    category_name = Column(String, nullable=False)
    category_code = Column(String, nullable=False)
    color_code = Column(String, nullable=True)
    icon = Column(String, nullable=True)
    receipt_prefix = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


from sqlalchemy.orm import validates

# ────────────────────────────────────────────────────────────────────
# 2. Offering (master record)
# ────────────────────────────────────────────────────────────────────
class Offering(Base):
    """Core offering / donation record."""
    __tablename__ = "offerings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    offering_number = Column(String, nullable=False)
    donor_name = Column(String, nullable=False)
    donor_phone = Column(String, nullable=True)
    donor_address = Column(Text, nullable=True)
    donor_email = Column(String(200), nullable=True)
    offering_type = Column(String(50), nullable=True)
    notification_mode = Column(String(20), nullable=True)
    notification_destination = Column(String(200), nullable=True)
    offering_metadata = Column(JSON, nullable=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("offering_categories.id"), nullable=True)
    total_amount = Column(Float, nullable=False)
    paid_amount = Column(Float, default=0)
    balance_amount = Column(Float, default=0)
    payment_status = Column(String, default="CREATED")       # CREATED, PENDING, PAID, FAILED, CANCELLED
    payment_method = Column(String, nullable=True)            # Cash / UPI / Card / NetBanking / Split
    booking_mode = Column(String, default="Counter")
    remarks = Column(Text, nullable=True)
    offering_status = Column(String, default="CONFIRMED")
    receipt_id = Column(UUID(as_uuid=True), ForeignKey("offering_receipts.id"), nullable=True)
    created_by = Column(String, nullable=True)
    verified_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    @validates("offering_type")
    def validate_offering_type(self, key, value):
        if value is not None and value not in ("GENERAL", "VAZHIPADU", "DONATION", "ANNADANAM"):
            raise ValueError(f"Invalid offering_type: {value}")
        return value


    # Offline / sync fields
    local_uuid = Column(String, nullable=True)
    sync_status = Column(String, default="SYNCED")
    sync_version = Column(Integer, default=1)
    source_device_id = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("temple_id", "offering_number", name="uq_offering_number"),
        Index("idx_offering_temple", "temple_id"),
        Index("idx_offering_number", "offering_number"),
        Index("idx_offering_status", "temple_id", "payment_status"),
    )


# ────────────────────────────────────────────────────────────────────
# 3. Offering Payment
# ────────────────────────────────────────────────────────────────────
class OfferingPayment(Base):
    """Individual payment against an offering."""
    __tablename__ = "offering_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offering_id = Column(UUID(as_uuid=True), ForeignKey("offerings.id"), nullable=False)
    transaction_number = Column(String, nullable=False)
    payment_method = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    gateway_reference = Column(String, nullable=True)
    payment_date = Column(DateTime(timezone=True), default=utcnow)
    received_by = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    sync_status = Column(String, default="SYNCED")
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ────────────────────────────────────────────────────────────────────
# 4. Offering Receipt
# ────────────────────────────────────────────────────────────────────
class OfferingReceipt(Base):
    """Receipt generated for an offering."""
    __tablename__ = "offering_receipts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    offering_id = Column(UUID(as_uuid=True), ForeignKey("offerings.id"), nullable=True)
    receipt_number = Column(String, nullable=False)
    receipt_type = Column(String, default="STANDARD")
    generated_at = Column(DateTime(timezone=True), default=utcnow)
    generated_by = Column(String, nullable=True)
    pdf_path = Column(String, nullable=True)
    qr_code = Column(String, nullable=True)
    print_count = Column(Integer, default=0)
    whatsapp_shared = Column(Boolean, default=False)
    email_shared = Column(Boolean, default=False)


# ────────────────────────────────────────────────────────────────────
# 5. Offering Audit Log
# ────────────────────────────────────────────────────────────────────
class OfferingAuditLog(Base):
    """Audit trail for offering mutations."""
    __tablename__ = "offering_audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offering_id = Column(UUID(as_uuid=True), ForeignKey("offerings.id"), nullable=True)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    action_type = Column(String, nullable=False)
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    changed_by = Column(String, nullable=True)
    changed_at = Column(DateTime(timezone=True), default=utcnow)
    ip_address = Column(String, nullable=True)
    device_info = Column(String, nullable=True)


# ────────────────────────────────────────────────────────────────────
# 6. Offering Inventory Link
# ────────────────────────────────────────────────────────────────────
class OfferingInventoryLink(Base):
    """Links an offering to a physical inventory item (gold, silver, etc.)."""
    __tablename__ = "offering_inventory_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offering_id = Column(UUID(as_uuid=True), ForeignKey("offerings.id"), nullable=False)
    metal_type = Column(String, nullable=False)
    purity = Column(String, nullable=True)
    weight = Column(Float, nullable=False)
    estimated_value = Column(Float, nullable=False)
    locker_reference = Column(String, nullable=True)
    photo_path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ────────────────────────────────────────────────────────────────────
# 7. Offering Reconciliation
# ────────────────────────────────────────────────────────────────────
class OfferingReconciliation(Base):
    """Daily / shift-wise reconciliation snapshot."""
    __tablename__ = "offering_reconciliations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    reconciliation_date = Column(DateTime(timezone=True), nullable=False)
    shift_name = Column(String, nullable=True)
    operator_name = Column(String, nullable=True)
    total_offerings_count = Column(Integer, default=0)
    total_amount = Column(Float, default=0)
    total_cash = Column(Float, default=0)
    total_upi = Column(Float, default=0)
    total_card = Column(Float, default=0)
    total_other = Column(Float, default=0)
    pending_balance = Column(Float, default=0)
    expected_total = Column(Float, default=0)
    actual_collected = Column(Float, default=0)
    variance = Column(Float, default=0)
    category_breakdown = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(String, default="OPEN")
    closed_by = Column(String, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
