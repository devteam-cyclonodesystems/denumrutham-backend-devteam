from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.deps import get_db, get_current_user, get_current_temple_id
from app.schemas.domain import BookingCreate, BookingResponse, TokenData
from app.services.base import BaseService

router = APIRouter()


@router.post("", response_model=BookingResponse)
async def create_booking(
    *,
    db: AsyncSession = Depends(get_db),
    booking_in: BookingCreate,
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await BaseService.create_booking(
        db=db,
        booking_in=booking_in,
        temple_id=temple_id,
        user_id=current_user.sub,
    )


@router.get("", response_model=List[BookingResponse])
async def read_bookings(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    return await BaseService.get_bookings(
        db=db, temple_id=temple_id, skip=skip, limit=limit
    )
