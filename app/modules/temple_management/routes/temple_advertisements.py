"""
Temple Advertisements Manager Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database.deps import get_db, get_current_temple_id, get_current_temple_manager
from app.core.deps import enforce_active_subscription
from app.schemas.domain import TokenData
from app.modules.temple_management.schemas.advertisement import (
    TempleAdvertisementCreate,
    TempleAdvertisementUpdate,
    TempleAdvertisementResponse,
)
from app.modules.temple_management.services.advertisement_service import AdvertisementService

router = APIRouter(prefix="/temple-advertisements")


@router.post("", response_model=TempleAdvertisementResponse, status_code=201, dependencies=[Depends(enforce_active_subscription)])
async def create_temple_ad(
    *,
    db: AsyncSession = Depends(get_db),
    payload: TempleAdvertisementCreate,
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    ad = await AdvertisementService.create_temple_ad(db=db, temple_id=temple_id, payload=payload)
    
    # Audit logging
    from app.modules.audit.services.audit_service import AuditService
    await AuditService.log_action(
        db=db,
        temple_id=temple_id,
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="temple_management",
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
        details=f"Created temple advertisement campaign {ad.id}"
    )
    await db.commit()
    return ad


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


@router.get("/{ad_id}/audit-history")
async def get_temple_ad_audit_history(
    ad_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    """
    Get audit logs for a specific temple advertisement campaign.
    """
    temple_id = UUID(temple_id_str)
    # Verify ad belongs to temple
    await AdvertisementService.get_temple_ad(db=db, temple_id=temple_id, ad_id=ad_id)
    
    from app.modules.governance.models.governance_models import AuditLog
    from sqlalchemy import select, desc
    
    stmt = (
        select(AuditLog)
        .filter(AuditLog.entity_id == str(ad_id), AuditLog.temple_id == temple_id)
        .order_by(desc(AuditLog.created_at))
    )
    res = await db.execute(stmt)
    logs = res.scalars().all()
    
    return [
        {
            "id": str(log.id),
            "action": log.action,
            "action_type": log.action_type,
            "user_id": str(log.user_id),
            "role": log.role,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "details": log.details,
        }
        for log in logs
    ]


@router.put("/{ad_id}", response_model=TempleAdvertisementResponse, dependencies=[Depends(enforce_active_subscription)])
async def update_temple_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    payload: TempleAdvertisementUpdate,
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    
    # Fetch old values for audit
    ad_old = await AdvertisementService.get_temple_ad(db=db, temple_id=temple_id, ad_id=ad_id)
    old_is_active = ad_old.is_active
    old_val = {
        "placement": ad_old.placement,
        "media_type": ad_old.media_type,
        "media_urls": ad_old.media_urls,
        "target_url": ad_old.target_url,
        "start_date": ad_old.start_date.isoformat() if ad_old.start_date else None,
        "end_date": ad_old.end_date.isoformat() if ad_old.end_date else None,
        "priority": ad_old.priority,
        "cpm_rate": ad_old.cpm_rate,
        "cpc_rate": ad_old.cpc_rate,
        "impression_cap": ad_old.impression_cap,
        "click_cap": ad_old.click_cap,
        "billing_contact": ad_old.billing_contact,
        "approval_status": ad_old.approval_status
    }
    
    ad = await AdvertisementService.update_temple_ad(
        db=db, temple_id=temple_id, ad_id=ad_id, payload=payload
    )
    
    action = "ADVERTISEMENT_UPDATE"
    details = f"Updated temple advertisement campaign {ad_id}"
    
    if payload.is_active is not None:
        if payload.is_active and not old_is_active:
            action = "ADVERTISEMENT_RESUME"
            details = f"Resumed temple advertisement campaign {ad_id}"
        elif not payload.is_active and old_is_active:
            action = "ADVERTISEMENT_SUSPENSION"
            details = f"Suspended temple advertisement campaign {ad_id}"
            
    # Log the action
    from app.modules.audit.services.audit_service import AuditService
    await AuditService.log_action(
        db=db,
        temple_id=temple_id,
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="temple_management",
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


@router.delete("/{ad_id}", dependencies=[Depends(enforce_active_subscription)])
async def delete_temple_ad(
    ad_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    ad = await AdvertisementService.get_temple_ad(db=db, temple_id=temple_id, ad_id=ad_id)
    old_val = {
        "placement": ad.placement,
        "media_type": ad.media_type,
    }
    
    res = await AdvertisementService.delete_temple_ad(db=db, temple_id=temple_id, ad_id=ad_id)
    
    from app.modules.audit.services.audit_service import AuditService
    await AuditService.log_action(
        db=db,
        temple_id=temple_id,
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="temple_management",
        action="ADVERTISEMENT_DELETION",
        action_type="DELETE",
        entity_id=str(ad_id),
        old_value=old_val,
        details=f"Deleted temple advertisement campaign {ad_id}"
    )
    await db.commit()
    return res
