"""Inventory API endpoints — Items, Suppliers, Invoices, Item Requests with tenant enforcement."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID
from app.api.deps import get_db, get_current_user, get_current_temple_id, require_permission
from app.schemas.domain import TokenData
from app.schemas.inventory import (
    InventoryItemCreate, InventoryItemResponse, InventoryItemUpdate,
    SupplierCreate, SupplierResponse,
    InvoiceCreate, InvoiceResponse, DeliveryComplete,
    ItemRequestCreate, ItemRequestResponse,
    InventoryLocationCreate, InventoryLocationResponse,
    IssueSessionCreate, IssueSessionResponse,
    RitualTemplateCreate, RitualTemplateResponse,
    ReconciliationCreate, StockLedgerResponse,
    PriceApprovalRequestResponse
)
from app.services.inventory_service import InventoryService

router = APIRouter()


# --- Items ---
@router.post("/items", response_model=InventoryItemResponse, tags=["inventory"])
async def create_item(
    item_in: InventoryItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.create_item(
        db=db, item_in=item_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None,
        username=current_user.username or "Admin" if current_user else "Admin",
        user_role=current_user.role or "SYSTEM" if current_user else "SYSTEM"
    )


@router.get("/items", response_model=List[InventoryItemResponse], tags=["inventory"])
async def list_items(
    skip: int = 0,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_items(db=db, temple_id=temple_id, skip=skip, limit=limit)


@router.patch("/items/{item_id}", response_model=InventoryItemResponse, tags=["inventory"])
async def update_item(
    item_id: str,
    item_in: InventoryItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.update_item(
        db=db, item_id=UUID(item_id), item_in=item_in.model_dump(exclude_unset=True), temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None,
        username=current_user.username or "Admin" if current_user else "Admin",
        user_role=current_user.role or "SYSTEM" if current_user else "SYSTEM"
    )


@router.get("/items/{item_id}/price-history", tags=["inventory"])
async def get_item_price_history(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_item_price_history(
        db=db, item_id=UUID(item_id), temple_id=temple_id
    )


# --- Suppliers ---
@router.post("/suppliers", response_model=SupplierResponse, tags=["inventory"])
async def create_supplier(
    sup_in: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.create_supplier(
        db=db, sup_in=sup_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None,
        username=current_user.username or "Admin" if current_user else "Admin",
        user_role=current_user.role or "SYSTEM" if current_user else "SYSTEM"
    )


@router.post("/vendor-update/{supplier_id}", response_model=SupplierResponse, tags=["inventory"])
async def update_supplier(
    supplier_id: str,
    sup_in: SupplierCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.update_supplier(
        db=db, supplier_id=UUID(supplier_id), sup_in=sup_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None,
        username=current_user.username or "Admin" if current_user else "Admin",
        user_role=current_user.role or "SYSTEM" if current_user else "SYSTEM"
    )


@router.get("/suppliers/{supplier_id}/history", tags=["inventory"])
async def get_supplier_history(
    supplier_id: str,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_supplier_history(db=db, supplier_id=UUID(supplier_id), temple_id=temple_id)


@router.get("/suppliers", response_model=List[SupplierResponse], tags=["inventory"])
async def list_suppliers(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_suppliers(db=db, temple_id=temple_id)


# --- Invoices ---
@router.post("/invoices", response_model=InvoiceResponse, tags=["inventory"])
async def create_invoice(
    inv_in: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.create_invoice(
        db=db, inv_in=inv_in, temple_id=temple_id,
        created_by=current_user.username or "Admin",
        user_id=current_user.sub if current_user.sub else None
    )


@router.get("/invoices", response_model=List[InvoiceResponse], tags=["inventory"])
async def list_invoices(
    skip: int = 0,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_invoices(db=db, temple_id=temple_id, skip=skip, limit=limit)


@router.post("/invoices/{invoice_id}/complete", response_model=InvoiceResponse, tags=["inventory"])
async def complete_delivery(
    invoice_id: str,
    delivery_in: Optional[DeliveryComplete] = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    print("DEBUG: INCOMING DELIVERY COMPLETE BODY:", delivery_in.model_dump() if delivery_in else None, flush=True)
    return await InventoryService.complete_delivery(
        db=db,
        invoice_id=UUID(invoice_id),
        temple_id=temple_id,
        user_id=current_user.sub if current_user.sub else None,
        delivery_in=delivery_in
    )


@router.post("/invoices/{invoice_id}/pay-due", response_model=InvoiceResponse, tags=["inventory"])
async def pay_due(
    invoice_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.pay_due(
        db=db,
        invoice_id=UUID(invoice_id),
        temple_id=temple_id,
        user_id=current_user.sub if current_user.sub else None,
        remarks=payload.get("remarks", ""),
        payment_mode=payload.get("payment_mode", "Cash"),
        paid_amount=payload.get("paid_amount", 0.0),
    )


@router.post("/invoices/{invoice_id}/cancel", tags=["inventory"])
async def cancel_invoice(
    invoice_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.cancel_invoice(
        db=db,
        invoice_id=UUID(invoice_id),
        temple_id=temple_id,
        user_id=current_user.sub if current_user.sub else None,
        reason=payload.get("reason", "")
    )


# --- Item Requests ---
@router.post("/item-requests", response_model=ItemRequestResponse, tags=["inventory"])
async def create_item_request(
    req_in: ItemRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("inventory", "create_request")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.create_item_request(
        db=db, req_in=req_in, temple_id=temple_id,
        created_by=current_user.username or "Admin",
        user_id=UUID(current_user.sub) if current_user.sub else None
    )


@router.get("/item-requests", response_model=List[ItemRequestResponse], tags=["inventory"])
async def list_item_requests(
    skip: int = 0,
    limit: int = 500,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("inventory", "view_request")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_item_requests(db=db, temple_id=temple_id, skip=skip, limit=limit)


@router.post("/item-requests/{request_id}/approve", response_model=ItemRequestResponse, tags=["inventory"])
async def approve_item_request(
    request_id: UUID,
    approved_items: List[dict],
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("inventory", "approve_request")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.approve_item_request(
        db=db, request_id=request_id, approved_items=approved_items,
        temple_id=temple_id, user_id=UUID(current_user.sub)
    )


@router.post("/item-requests/{request_id}/reject", response_model=ItemRequestResponse, tags=["inventory"])
async def reject_item_request(
    request_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("inventory", "approve_request")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.reject_item_request(
        db=db, request_id=request_id, remarks=payload.get("remarks", ""),
        temple_id=temple_id, user_id=UUID(current_user.sub)
    )


@router.post("/item-requests/{request_id}/cancel", response_model=ItemRequestResponse, tags=["inventory"])
async def cancel_item_request(
    request_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("inventory", "cancel_request")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.cancel_item_request(
        db=db, request_id=request_id, remarks=payload.get("remarks", ""),
        temple_id=temple_id, user_id=UUID(current_user.sub)
    )


@router.post("/item-requests/{request_id}/issue", response_model=ItemRequestResponse, tags=["inventory"])
async def issue_item_request(
    request_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("inventory", "issue_stock")),
    temple_id: str = Depends(get_current_temple_id),
):
    issued_items = payload.get("issued_items", [])
    location_id = payload.get("location_id")
    location_uuid = UUID(str(location_id)) if location_id else None
    return await InventoryService.issue_item_request_stock(
        db=db, request_id=request_id, issued_items=issued_items,
        location_id=location_uuid, temple_id=temple_id, user_id=UUID(current_user.sub)
    )


# --- Enterprise Features ---

@router.get("/locations", response_model=List[InventoryLocationResponse], tags=["inventory"])
async def list_locations(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_locations(db=db, temple_id=temple_id)


@router.post("/locations", response_model=InventoryLocationResponse, tags=["inventory"])
async def create_location(
    loc_in: InventoryLocationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.create_location(
        db=db, loc_in=loc_in, temple_id=temple_id,
        user_id=UUID(str(current_user.sub)) if current_user and current_user.sub else None
    )


@router.post("/issue-sessions", response_model=IssueSessionResponse, tags=["inventory"])
async def create_issue_session(
    session_in: IssueSessionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.create_issue_session(
        db=db, session_in=session_in, temple_id=temple_id,
        user_id=current_user.sub
    )


@router.post("/reconcile", tags=["inventory"])
async def reconcile_stock(
    recon_in: ReconciliationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.reconcile_stock(
        db=db, recon_in=recon_in, temple_id=temple_id,
        user_id=current_user.sub
    )


@router.get("/ritual-templates", response_model=List[RitualTemplateResponse], tags=["inventory"])
async def list_ritual_templates(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_ritual_templates(db=db, temple_id=temple_id)


@router.post("/ritual-templates", response_model=RitualTemplateResponse, tags=["inventory"])
async def create_ritual_template(
    temp_in: RitualTemplateCreate,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.create_ritual_template(db=db, temp_in=temp_in, temple_id=temple_id)


@router.get("/ledger", response_model=List[StockLedgerResponse], tags=["inventory"])
async def get_ledger(
    skip: int = 0,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.get_ledger(db=db, temple_id=temple_id, skip=skip, limit=limit)


@router.get("/status/low-stock", tags=["inventory"])
async def get_low_stock_status(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    count = await InventoryService.get_low_stock_count(db=db, temple_id=temple_id)
    items = await InventoryService.get_low_stock_items(db=db, temple_id=temple_id)
    return {"count": count, "items": items}


@router.post("/item-requests/{request_id}/returns", tags=["inventory"])
async def record_item_return(
    request_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("inventory", "return_items")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await InventoryService.record_return(
        db=db,
        request_id=request_id,
        items=payload.get("items", []),
        remarks=payload.get("remarks", ""),
        temple_id=temple_id,
        user_id=current_user.sub
    )


# --- Price Change Approvals ---

@router.get("/price-approvals", response_model=List[PriceApprovalRequestResponse], tags=["inventory"])
async def list_price_approvals(
    status: Optional[str] = "PENDING_APPROVAL",
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    if current_user.role.upper() not in ("TEMPLE_MANAGER", "TEMPLE_ADMIN", "ADMIN", "SUPERADMIN"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Only managers or admins can access price approvals.")
    return await InventoryService.get_price_approvals(db=db, temple_id=temple_id, status=status)


@router.post("/price-approvals/{request_id}/approve", tags=["inventory"])
async def approve_price_approval(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    if current_user.role.upper() not in ("TEMPLE_MANAGER", "TEMPLE_ADMIN", "ADMIN", "SUPERADMIN"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Only managers or admins can approve price changes.")
    return await InventoryService.approve_price_approval(
        db=db,
        request_id=request_id,
        temple_id=temple_id,
        user_id=UUID(current_user.sub) if current_user.sub else None,
        username=current_user.username or "Admin",
        role=current_user.role
    )


@router.post("/price-approvals/{request_id}/reject", tags=["inventory"])
async def reject_price_approval(
    request_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    if current_user.role.upper() not in ("TEMPLE_MANAGER", "TEMPLE_ADMIN", "ADMIN", "SUPERADMIN"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Only managers or admins can reject price changes.")
    return await InventoryService.reject_price_approval(
        db=db,
        request_id=request_id,
        temple_id=temple_id,
        user_id=UUID(current_user.sub) if current_user.sub else None,
        username=current_user.username or "Admin",
        role=current_user.role,
        reason=payload.get("reason")
    )
