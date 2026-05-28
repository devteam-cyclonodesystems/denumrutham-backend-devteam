from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional, List
from datetime import datetime, date

# ---------- Store Product ----------
class StoreProductCreate(BaseModel):
    name: str
    category: str = "Other"
    unit: str = "piece"
    unit_price: float = 0.0
    supplier_id: Optional[UUID4] = None
    barcode: Optional[str] = None
    sku: Optional[str] = None
    qr_code: Optional[str] = None
    media: Optional[List[str]] = None

class StoreProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    supplier_id: Optional[UUID4] = None
    barcode: Optional[str] = None
    sku: Optional[str] = None
    qr_code: Optional[str] = None
    media: Optional[List[str]] = None

class StoreProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    name: str
    category: str
    unit: str
    unit_price: float
    supplier_id: Optional[UUID4]
    barcode: Optional[str]
    sku: Optional[str]
    qr_code: Optional[str]
    rating: float
    is_active: bool
    media: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime

# ---------- Store Sales Order ----------
class SalesOrderItemCreate(BaseModel):
    product_id: UUID4
    quantity: float
    unit_price: float

class StoreSalesOrderCreate(BaseModel):
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    items: List[SalesOrderItemCreate]
    payment_mode: str = "Cash" # Cash, Card, UPI
    idempotency_key: Optional[str] = None

class StoreSalesOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    order_number: str
    customer_name: Optional[str]
    customer_phone: Optional[str]
    total_amount: float
    payment_mode: str
    status: str
    created_by: Optional[UUID4]
    idempotency_key: Optional[str]
    created_at: datetime
    updated_at: datetime

# ---------- Auction Listing ----------
class AuctionBidResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    auction_id: UUID4
    bidder_name: str
    bid_amount: float
    created_at: datetime

class AuctionListingCreate(BaseModel):
    product_id: UUID4
    quantity: float
    start_price: float = 0.0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    remarks: Optional[str] = None
    media: Optional[List[str]] = None

class AuctionListingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    product_id: UUID4
    auction_code: Optional[str]
    quantity: float
    start_price: float
    current_bid: float
    status: str
    is_active: bool
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    product: Optional[StoreProductResponse] = None
    bids: Optional[List[AuctionBidResponse]] = []
    remarks: Optional[str] = None
    media: Optional[List[str]] = None

class AuctionListingUpdate(BaseModel):
    quantity: Optional[float] = None
    start_price: Optional[float] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    is_active: Optional[bool] = None
    remarks: Optional[str] = None
    media: Optional[List[str]] = None
