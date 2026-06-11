"""Offerings Module — FastAPI router."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.api.deps import get_db, get_current_user, get_current_temple_id, enforce_active_subscription, enforce_management_mode
from app.schemas.domain import TokenData
from app.services.offering_service import OfferingService
from app.schemas.offering import (
    OfferingCategoryCreate, OfferingCategoryUpdate, OfferingCategoryResponse,
    OfferingCreate, OfferingUpdate, OfferingResponse,
    OfferingPaymentCreate, OfferingPaymentResponse,
    OfferingAuditLogResponse,
    OfferingDetailResponse,
    OfferingReconciliationResponse,
    OfferingSummaryResponse,
    PaginatedOfferingsResponse,
    OfferingInventoryLinkResponse,
)

router = APIRouter(dependencies=[Depends(enforce_management_mode("offerings"))])


# ================================================================
#  CATEGORIES
# ================================================================
@router.get("/offering-categories", response_model=List[OfferingCategoryResponse], tags=["offering-categories"])
async def list_categories(
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.get_categories(db=db, temple_id=temple_id, include_inactive=include_inactive)


@router.post("/offering-categories", response_model=OfferingCategoryResponse, status_code=201, dependencies=[Depends(enforce_active_subscription)], tags=["offering-categories"])
async def create_category(
    data: OfferingCategoryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.create_category(db=db, data=data, temple_id=temple_id)


@router.put("/offering-categories/{category_id}", response_model=OfferingCategoryResponse, dependencies=[Depends(enforce_active_subscription)], tags=["offering-categories"])
async def update_category(
    category_id: str,
    data: OfferingCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await OfferingService.update_category(db=db, category_id=category_id, data=data, temple_id=temple_id)
    if not result:
        raise HTTPException(status_code=404, detail="Category not found")
    return result


# ================================================================
#  OFFERINGS — CORE CRUD
# ================================================================
@router.post("/offerings", response_model=OfferingResponse, status_code=201, dependencies=[Depends(enforce_active_subscription)], tags=["offerings"])
async def create_offering(
    data: OfferingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.create_offering(
        db=db,
        data=data,
        temple_id=temple_id,
        created_by=current_user.username or "Admin",
    )


@router.get("/offerings", response_model=PaginatedOfferingsResponse, tags=["offerings"])
async def list_offerings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    category_id: Optional[str] = None,
    payment_status: Optional[str] = None,
    booking_mode: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.get_offerings(
        db=db,
        temple_id=temple_id,
        page=page,
        page_size=page_size,
        search=search,
        category_id=category_id,
        payment_status=payment_status,
        booking_mode=booking_mode,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/offerings/summary", response_model=OfferingSummaryResponse, tags=["offerings"])
async def get_summary(
    date_from: Optional[str] = Query(None, description="Start date filter (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="End date filter (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.get_summary(
        db=db,
        temple_id=temple_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/offerings/{offering_id}", response_model=OfferingDetailResponse, tags=["offerings"])
async def get_offering_detail(
    offering_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await OfferingService.get_offering_detail(db=db, offering_id=offering_id, temple_id=temple_id)
    if not result:
        raise HTTPException(status_code=404, detail="Offering not found")
    return result


@router.put("/offerings/{offering_id}", response_model=OfferingResponse, dependencies=[Depends(enforce_active_subscription)], tags=["offerings"])
async def update_offering(
    offering_id: str,
    data: OfferingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await OfferingService.update_offering(
        db=db,
        offering_id=offering_id,
        data=data,
        temple_id=temple_id,
        changed_by=current_user.username or "Admin",
    )
    if not result:
        raise HTTPException(status_code=404, detail="Offering not found")
    return result


@router.delete("/offerings/{offering_id}", dependencies=[Depends(enforce_active_subscription)], tags=["offerings"])
async def delete_offering(
    offering_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await OfferingService.delete_offering(
        db=db,
        offering_id=offering_id,
        temple_id=temple_id,
        changed_by=current_user.username or "Admin",
    )
    if not result:
        raise HTTPException(status_code=404, detail="Offering not found")
    return {"message": "Offering deleted successfully"}


# ================================================================
#  PAYMENTS
# ================================================================
@router.post("/offerings/{offering_id}/payments", response_model=OfferingPaymentResponse, status_code=201, dependencies=[Depends(enforce_active_subscription)], tags=["offering-payments"])
async def add_payment(
    offering_id: str,
    data: OfferingPaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await OfferingService.add_payment(
        db=db,
        offering_id=offering_id,
        data=data,
        temple_id=temple_id,
        received_by=current_user.username or "Admin",
    )
    if not result:
        raise HTTPException(status_code=404, detail="Offering not found")
    return result


@router.get("/offerings/{offering_id}/payments", response_model=List[OfferingPaymentResponse], tags=["offering-payments"])
async def get_payments(
    offering_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await OfferingService.get_payments(db=db, offering_id=offering_id, temple_id=temple_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Offering not found")
    return result


# ================================================================
#  AUDIT TRAIL
# ================================================================
@router.get("/offerings/{offering_id}/audit-trail", response_model=List[OfferingAuditLogResponse], tags=["offering-audit"])
async def get_audit_trail(
    offering_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.get_audit_trail(db=db, offering_id=offering_id, temple_id=temple_id)


# ================================================================
#  RECONCILIATION
# ================================================================
@router.get("/offerings-reconciliation/today", tags=["offering-reconciliation"])
async def get_today_reconciliation(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.get_today_reconciliation(db=db, temple_id=temple_id)


@router.post("/offerings-reconciliation/close", response_model=OfferingReconciliationResponse, status_code=201, dependencies=[Depends(enforce_active_subscription)], tags=["offering-reconciliation"])
async def close_reconciliation(
    actual_collected: float = Query(..., description="Actual collected amount"),
    notes: Optional[str] = Query(None, description="Closing notes"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.close_reconciliation(
        db=db,
        temple_id=temple_id,
        actual_collected=actual_collected,
        notes=notes,
        closed_by=current_user.username or "Admin",
    )


@router.get("/offerings-reconciliation/history", response_model=List[OfferingReconciliationResponse], tags=["offering-reconciliation"])
async def get_reconciliation_history(
    limit: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.get_reconciliation_history(db=db, temple_id=temple_id, limit=limit)


# ================================================================
#  DONOR SEARCH
# ================================================================
@router.get("/offerings-donors/search", tags=["offering-donors"])
async def search_donors(
    q: str = Query(..., min_length=2, description="Search by name or phone"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await OfferingService.search_donors(db=db, temple_id=temple_id, query=q)
