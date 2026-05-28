from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.deps import get_db, get_current_user, get_current_temple_id
from app.schemas.domain import DonationCreate, DonationResponse, TokenData
from app.services.base import BaseService

router = APIRouter()


@router.post("", response_model=DonationResponse)
async def create_donation(
    *,
    db: AsyncSession = Depends(get_db),
    donation_in: DonationCreate,
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await BaseService.create_donation(
        db=db,
        donation_in=donation_in,
        temple_id=temple_id,
        user_id=current_user.sub,
    )


@router.get("", response_model=List[DonationResponse])
async def read_donations(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    return await BaseService.get_donations(
        db=db, temple_id=temple_id, skip=skip, limit=limit
    )
