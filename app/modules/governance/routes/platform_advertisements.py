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
    ad = await AdvertisementService.create_platform_ad(db=db, payload=payload)
    
    # Audit Governance log
    from app.modules.audit.services.audit_service import AuditService
    await AuditService.log_action(
        db=db,
        temple_id=None,
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="governance",
        action="ADVERTISEMENT_CREATION",
        action_type="CREATE",
        entity_id=str(ad.id),
        new_value={
            "placement": ad.placement,
            "media_type": ad.media_type,
            "media_urls": ad.media_urls,
            "target_url": ad.target_url,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "priority": ad.priority,
            "cpm_rate": ad.cpm_rate,
            "cpc_rate": ad.cpc_rate,
            "impression_cap": ad.impression_cap,
            "click_cap": ad.click_cap,
            "billing_contact": ad.billing_contact,
            "approval_status": ad.approval_status
        },
        details=f"Created platform advertisement campaign {ad.id}"
    )
    await db.commit()
    return ad


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
    # 1. Fetch old advertisement to see values before update
    ad = await AdvertisementService.get_platform_ad(db, ad_id)
    old_status = ad.approval_status
    old_val = {
        "placement": ad.placement,
        "media_type": ad.media_type,
        "media_urls": ad.media_urls,
        "target_url": ad.target_url,
        "start_date": ad.start_date.isoformat() if ad.start_date else None,
        "end_date": ad.end_date.isoformat() if ad.end_date else None,
        "priority": ad.priority,
        "cpm_rate": ad.cpm_rate,
        "cpc_rate": ad.cpc_rate,
        "impression_cap": ad.impression_cap,
        "click_cap": ad.click_cap,
        "billing_contact": ad.billing_contact,
        "approval_status": ad.approval_status
    }
    
    # 2. Update advertisement
    ad = await AdvertisementService.update_platform_ad(db=db, ad_id=ad_id, payload=payload)
    
    # 3. Determine the specific action
    action = "ADVERTISEMENT_UPDATE"
    details = f"Updated platform advertisement campaign {ad_id}"
    
    if payload.approval_status is not None:
        if payload.approval_status == "PUBLISHED":
            if old_status == "SUSPENDED":
                action = "ADVERTISEMENT_RESUME"
                details = f"Resumed platform advertisement campaign {ad_id}"
            else:
                action = "ADVERTISEMENT_PUBLISH"
                details = f"Published platform advertisement campaign {ad_id}"
        elif payload.approval_status == "SUSPENDED":
            action = "ADVERTISEMENT_SUSPENSION"
            details = f"Suspended platform advertisement campaign {ad_id}"
            
    # 4. Log the action
    from app.modules.audit.services.audit_service import AuditService
    await AuditService.log_action(
        db=db,
        temple_id=None,
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="governance",
        action=action,
        action_type="UPDATE",
        entity_id=str(ad_id),
        old_value=old_val,
        new_value={
            "placement": ad.placement,
            "media_type": ad.media_type,
            "media_urls": ad.media_urls,
            "target_url": ad.target_url,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "priority": ad.priority,
            "cpm_rate": ad.cpm_rate,
            "cpc_rate": ad.cpc_rate,
            "impression_cap": ad.impression_cap,
            "click_cap": ad.click_cap,
            "billing_contact": ad.billing_contact,
            "approval_status": ad.approval_status
        },
        details=details
    )
    await db.commit()
    return ad


@router.delete("/{ad_id}")
async def delete_platform_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    return await AdvertisementService.delete_platform_ad(db=db, ad_id=ad_id)
