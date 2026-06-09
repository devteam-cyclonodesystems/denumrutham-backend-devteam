"""
Platform Advertisements Super Admin Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.api.deps import get_db, get_current_superadmin
from app.schemas.domain import TokenData
from app.modules.temple_management.schemas.advertisement import (
    PlatformAdvertisementCreate,
    PlatformAdvertisementUpdate,
    PlatformAdvertisementResponse,
)
from app.modules.temple_management.services.advertisement_service import AdvertisementService

router = APIRouter(prefix="/platform-advertisements")


@router.post("", response_model=PlatformAdvertisementResponse, status_code=201)
async def create_platform_ad(
    *,
    db: AsyncSession = Depends(get_db),
    payload: PlatformAdvertisementCreate,
    current_user: TokenData = Depends(get_current_superadmin),
):
    return await AdvertisementService.create_platform_ad(db=db, payload=payload)


@router.get("", response_model=List[PlatformAdvertisementResponse])
async def list_platform_ads(
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    return await AdvertisementService.list_platform_ads(db=db)


@router.get("/{ad_id}", response_model=PlatformAdvertisementResponse)
async def get_platform_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    return await AdvertisementService.get_platform_ad(db=db, ad_id=ad_id)


@router.put("/{ad_id}", response_model=PlatformAdvertisementResponse)
async def update_platform_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    payload: PlatformAdvertisementUpdate,
    current_user: TokenData = Depends(get_current_superadmin),
):
    return await AdvertisementService.update_platform_ad(db=db, ad_id=ad_id, payload=payload)


@router.delete("/{ad_id}")
async def delete_platform_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    return await AdvertisementService.delete_platform_ad(db=db, ad_id=ad_id)
