from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional, List
from datetime import datetime


# ---------- Inventory Item ----------
class InventoryItemCreate(BaseModel):
    name: str
    category: str = "Other"
    unit: str = "piece"
    qty: int = 0
    min_stock: int = 10
    unit_price: float = 0.0
    supplier_name: str = ""
    purchase_mode: str = "Local"
    remarks: str = ""


class InventoryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    name: str
    stock: int
    category: Optional[str] = "Other"
    unit: Optional[str] = "piece"
    min_stock: Optional[int] = 10
    unit_price: Optional[float] = 0.0
    purchase_mode: Optional[str] = "Local"
    remarks: Optional[str] = ""
    created_at: Optional[datetime] = None


# ---------- Supplier ----------
class SupplierCreate(BaseModel):
    name: str
    contact: str = ""
    alt_contact: str = ""
    email: str = ""
    address: str = ""
    items_supplied: str = ""
    last_delivery: str = ""
    remarks: str = ""


class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    sup_code: Optional[str] = None
    name: str
    contact: str
    alt_contact: str
    email: str
    address: str
    items_supplied: str
    last_delivery: str
    remarks: str
    created_at: datetime


# ---------- Invoice ----------
class InvoiceCreate(BaseModel):
    """Matches inventory.js saveInvoice() payload."""
    ref_number: str = ""
    supplier_name: str = ""
    date: str = ""
    items_summary: str = ""
    items: List[dict] = []  # [{item_id, qty, price}]
    amount: float = 0.0
    order_mode: str = "Phone"
    payment_mode: str = "Cash"
    status: str = "Completed"
    remarks: str = ""
    target_domain: str = "KALAVARA"


class DeliveryComplete(BaseModel):
    order_mode: str = "Phone"
    payment_mode: str = "Cash"
    remarks: str = ""



class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    ref_number: Optional[str] = None
    supplier_name: str
    date: str
    items_summary: str
    amount: float
    order_mode: str
    payment_mode: str
    remarks: str
    status: str
    items_data: Optional[List[dict]] = None
    created_by: str
    created_at: datetime
    grn_code: Optional[str] = None
    grn_created_at: Optional[datetime] = None
    target_domain: str = "KALAVARA"


# ---------- Item Request ----------
class ItemRequestCreate(BaseModel):
    date: str
    requester: str
    role: str = ""
    department: str = ""
    items_summary: str = ""
    items_data: List[dict] = []  # [{itemId, qty}]
    remarks: str = ""


class ItemRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    req_code: Optional[str] = None
    date: str
    requester: str
    role: str
    department: str
    items_summary: str
    items_data: Optional[List[dict]] = []
    remarks: str
    status: str
    created_by: str
    created_at: datetime


# ---------- Inventory Location ----------
class InventoryLocationCreate(BaseModel):
    name: str
    description: Optional[str] = None

class InventoryLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime


# ---------- Stock Ledger ----------
class StockLedgerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    item_id: UUID4
    location_id: Optional[UUID4]
    movement_type: str
    quantity_change: float
    before_stock: float
    after_stock: float
    reference_type: Optional[str]
    reference_id: Optional[str]
    performed_by: Optional[UUID4]
    remarks: Optional[str]
    timestamp: datetime


# ---------- Issue Session ----------
class IssueSessionCreate(BaseModel):
    request_id: UUID4
    location_id: Optional[UUID4] = None
    items: List[dict] = []  # [{itemId, qty}]
    remarks: Optional[str] = None

class IssueSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    request_id: UUID4
    issued_by: UUID4
    issued_at: datetime
    location_id: Optional[UUID4]
    status: str
    remarks: Optional[str]


# ---------- Procurement GRN ----------
class GRNCreate(BaseModel):
    supplier_id: UUID4
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    items: List[dict] = []  # [{itemId, qty, unitPrice}]
    remarks: Optional[str] = None

class GRNResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    grn_code: str
    supplier_id: UUID4
    invoice_number: Optional[str]
    total_amount: float
    received_by: UUID4
    status: str
    created_at: datetime


# ---------- Ritual Template ----------
class RitualTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    items: List[dict] = []  # [{itemId, defaultQty}]

class RitualTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    name: str
    description: Optional[str]
    is_active: bool
    created_at: datetime


# ---------- Reconciliation ----------
class ReconciliationCreate(BaseModel):
    item_id: UUID4
    actual_stock: float
    remarks: Optional[str] = None
