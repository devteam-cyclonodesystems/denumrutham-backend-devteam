"""
Temple Advertisements Manager Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database.deps import get_db, get_current_temple_id, get_current_temple_manager
from app.schemas.domain import TokenData
from app.modules.temple_management.schemas.advertisement import (
    TempleAdvertisementCreate,
    TempleAdvertisementUpdate,
    TempleAdvertisementResponse,
)
from app.modules.temple_management.services.advertisement_service import AdvertisementService

router = APIRouter(prefix="/temple-advertisements")


@router.post("", response_model=TempleAdvertisementResponse, status_code=201)
async def create_temple_ad(
    *,
    db: AsyncSession = Depends(get_db),
    payload: TempleAdvertisementCreate,
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await AdvertisementService.create_temple_ad(db=db, temple_id=temple_id, payload=payload)


@router.get("", response_model=List[TempleAdvertisementResponse])
async def list_temple_ads(
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await AdvertisementService.list_temple_ads(db=db, temple_id=temple_id)


@router.get("/{ad_id}", response_model=TempleAdvertisementResponse)
async def get_temple_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await AdvertisementService.get_temple_ad(db=db, temple_id=temple_id, ad_id=ad_id)


@router.put("/{ad_id}", response_model=TempleAdvertisementResponse)
async def update_temple_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    payload: TempleAdvertisementUpdate,
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await AdvertisementService.update_temple_ad(
        db=db, temple_id=temple_id, ad_id=ad_id, payload=payload
    )


@router.delete("/{ad_id}")
async def delete_temple_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await AdvertisementService.delete_temple_ad(db=db, temple_id=temple_id, ad_id=ad_id)
