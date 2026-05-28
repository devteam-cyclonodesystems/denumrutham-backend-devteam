from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.deps import get_db, get_current_user, get_current_temple_id
from app.schemas.domain import DevoteeCreate, DevoteeResponse, TokenData
from app.services.base import BaseService

router = APIRouter()

@router.post("", response_model=DevoteeResponse)
async def create_devotee(
    *,
    db: AsyncSession = Depends(get_db),
    devotee_in: DevoteeCreate,
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id)
):
    return await BaseService.create_devotee(db=db, devotee_in=devotee_in, temple_id=temple_id)

@router.get("", response_model=List[DevoteeResponse])
async def read_devotees(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id)
):
    return await BaseService.get_devotees(db=db, temple_id=temple_id, skip=skip, limit=limit)
