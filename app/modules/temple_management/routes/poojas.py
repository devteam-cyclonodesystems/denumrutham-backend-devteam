from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.deps import get_db, get_current_active_admin, get_current_user, get_current_temple_id
from app.schemas.domain import PoojaCreate, PoojaResponse, TokenData
from app.services.base import BaseService

router = APIRouter()

@router.post("", response_model=PoojaResponse)
async def create_pooja(
    *,
    db: AsyncSession = Depends(get_db),
    pooja_in: PoojaCreate,
    current_user: TokenData = Depends(get_current_active_admin),
    temple_id: str = Depends(get_current_temple_id)
):
    return await BaseService.create_pooja(db=db, pooja_in=pooja_in, temple_id=temple_id)

@router.get("", response_model=List[PoojaResponse])
async def read_poojas(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id)
):
    return await BaseService.get_poojas(db=db, temple_id=temple_id, skip=skip, limit=limit)
