"""Hall & Hall Booking API endpoints with strict tenant enforcement."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.deps import get_db, get_current_user, get_current_temple_id
from app.schemas.domain import TokenData
from app.schemas.hall import HallCreate, HallUpdate, HallResponse, HallBookingCreate, HallBookingResponse, HallBookingUpdate, HallRefundRequest
from app.services.hall_service import HallService

router = APIRouter()


# --- Halls ---
@router.post("/halls", response_model=HallResponse, tags=["halls"])
async def create_hall(
    hall_in: HallCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.create_hall(db=db, hall_in=hall_in, temple_id=temple_id)


@router.get("/halls", response_model=List[HallResponse], tags=["halls"])
async def list_halls(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.get_halls(db=db, temple_id=temple_id)


@router.put("/halls/{hall_id}", response_model=HallResponse, tags=["halls"])
async def update_hall(
    hall_id: str,
    hall_in: HallUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.update_hall(db=db, hall_id=hall_id, update_in=hall_in, temple_id=temple_id)
    if not result:
        raise HTTPException(status_code=404, detail="Venue not found")
    return result


@router.delete("/halls/{hall_id}", tags=["halls"])
async def delete_hall(
    hall_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.delete_hall(db=db, hall_id=hall_id, temple_id=temple_id)
    if not result:
        raise HTTPException(status_code=404, detail="Venue not found")
    return {"message": "Venue removed successfully"}


# --- Hall Bookings ---
@router.post("/hall-bookings", response_model=HallBookingResponse, tags=["hall-bookings"])
async def create_hall_booking(
    booking_in: HallBookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.create_hall_booking(
        db=db, booking_in=booking_in, temple_id=temple_id,
        created_by=current_user.username or "Admin",
        user_id=current_user.sub,
    )


@router.get("/hall-bookings", response_model=List[HallBookingResponse], tags=["hall-bookings"])
async def list_hall_bookings(
    skip: int = 0,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.get_hall_bookings(db=db, temple_id=temple_id, skip=skip, limit=limit)


@router.put("/hall-bookings/{booking_id}", response_model=HallBookingResponse, tags=["hall-bookings"])
async def update_hall_booking(
    booking_id: str,
    update_in: HallBookingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.update_hall_booking(
        db=db, booking_id=booking_id, update_in=update_in, temple_id=temple_id, user_id=current_user.sub
    )
    if not result:
        raise HTTPException(status_code=404, detail="Booking not found")
    return result


@router.patch("/hall-bookings/{booking_id}/cancel", response_model=HallBookingResponse, tags=["hall-bookings"])
async def cancel_hall_booking(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.cancel_hall_booking(db=db, booking_id=booking_id, temple_id=temple_id, user_id=current_user.sub)
    if not result:
        raise HTTPException(status_code=404, detail="Booking not found")
    return result


@router.patch("/hall-bookings/{booking_id}/approve", response_model=HallBookingResponse, tags=["hall-bookings"])
async def approve_hall_booking(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.approve_hall_booking(db=db, booking_id=booking_id, temple_id=temple_id, user_id=current_user.sub)
    if not result:
        raise HTTPException(status_code=404, detail="Booking not found")
    return result


# --- Refunds ---
@router.post("/hall-bookings/refunds", tags=["hall-refunds"])
async def process_hall_refund(
    refund_in: HallRefundRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.process_refund(
        db=db,
        temple_id=temple_id,
        booking_id=refund_in.booking_id,
        amount=refund_in.amount,
        refund_method=refund_in.refund_method,
        refund_status=refund_in.refund_status,
        reason=refund_in.reason,
        user_id=current_user.sub,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Booking not found")
    return result


@router.get("/hall-bookings/{booking_id}/transactions", tags=["hall-bookings"])
async def get_booking_transactions(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.get_booking_transactions(db=db, booking_id=booking_id, temple_id=temple_id)


@router.get("/hall-bookings/{booking_id}/audit-trail", tags=["hall-bookings"])
async def get_booking_audit_trail(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.get_booking_audit_trail(db=db, booking_id=booking_id, temple_id=temple_id)

