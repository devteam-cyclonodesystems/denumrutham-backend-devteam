"""Offerings Module — Pydantic v2 schemas."""
from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional, List, Any
from datetime import datetime


# ────────────────────────────────────────────────────────────────────
# Offering Category
# ────────────────────────────────────────────────────────────────────
class OfferingCategoryCreate(BaseModel):
    category_name: str
    category_code: str
    receipt_prefix: str
    color_code: Optional[str] = None
    icon: Optional[str] = None


class OfferingCategoryUpdate(BaseModel):
    category_name: Optional[str] = None
    category_code: Optional[str] = None
    receipt_prefix: Optional[str] = None
    color_code: Optional[str] = None
    icon: Optional[str] = None
    is_active: Optional[bool] = None


class OfferingCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    temple_id: UUID4
    category_name: str
    category_code: str
    color_code: Optional[str] = None
    icon: Optional[str] = None
    receipt_prefix: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


# ────────────────────────────────────────────────────────────────────
# Offering
# ────────────────────────────────────────────────────────────────────
class OfferingCreate(BaseModel):
    donor_name: str
    donor_phone: Optional[str] = None
    donor_address: Optional[str] = None
    category_id: UUID4
    total_amount: float
    paid_amount: Optional[float] = 0
    payment_method: Optional[str] = None
    booking_mode: Optional[str] = "Counter"
    remarks: Optional[str] = None
    created_at: Optional[datetime] = None
    # Metal / inventory fields (optional)
    metal_type: Optional[str] = None
    metal_purity: Optional[str] = None
    metal_weight: Optional[float] = None
    metal_estimated_value: Optional[float] = None
    metal_locker: Optional[str] = None


class OfferingUpdate(BaseModel):
    donor_name: Optional[str] = None
    donor_phone: Optional[str] = None
    donor_address: Optional[str] = None
    remarks: Optional[str] = None
    booking_mode: Optional[str] = None
    offering_status: Optional[str] = None


class OfferingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    temple_id: UUID4
    offering_number: str
    donor_name: str
    donor_phone: Optional[str] = None
    donor_address: Optional[str] = None
    category_id: Optional[UUID4] = None
    total_amount: float
    paid_amount: float
    balance_amount: float
    payment_status: str
    payment_method: Optional[str] = None
    booking_mode: Optional[str] = None
    remarks: Optional[str] = None
    offering_status: str
    receipt_id: Optional[UUID4] = None
    created_by: Optional[str] = None
    verified_by: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    local_uuid: Optional[str] = None
    sync_status: Optional[str] = None
    sync_version: Optional[int] = None
    source_device_id: Optional[str] = None
    # Joined display field
    category_name: Optional[str] = None


# ────────────────────────────────────────────────────────────────────
# Offering Payment
# ────────────────────────────────────────────────────────────────────
class OfferingPaymentCreate(BaseModel):
    payment_method: str
    amount: float
    gateway_reference: Optional[str] = None
    notes: Optional[str] = None


class OfferingPaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    offering_id: UUID4
    transaction_number: str
    payment_method: str
    amount: float
    gateway_reference: Optional[str] = None
    payment_date: Optional[datetime] = None
    received_by: Optional[str] = None
    notes: Optional[str] = None
    sync_status: Optional[str] = None
    created_at: datetime


# ────────────────────────────────────────────────────────────────────
# Audit Log
# ────────────────────────────────────────────────────────────────────
class OfferingAuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    offering_id: Optional[UUID4] = None
    temple_id: UUID4
    action_type: str
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    changed_by: Optional[str] = None
    changed_at: Optional[datetime] = None
    ip_address: Optional[str] = None
    device_info: Optional[str] = None


# ────────────────────────────────────────────────────────────────────
# Inventory Link
# ────────────────────────────────────────────────────────────────────
class OfferingInventoryLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    offering_id: UUID4
    metal_type: str
    purity: Optional[str] = None
    weight: float
    estimated_value: float
    locker_reference: Optional[str] = None
    photo_path: Optional[str] = None
    created_at: datetime


# ────────────────────────────────────────────────────────────────────
# Receipt (inline for detail response)
# ────────────────────────────────────────────────────────────────────
class OfferingReceiptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    temple_id: UUID4
    offering_id: Optional[UUID4] = None
    receipt_number: str
    receipt_type: Optional[str] = None
    generated_at: Optional[datetime] = None
    generated_by: Optional[str] = None
    pdf_path: Optional[str] = None
    qr_code: Optional[str] = None
    print_count: int
    whatsapp_shared: bool
    email_shared: bool


# ────────────────────────────────────────────────────────────────────
# Offering Detail (composite)
# ────────────────────────────────────────────────────────────────────
class OfferingDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    temple_id: UUID4
    offering_number: str
    donor_name: str
    donor_phone: Optional[str] = None
    donor_address: Optional[str] = None
    category_id: Optional[UUID4] = None
    category_name: Optional[str] = None
    total_amount: float
    paid_amount: float
    balance_amount: float
    payment_status: str
    payment_method: Optional[str] = None
    booking_mode: Optional[str] = None
    remarks: Optional[str] = None
    offering_status: str
    created_by: Optional[str] = None
    verified_by: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    sync_version: Optional[int] = None
    # Related collections
    payments: List[OfferingPaymentResponse] = []
    audit_logs: List[OfferingAuditLogResponse] = []
    inventory_links: List[OfferingInventoryLinkResponse] = []
    receipt: Optional[OfferingReceiptResponse] = None


# ────────────────────────────────────────────────────────────────────
# Reconciliation
# ────────────────────────────────────────────────────────────────────
class OfferingReconciliationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    temple_id: UUID4
    reconciliation_date: datetime
    shift_name: Optional[str] = None
    operator_name: Optional[str] = None
    total_offerings_count: int
    total_amount: float
    total_cash: float
    total_upi: float
    total_card: float
    total_other: float
    pending_balance: float
    expected_total: float
    actual_collected: float
    variance: float
    category_breakdown: Optional[Any] = None
    notes: Optional[str] = None
    status: str
    closed_by: Optional[str] = None
    closed_at: Optional[datetime] = None
    created_at: datetime


# ────────────────────────────────────────────────────────────────────
# Summary
# ────────────────────────────────────────────────────────────────────
class OfferingSummaryResponse(BaseModel):
    total_offerings: float
    total_donors: int
    total_receipts: int
    pending_payments: int
    today_total: float
    today_count: int
    category_totals: List[dict]


# ────────────────────────────────────────────────────────────────────
# Paginated list
# ────────────────────────────────────────────────────────────────────
class PaginatedOfferingsResponse(BaseModel):
    items: List[OfferingResponse]
    total: int
    page: int
    page_size: int
