import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Float, Text, Enum, Integer, Time, UniqueConstraint, Date, JSON, Index, text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database.base import Base
from app.models.operational_states import TempleOperationalState

def utcnow():
    return datetime.now(timezone.utc)


class InventoryItem(Base):
    __tablename__ = "kalavara_inventory_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    stock = Column(Float, default=0.0) # Deprecated - quantity is now in kalavara_stock
    # --- Enriched columns (additive) ---
    category = Column(String, default="Other")
    unit = Column(String, default="piece")
    min_stock = Column(Float, default=10.0)
    unit_price = Column(Float, default=0.0)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    purchase_mode = Column(String, default="Local")
    remarks = Column(Text, default="")
    
    # --- Enterprise Layer ---
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    
    # --- Unit Conversion ---
    base_unit = Column(String, default="piece")
    purchase_unit = Column(String, default="piece")
    conversion_ratio = Column(Float, default=1.0)
    
    # --- Soft Delete ---
    is_archived = Column(Boolean, default=False, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)




class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey("kalavara_inventory_items.id"), nullable=False)
    quantity_change = Column(Integer, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class InventoryTxnType(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"




class InventoryMovementType(str, enum.Enum):
    PURCHASE = "PURCHASE"
    ISSUE = "ISSUE"
    RETURN = "RETURN"
    DAMAGE = "DAMAGE"
    WASTAGE = "WASTAGE"
    TRANSFER = "TRANSFER"
    DONATION = "DONATION"
    ADJUSTMENT = "ADJUSTMENT"
    FESTIVAL_ALLOCATION = "FESTIVAL_ALLOCATION"
    SALE = "SALE"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    AUCTION_RESERVATION = "AUCTION_RESERVATION"
    AUCTION_RELEASE = "AUCTION_RELEASE"
    DONATION_ADDITION = "DONATION_ADDITION"
    RESTOCK = "RESTOCK"




class InventoryIssueStatus(str, enum.Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"




class ProcurementStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    INVOICED = "INVOICED"
    PENDING_DELIVERY = "PENDING_DELIVERY"
    RECEIVED = "RECEIVED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    DISPUTED = "DISPUTED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    COMPLETED = "COMPLETED"  # Backward compatibility




class Supplier(Base):
    """Inventory supplier."""
    __tablename__ = "suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    sup_code = Column(String, nullable=True)  # e.g. TSUP-001
    name = Column(String, nullable=False)
    contact = Column(String, default="")
    alt_contact = Column(String, default="")
    email = Column(String, default="")
    address = Column(String, default="")
    items_supplied = Column(String, default="")
    last_delivery = Column(String, default="")
    remarks = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # --- Soft Delete ---
    is_archived = Column(Boolean, default=False, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)




class InventoryInvoice(Base):
    """Purchase invoice for inventory."""
    __tablename__ = "inventory_invoices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    ref_number = Column(String, nullable=True)  # e.g. Inv001/0226
    supplier_name = Column(String, default="")
    date = Column(String, nullable=False)
    items_summary = Column(String, default="")
    amount = Column(Float, nullable=False, default=0.0)
    order_mode = Column(String, default="Phone")
    payment_mode = Column(String, default="Cash")
    remarks = Column(Text, default="")
    status = Column(String, default="Completed")  # Requested | Approved | Invoiced | Pending | Completed | Cancelled
    items_data = Column(JSON, default=list)  # Detailed list: [{item_id, qty, price, name}]
    created_by = Column(String, default="Admin")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # --- Enterprise Restocking & Payment Tracking ---
    target_domain = Column(String, default="KALAVARA", nullable=False) # STORE or KALAVARA
    due_date = Column(Date, nullable=True)
    paid_amount = Column(Float, default=0.0, nullable=False)
    outstanding_amount = Column(Float, default=0.0, nullable=False)
    payment_state = Column(String, default="UNPAID") # UNPAID, PARTIALLY_PAID, FULLY_PAID, OVERDUE
    idempotency_key = Column(String, unique=True, nullable=True)
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)

    # --- Soft Delete ---
    is_archived = Column(Boolean, default=False, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)




class SupplierPriceHistory(Base):
    """Tracks granular price shifts for individual items supplied by a vendor."""
    __tablename__ = "supplier_price_history"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False, index=True)
    item_name = Column(String, nullable=False)
    old_price = Column(Float, nullable=True)
    new_price = Column(Float, nullable=False)
    changed_by = Column(String, default="Admin")
    created_at = Column(DateTime(timezone=True), default=utcnow)




class InventoryItemRequest(Base):
    """Item request from departments."""
    __tablename__ = "inventory_item_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    req_code = Column(String, nullable=True)  # e.g. REQ-001
    date = Column(String, nullable=False)
    requester = Column(String, nullable=False)
    role = Column(String, default="")
    department = Column(String, default="")
    items_summary = Column(String, default="")
    items_data = Column(JSON, default=list)  # [{itemId, qty}]
    remarks = Column(Text, default="")
    status = Column(String, default="Request Completed")
    created_by = Column(String, default="Admin")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    
    # Material Request fields
    priority = Column(String, default="Medium")
    purpose = Column(String, default="")
    requested_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    approved_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    issued_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    # Relationships
    requested_by_user = relationship("User", foreign_keys=[requested_by_user_id])
    approved_by_user = relationship("User", foreign_keys=[approved_by_user_id])
    issued_by_user = relationship("User", foreign_keys=[issued_by_user_id])




class InventoryTransaction(Base):
    """Stock IN/OUT transaction for inventory items."""
    __tablename__ = "inventory_transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey("kalavara_inventory_items.id"), nullable=False)
    type = Column(Enum(InventoryTxnType), nullable=False)  # IN | OUT
    quantity = Column(Integer, nullable=False)
    reference = Column(String, default="")  # invoice ref or request ref
    notes = Column(Text, default="")
    date = Column(DateTime(timezone=True), default=utcnow)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ====================================================================
# CHANGE REQUEST — Field-level change approval system
# ====================================================================



class InventoryLocation(Base):
    """Storage locations like Main Store, Kitchen, Puja Room."""
    __tablename__ = "inventory_locations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class InventoryStockLedger(Base):
    """Immutable append-only ledger for all inventory movements."""
    __tablename__ = "inventory_stock_ledger"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    
    # --- Polymorphic Keys ---
    domain_type = Column(String, default="KALAVARA", nullable=False) # STORE or KALAVARA
    store_product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id"), nullable=True)
    kalavara_item_id = Column(UUID(as_uuid=True), ForeignKey("kalavara_inventory_items.id"), nullable=True)
    item_name = Column(String, nullable=False)

    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    movement_type = Column(Enum(InventoryMovementType), nullable=False)
    quantity_change = Column(Float, nullable=False)
    before_stock = Column(Float, nullable=False)
    after_stock = Column(Float, nullable=False)
    reference_type = Column(String, nullable=True) # REQUEST, GRN, RECONCILIATION, RITUAL, DAMAGE
    reference_id = Column(String, nullable=True)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    remarks = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (
        CheckConstraint(
            "(domain_type = 'STORE' AND store_product_id IS NOT NULL AND kalavara_item_id IS NULL) OR "
            "(domain_type = 'KALAVARA' AND kalavara_item_id IS NOT NULL AND store_product_id IS NULL)",
            name="chk_ledger_polymorphic"
        ),
    )




class InventoryIssueSession(Base):
    """Operational record of physical stock issuance."""
    __tablename__ = "inventory_issue_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    request_id = Column(UUID(as_uuid=True), ForeignKey("inventory_item_requests.id"), nullable=False)
    issued_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    issued_at = Column(DateTime(timezone=True), default=utcnow)
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    status = Column(Enum(InventoryIssueStatus), default=InventoryIssueStatus.COMPLETED)
    remarks = Column(Text, nullable=True)




class ProcurementGRN(Base):
    """Goods Receipt Note - Formal intake of purchased stock."""
    __tablename__ = "procurement_grns"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    grn_code = Column(String, unique=True, index=True)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    invoice_number = Column(String, nullable=True)
    invoice_date = Column(Date, nullable=True)
    total_amount = Column(Float, default=0.0)
    received_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status = Column(Enum(ProcurementStatus), default=ProcurementStatus.COMPLETED)
    remarks = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # --- Enterprise Fields ---
    target_domain = Column(String, default="KALAVARA", nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    
    # --- Soft Delete ---
    is_archived = Column(Boolean, default=False, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)




class RitualTemplate(Base):
    """Standard inventory requirements for rituals."""
    __tablename__ = "ritual_templates"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)




class RitualTemplateItem(Base):
    """Items associated with a ritual template."""
    __tablename__ = "ritual_template_items"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_id = Column(UUID(as_uuid=True), ForeignKey("ritual_templates.id"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("kalavara_inventory_items.id"), nullable=False)
    default_qty = Column(Float, nullable=False, default=1.0)




class InventoryReconciliation(Base):
    """Stock audit session for correcting mismatches."""
    __tablename__ = "inventory_reconciliations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), nullable=False)
    expected_stock = Column(Float, nullable=False)
    actual_stock = Column(Float, nullable=False)
    adjustment_qty = Column(Float, nullable=False)
    performed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    remarks = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow)




class DonationInventoryMapping(Base):
    """Tracks utilization of donated inventory."""
    __tablename__ = "donation_inventory_mapping"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    donation_id = Column(UUID(as_uuid=True), ForeignKey("donations.id"), nullable=False)
    item_id = Column(UUID(as_uuid=True), ForeignKey("kalavara_inventory_items.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    status = Column(String, default="AVAILABLE") # AVAILABLE, CONSUMED
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


# ====================================================================
# TEMPLE STORE & DOMAIN-ISOLATED INVENTORY MODELS
# ====================================================================



class KalavaraStock(Base):
    """Operational stock quantities for Kalavara items."""
    __tablename__ = "kalavara_stock"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    item_id = Column(UUID(as_uuid=True), ForeignKey("kalavara_inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = Column(Float, default=0.0, nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    version_number = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    item = relationship("InventoryItem", foreign_keys=[item_id])




class StoreProduct(Base):
    """Catalog definition for storefront commercial items."""
    __tablename__ = "store_products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(String, default="Other")
    unit = Column(String, default="piece")
    unit_price = Column(Float, default=0.0)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=True)
    barcode = Column(String, nullable=True, index=True)
    sku = Column(String, nullable=True, index=True)
    qr_code = Column(String, nullable=True)
    rating = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    media = Column(JSON, default=list)
    
    # --- Unit Conversion ---
    base_unit = Column(String, default="piece")
    purchase_unit = Column(String, default="piece")
    conversion_ratio = Column(Float, default=1.0)

    # --- Soft Delete ---
    is_archived = Column(Boolean, default=False, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)




class StoreStock(Base):
    """Commercial stock balances for Store items."""
    __tablename__ = "store_stock"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity = Column(Float, default=0.0, nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    version_number = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    product = relationship("StoreProduct", foreign_keys=[product_id])




class StoreSalesOrder(Base):
    """Commercial storefront customer sales log."""
    __tablename__ = "store_sales_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    order_number = Column(String, nullable=False, unique=True, index=True)
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    total_amount = Column(Float, default=0.0, nullable=False)
    payment_mode = Column(String, default="Cash")  # Cash, Card, UPI
    status = Column(String, default="Completed")  # Completed, Cancelled
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)




class StoreSalesOrderItem(Base):
    """Individual product listing inside a storefront customer order."""
    __tablename__ = "store_sales_order_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id = Column(UUID(as_uuid=True), ForeignKey("store_sales_orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id"), nullable=False)
    quantity = Column(Float, nullable=False, default=1.0)
    unit_price = Column(Float, nullable=False, default=0.0)
    total_price = Column(Float, nullable=False, default=0.0)

    # Relationships
    order = relationship("StoreSalesOrder", backref="items")
    product = relationship("StoreProduct")




class AuctionListing(Base):
    """Inventory items listed for commercial auction bidding."""
    __tablename__ = "store_auctions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id"), nullable=False)
    auction_code = Column(String, unique=True, index=True)
    idempotency_key = Column(String, unique=True, nullable=True)
    quantity = Column(Float, nullable=False)
    start_price = Column(Float, default=0.0)
    current_bid = Column(Float, default=0.0)
    status = Column(String, default="AVAILABLE")  # AVAILABLE, RESERVED, SOLD, RELEASED
    is_active = Column(Boolean, default=True)
    
    # --- Schedules ---
    start_time = Column(DateTime(timezone=True), nullable=True)
    end_time = Column(DateTime(timezone=True), nullable=True)

    # --- Remarks & Media ---
    remarks = Column(String, nullable=True)
    media = Column(JSON, default=list, nullable=True)

    # --- Soft Delete ---
    is_archived = Column(Boolean, default=False, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    # Relationships
    product = relationship("StoreProduct")
    bids = relationship("AuctionBid", back_populates="auction", cascade="all, delete-orphan", order_by="desc(AuctionBid.created_at)")




class AuctionBid(Base):
    """Bidding event history for a commercial store auction."""
    __tablename__ = "store_auction_bids"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    auction_id = Column(UUID(as_uuid=True), ForeignKey("store_auctions.id", ondelete="CASCADE"), nullable=False, index=True)
    bidder_name = Column(String, nullable=False)
    bid_amount = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    auction = relationship("AuctionListing", back_populates="bids")




class StoreStockReservation(Base):
    """Active reservations preventing concurrency drift (e.g. for auctions / carts)."""
    __tablename__ = "store_stock_reservations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id", ondelete="CASCADE"), nullable=False)
    quantity_reserved = Column(Float, nullable=False)
    reservation_status = Column(String, default="RESERVED")  # RESERVED, RELEASED, CONFIRMED
    expires_at = Column(DateTime(timezone=True), nullable=False)
    reference_type = Column(String, nullable=True)  # AUCTION, ORDER, CART
    reference_id = Column(String, nullable=True)
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    product = relationship("StoreProduct")




class InventoryDailySnapshot(Base):
    """Historical daily snapshots for inventory valuation and audit metrics."""
    __tablename__ = "inventory_daily_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    domain_type = Column(String, nullable=False)  # STORE or KALAVARA
    store_product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id"), nullable=True)
    kalavara_item_id = Column(UUID(as_uuid=True), ForeignKey("kalavara_inventory_items.id"), nullable=True)
    quantity = Column(Float, default=0.0, nullable=False)
    inventory_value = Column(Float, default=0.0, nullable=False)
    average_procurement_cost = Column(Float, default=0.0, nullable=False)
    snapshot_date = Column(Date, nullable=False, index=True)
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "(domain_type = 'STORE' AND store_product_id IS NOT NULL AND kalavara_item_id IS NULL) OR "
            "(domain_type = 'KALAVARA' AND kalavara_item_id IS NOT NULL AND store_product_id IS NULL)",
            name="chk_snapshot_polymorphic"
        ),
    )




class ProcurementCostHistory(Base):
    """Historical procurement prices tracking inflation and supplier rates."""
    __tablename__ = "procurement_cost_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, index=True)
    domain_type = Column(String, nullable=False)  # STORE or KALAVARA
    store_product_id = Column(UUID(as_uuid=True), ForeignKey("store_products.id"), nullable=True)
    kalavara_item_id = Column(UUID(as_uuid=True), ForeignKey("kalavara_inventory_items.id"), nullable=True)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False)
    procurement_invoice_id = Column(UUID(as_uuid=True), ForeignKey("inventory_invoices.id"), nullable=False)
    unit_cost = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    total_cost = Column(Float, nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("inventory_locations.id"), nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "(domain_type = 'STORE' AND store_product_id IS NOT NULL AND kalavara_item_id IS NULL) OR "
            "(domain_type = 'KALAVARA' AND kalavara_item_id IS NOT NULL AND store_product_id IS NULL)",
            name="chk_cost_history_polymorphic"
        ),
    )
