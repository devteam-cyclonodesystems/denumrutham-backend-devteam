"""
SuperAdmin API — Temple registry, context-switching, and CRUD endpoints.
Only accessible by users with role == 'SUPERADMIN'.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

from app.api.deps import get_db, get_current_superadmin, require_system_permission
from app.schemas.domain import TokenData, Token, TempleCreateFull, TempleUpdateFull, TempleActionRequest
from app.schemas.sync import SyncPushRequest
from app.services.superadmin_service import SuperAdminService

router = APIRouter()


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------

class SuperAdminTempleItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    domain: str
    location: str
    state: str
    address_line_1: str
    address_line_2: str
    district: str
    pincode: str
    contact_number: str
    alternate_contact: str
    email: str
    description: str
    image_url: str
    status: str
    operational_state: str
    version: Optional[int] = 1
    updated_at: Optional[str] = None


class SuperAdminTempleListResponse(BaseModel):
    temples: List[SuperAdminTempleItem]
    total: int


class StateTransitionRequest(BaseModel):
    new_state: str # TempleOperationalState
    reason: str

class SelectTempleRequest(BaseModel):
    temple_id: str


# ---------------------------------------------------------------------------
# Endpoints — STATS
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_system_stats(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Global system stats for SuperAdmin dashboard."""
    return await SuperAdminService.get_dashboard_stats(db)


# ---------------------------------------------------------------------------
# Endpoints — LIST & SELECT
# ---------------------------------------------------------------------------

@router.get("/temples/", response_model=SuperAdminTempleListResponse)
async def list_all_temples(
    include_inactive: bool = Query(False, description="Include inactive temples"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Return all temples in the system.
    SuperAdmin-only: no temple_id filtering applied.
    """
    items, total = await SuperAdminService.get_all_temples(db, include_inactive)
    return SuperAdminTempleListResponse(temples=items, total=total)


@router.post("/select-temple", response_model=Token)
async def select_temple(
    body: SelectTempleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Issue a new JWT with the chosen temple's temple_id embedded.
    The frontend replaces its stored token with this new one so that
    all subsequent API calls carry the correct temple context.
    """
    token = await SuperAdminService.select_temple(
        db, body.temple_id, current_user.sub, current_user.username
    )
    return {"access_token": token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# Endpoints — CRUD
# ---------------------------------------------------------------------------

@router.post("/temples", response_model=SuperAdminTempleItem, status_code=201)
async def create_temple(
    body: TempleCreateFull,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Create a new temple with full details."""
    item = await SuperAdminService.create_temple(db, body, current_user.sub)
    return SuperAdminTempleItem(**item)


@router.put("/temples/{temple_id}")
async def update_temple(
    temple_id: str,
    body: TempleUpdateFull,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Update temple details - Requires Approval Workflow."""
    from app.services.approval_service import ApprovalService
    
    req = await ApprovalService.request_approval(
        db=db,
        temple_id=UUID(temple_id),
        module="temples",
        entity_id=temple_id,
        requested_by=UUID(current_user.sub),
        request_payload=body.model_dump(exclude_unset=True)
    )
    return {"message": "Update request submitted for approval", "approval_request_id": str(req.id)}


@router.delete("/temples/{temple_id}")
async def delete_temple(
    temple_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Soft-delete a temple by setting status to 'inactive'."""
    return await SuperAdminService.delete_temple(
        db, temple_id, deleted_by=current_user.sub, user_role=current_user.role
    )


@router.post("/temples/{temple_id}/deactivate")
async def deactivate_temple(
    temple_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Explicit endpoint for temple deactivation."""
    return await SuperAdminService.delete_temple(
        db, temple_id, deleted_by=current_user.sub, user_role=current_user.role
    )


@router.post("/temples/{temple_id}/suspend")
async def suspend_temple(
    temple_id: str,
    body: TempleActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Emergency administrative lock."""
    return await SuperAdminService.suspend_temple(
        db, temple_id, suspended_by=current_user.sub, reason=body.reason
    )


@router.post("/temples/{temple_id}/reactivate")
async def reactivate_temple(
    temple_id: str,
    body: TempleActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Restore a deactivated or suspended temple."""
    return await SuperAdminService.reactivate_temple(
        db, temple_id, activated_by=current_user.sub, reason=body.reason
    )


@router.post("/temples/{temple_id}/transition-state")
async def transition_temple_state(
    temple_id: str,
    body: StateTransitionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Formal transition between operational states."""
    from app.modules.governance.models.operational_states import TempleOperationalState
    from app.services.operational_state_service import OperationalStateService
    
    try:
        new_state_enum = TempleOperationalState(body.new_state)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid operational state: {body.new_state}")
        
    return await OperationalStateService.transition_to(
        db=db,
        temple_id=temple_id,
        new_state=new_state_enum,
        changed_by=current_user.sub,
        reason=body.reason
    )


@router.post("/temples/{temple_id}/force-logout")
async def force_logout(
    temple_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """Advanced Security: Invalidate all active sessions for a temple."""
    return await SuperAdminService.force_logout_all_users(
        db, temple_id, triggered_by=current_user.sub
    )


# ---------------------------------------------------------------------------
# Endpoints — CONTEXT RESET
# ---------------------------------------------------------------------------

@router.post("/reset-context", response_model=Token)
async def reset_context(
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Re-issue a clean SUPERADMIN JWT without temple_id.
    Used when switching temples to clear the stale tenant context.
    """
    token = await SuperAdminService.reset_context(current_user.sub, current_user.username)
    return {"access_token": token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# Endpoints — TEMPLE REGISTRATION APPROVAL (Legacy — preserved for backward compat)
# New flow: Use /onboarding/admin/* endpoints instead.
# These now use permission-based guards instead of hardcoded SUPERADMIN check.
# ---------------------------------------------------------------------------

@router.get("/pending-temples")
async def list_pending_temples(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """List all temples with PENDING status awaiting approval.
    
    DEPRECATED: Use GET /onboarding/admin/temple-requests instead.
    This endpoint lists temples from the old direct-creation flow.
    """
    from app.services.registration_service import RegistrationService
    return await RegistrationService.list_pending_temples(db)


@router.post("/temples/{temple_id}/approve")
async def approve_temple(
    temple_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """Approve a pending temple registration (legacy flow)."""
    from app.services.registration_service import RegistrationService
    return await RegistrationService.approve_temple(db, UUID(temple_id), UUID(current_user.sub))


@router.post("/temples/{temple_id}/reject")
async def reject_temple(
    temple_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """Reject a pending temple registration (legacy flow)."""
    from app.services.registration_service import RegistrationService
    return await RegistrationService.reject_temple(db, UUID(temple_id), UUID(current_user.sub))


# ---------------------------------------------------------------------------
# Endpoints — STAFF APPROVAL (delegated, also accessible by TEMPLE_MANAGER)
# ---------------------------------------------------------------------------

@router.get("/pending-staff/{temple_id}")
async def list_pending_staff(
    temple_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("MANAGE_USERS")),
):
    """List pending staff registrations for a specific temple."""
    from app.services.registration_service import RegistrationService
    return await RegistrationService.list_pending_staff(db, UUID(temple_id))


# ---------------------------------------------------------------------------
# Endpoints — AUDIT TRAIL
# ---------------------------------------------------------------------------

@router.get("/temples/{temple_id}/audit-history")
async def get_temple_audit_history(
    temple_id: str,
    limit: int = Query(50, ge=1, le=200, description="Max records to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    date_from: str = Query(None, description="Filter: records after this ISO datetime"),
    date_to: str = Query(None, description="Filter: records before this ISO datetime"),
    sort: str = Query("desc", description="Sort order: 'desc' (newest first) or 'asc'"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Get the full status change audit trail for a temple.

    Supports:
      - Pagination via limit/offset
      - Date range filtering via date_from/date_to (ISO 8601)
      - Sort order via sort (desc default)
    """
    from datetime import datetime

    parsed_from = None
    parsed_to = None
    if date_from:
        try:
            parsed_from = datetime.fromisoformat(date_from)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid date_from format. Use ISO 8601.")
    if date_to:
        try:
            parsed_to = datetime.fromisoformat(date_to)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid date_to format. Use ISO 8601.")

    from app.services.temple_audit_service import TempleAuditService
    return await TempleAuditService.get_temple_audit_history(
        db, UUID(temple_id),
        limit=limit, offset=offset,
        date_from=parsed_from, date_to=parsed_to,
        sort_order=sort,
    )


@router.get("/temples/{temple_id}/governance-timeline")
async def get_temple_governance_timeline(
    temple_id: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Page size"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Get the Unified Governance Timeline for a temple, paginated.
    """
    try:
        t_id = UUID(temple_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid temple_id format")

    events, total = await SuperAdminService.get_governance_timeline(
        db=db,
        temple_id=t_id,
        page=page,
        page_size=page_size,
        event_type=event_type
    )
    return {"events": events, "total": total}



# ---------------------------------------------------------------------------
# Endpoints — HYBRID SYNC (Phase 4)
# ---------------------------------------------------------------------------

@router.get("/temples/sync")
async def sync_pull(
    since: str = Query(..., description="ISO 8601 timestamp — return temples updated after this time"),
    limit: int = Query(100, ge=1, le=500, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Phase 4 Hybrid Sync — PULL: Get all temple changes since a timestamp.

    Client stores the returned `server_time` and uses it as `since`
    in the next pull request for incremental sync.
    """
    from datetime import datetime
    from app.services.sync_engine import SyncEngine

    try:
        since_dt = datetime.fromisoformat(since)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid 'since' format. Use ISO 8601.")

    return await SyncEngine.pull_changes(db, since_dt, limit)


@router.post("/temples/sync")
async def sync_push(
    body: SyncPushRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Phase 4 Hybrid Sync — PUSH: Batch-submit offline temple changes.

    For each update:
      1. Validates RBAC (user must be authorized for the temple)
      2. Validates version match (conflict detection)
      3. Blocks status changes and deletes (online-only operations)
      4. Applies safe field updates atomically (SELECT FOR UPDATE)
      5. Increments version and records audit trail

    Conflict resolution: SERVER WINS — no auto-merge.
    On conflict, returns latest server state for client reconciliation.
    """
    from app.services.sync_engine import SyncEngine

    user_id = UUID(current_user.sub) if current_user.sub else None

    return await SyncEngine.push_changes(
        db=db,
        updates=body.updates,
        user_id=user_id,
        user_role=current_user.role,
    )


# =============================================================================
# SPRINT 4 SUPER ADMIN ADDITIONS — GLOBAL SETTINGS & ADS APPROVALS
# =============================================================================

class GlobalSettingUpdate(BaseModel):
    value: dict | list | str | int | float | bool


class AdApproveRequest(BaseModel):
    priority: Optional[str] = "MEDIUM"
    scheduling_rules: Optional[dict] = None
    cpm_rate: Optional[float] = 0.0
    cpc_rate: Optional[float] = 0.0
    impression_cap: Optional[int] = None
    click_cap: Optional[int] = None
    billing_contact: Optional[str] = None
    revenue_attribution: Optional[dict] = None


class AdRejectRequest(BaseModel):
    remarks: str


@router.get("/global-settings/{key}")
async def get_global_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Get a global setting. FCM credentials are automatically masked.
    """
    from app.modules.governance.models.governance_models import PlatformGlobalSetting
    from sqlalchemy import select
    
    result = await db.execute(select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == key))
    setting = result.scalar_one_or_none()
    if not setting:
        return {"key": key, "value": {}}
        
    value = setting.value
    if key == "fcm_credentials" and isinstance(value, dict):
        masked_value = dict(value)
        if "encrypted_credentials" in masked_value:
            masked_value["encrypted_credentials"] = "********"
        for k in ["private_key", "private_key_id"]:
            if k in masked_value:
                masked_value[k] = "********"
        return {"key": key, "value": masked_value}
        
    return {"key": key, "value": value}


@router.put("/global-settings/{key}")
async def update_global_setting(
    key: str,
    body: GlobalSettingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Update a global setting. FCM credentials are automatically encrypted.
    """
    from app.modules.governance.models.governance_models import PlatformGlobalSetting
    from app.core.security.encryption import encrypt_data
    from app.modules.audit.services.audit_service import AuditService
    import json
    from sqlalchemy import select
    
    result = await db.execute(select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == key))
    setting = result.scalar_one_or_none()
    
    old_val = setting.value if setting else None
    new_val = body.value
    
    if key == "fcm_credentials":
        if isinstance(new_val, dict):
            private_key = new_val.get("private_key")
            if private_key and private_key != "********":
                encrypted_str = encrypt_data(json.dumps(new_val))
                new_val = {"encrypted_credentials": encrypted_str}
            else:
                if old_val:
                    new_val = old_val
                else:
                    new_val = {"encrypted_credentials": ""}
        elif isinstance(new_val, str) and new_val != "********":
            new_val = {"encrypted_credentials": encrypt_data(new_val)}
        else:
            new_val = old_val if old_val else {"encrypted_credentials": ""}
            
    if not setting:
        setting = PlatformGlobalSetting(key=key, value=new_val)
        db.add(setting)
    else:
        setting.value = new_val
        
    await db.flush()
    
    # Audit log governance
    action = "FCM_CREDENTIAL_CHANGES" if key == "fcm_credentials" else "SETTINGS_CHANGES"
    old_audit_val = old_val
    new_audit_val = new_val
    if key == "fcm_credentials":
        if isinstance(old_audit_val, dict) and "encrypted_credentials" in old_audit_val:
            old_audit_val = {"encrypted_credentials": "********"}
        if isinstance(new_audit_val, dict) and "encrypted_credentials" in new_audit_val:
            new_audit_val = {"encrypted_credentials": "********"}
            
    await AuditService.log_action(
        db=db,
        temple_id=None,
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="governance",
        action=action,
        action_type="UPDATE",
        entity_id=key,
        old_value=old_audit_val,
        new_value=new_audit_val,
        details=f"Updated global setting for {key}"
    )
    
    await db.commit()
    return {"key": key, "value": new_val}


@router.post("/global-settings/{key}/publish")
async def publish_global_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Publish draft settings to live and invalidates layouts cache.
    """
    from app.modules.governance.models.governance_models import PlatformGlobalSetting
    from app.modules.audit.services.audit_service import AuditService
    from app.core.cache import GlobalConfigurationCache
    from sqlalchemy import select
    from datetime import datetime, timezone
    
    if key != "global_website_builder":
        raise HTTPException(status_code=400, detail="Only global_website_builder can be published")
        
    # Fetch draft
    draft_res = await db.execute(
        select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "global_website_builder_draft")
    )
    draft = draft_res.scalar_one_or_none()
    if not draft or not draft.value:
        raise HTTPException(status_code=404, detail="No draft configuration found to publish")
        
    # Fetch live
    live_res = await db.execute(
        select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "global_website_builder_live")
    )
    live = live_res.scalar_one_or_none()
    
    new_version_num = 1
    if live and isinstance(live.value, dict):
        new_version_num = live.value.get("version", 0) + 1
        
    live_value = dict(draft.value)
    live_value["version"] = new_version_num
    live_value["published_at"] = datetime.now(timezone.utc).isoformat()
    live_value["published_by"] = str(current_user.sub)
    
    if not live:
        live = PlatformGlobalSetting(key="global_website_builder_live", value=live_value)
        db.add(live)
    else:
        live.value = live_value
        
    # Save to history list
    history_res = await db.execute(
        select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "global_website_builder_history")
    )
    history = history_res.scalar_one_or_none()
    
    history_list = []
    if history and isinstance(history.value, list):
        history_list = list(history.value)
        
    snapshot = {
        "version": new_version_num,
        "published_at": live_value["published_at"],
        "published_by": live_value["published_by"],
        "config": draft.value
    }
    history_list.append(snapshot)
    
    if not history:
        history = PlatformGlobalSetting(key="global_website_builder_history", value=history_list)
        db.add(history)
    else:
        history.value = history_list
        
    await db.flush()
    
    # Invalidate layouts configuration cache on publish
    GlobalConfigurationCache.invalidate_all()
    
    # Audit Governance log
    await AuditService.log_action(
        db=db,
        temple_id=None,
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="governance",
        action="GLOBAL_PUBLISH",
        action_type="CREATE",
        entity_id="global_website_builder",
        new_value={"version": new_version_num},
        details=f"Published global website layout version {new_version_num}"
    )
    
    await db.commit()
    return {"status": "success", "version": new_version_num, "live": live_value}


@router.post("/advertisements/{ad_id}/approve")
async def approve_advertisement(
    ad_id: UUID,
    body: AdApproveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Approve platform/temple advertisement.
    """
    from app.modules.temple_management.models.temple_models import PlatformAdvertisement, TempleAdvertisement
    from app.modules.audit.services.audit_service import AuditService
    from sqlalchemy import select
    
    ad = None
    ad_type = "PLATFORM"
    result = await db.execute(select(PlatformAdvertisement).filter(PlatformAdvertisement.id == ad_id))
    ad = result.scalar_one_or_none()
    
    if not ad:
        result = await db.execute(select(TempleAdvertisement).filter(TempleAdvertisement.id == ad_id))
        ad = result.scalar_one_or_none()
        ad_type = "TEMPLE"
        
    if not ad:
        raise HTTPException(status_code=404, detail="Advertisement not found")
        
    ad.approval_status = "APPROVED"
    ad.priority = body.priority or "MEDIUM"
    ad.scheduling_rules = body.scheduling_rules or {}
    ad.cpm_rate = body.cpm_rate or 0.0
    ad.cpc_rate = body.cpc_rate or 0.0
    ad.impression_cap = body.impression_cap
    ad.click_cap = body.click_cap
    ad.billing_contact = body.billing_contact
    if body.revenue_attribution:
        ad.revenue_attribution = body.revenue_attribution
        
    await db.flush()
    
    # Audit Governance log
    await AuditService.log_action(
        db=db,
        temple_id=getattr(ad, "temple_id", None),
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="governance",
        action="ADVERTISEMENT_APPROVAL",
        action_type="UPDATE",
        entity_id=str(ad_id),
        new_value={"approval_status": "APPROVED", "type": ad_type},
        details=f"Approved {ad_type.lower()} advertisement {ad_id}"
    )
    
    await db.commit()
    return {"status": "success", "message": "Advertisement approved", "ad_id": str(ad_id)}


@router.post("/advertisements/{ad_id}/reject")
async def reject_advertisement(
    ad_id: UUID,
    body: AdRejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Reject platform/temple advertisement.
    """
    from app.modules.temple_management.models.temple_models import PlatformAdvertisement, TempleAdvertisement
    from app.modules.audit.services.audit_service import AuditService
    from sqlalchemy import select
    
    ad = None
    ad_type = "PLATFORM"
    result = await db.execute(select(PlatformAdvertisement).filter(PlatformAdvertisement.id == ad_id))
    ad = result.scalar_one_or_none()
    
    if not ad:
        result = await db.execute(select(TempleAdvertisement).filter(TempleAdvertisement.id == ad_id))
        ad = result.scalar_one_or_none()
        ad_type = "TEMPLE"
        
    if not ad:
        raise HTTPException(status_code=404, detail="Advertisement not found")
        
    ad.approval_status = "REJECTED"
    ad.approval_remarks = body.remarks
    
    await db.flush()
    
    # Audit Governance log
    await AuditService.log_action(
        db=db,
        temple_id=getattr(ad, "temple_id", None),
        user_id=UUID(current_user.sub),
        role=current_user.role,
        module_name="governance",
        action="ADVERTISEMENT_REJECTION",
        action_type="UPDATE",
        entity_id=str(ad_id),
        new_value={"approval_status": "REJECTED", "remarks": body.remarks, "type": ad_type},
        details=f"Rejected {ad_type.lower()} advertisement {ad_id}"
    )
    
    await db.commit()
    return {"status": "success", "message": "Advertisement rejected", "ad_id": str(ad_id)}


@router.get("/advertisements/{ad_id}/audit-history")
async def get_ad_audit_history(
    ad_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """
    Get audit logs for a specific advertisement campaign.
    """
    from app.modules.governance.models.governance_models import AuditLog
    from sqlalchemy import select, desc
    
    stmt = (
        select(AuditLog)
        .filter(AuditLog.entity_id == str(ad_id))
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


@router.get("/analytics/search")
async def get_search_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """SuperAdmin search analytics dashboard."""
    from datetime import datetime, timezone, timedelta
    from app.modules.temple_management.models.temple_models import PortalAnalyticsEvent
    from sqlalchemy import select
    
    now = datetime.now(timezone.utc)
    fourteen_days_ago = now - timedelta(days=14)
    
    # Fetch all search and click events from last 14 days
    events_stmt = select(PortalAnalyticsEvent).filter(
        PortalAnalyticsEvent.event_name.in_(["HOMEPAGE_SEARCH", "TEMPLE_CARD_CLICK", "TEMPLE_VIEW"]),
        PortalAnalyticsEvent.created_at >= fourteen_days_ago
    )
    events_res = await db.execute(events_stmt)
    events = events_res.scalars().all()
    
    searches = [e for e in events if e.event_name == "HOMEPAGE_SEARCH"]
    clicks = [e for e in events if e.event_name in ("TEMPLE_CARD_CLICK", "TEMPLE_VIEW")]
    
    total_searches = len(searches)
    
    # Calculate Success & Abandonment Rates
    # Group clicks by visitor_hash for fast lookup
    clicks_by_visitor = {}
    for c in clicks:
        clicks_by_visitor.setdefault(c.visitor_hash, []).append(c)
        if c.session_id:
            clicks_by_visitor.setdefault(c.session_id, []).append(c)
            
    successful_searches_count = 0
    for s in searches:
        # Check matching clicks
        candidate_clicks = []
        if s.session_id and s.session_id in clicks_by_visitor:
            candidate_clicks.extend(clicks_by_visitor[s.session_id])
        if s.visitor_hash in clicks_by_visitor:
            candidate_clicks.extend(clicks_by_visitor[s.visitor_hash])
            
        # Check if any click is within 30 minutes after the search
        success = False
        for c in candidate_clicks:
            if c.created_at >= s.created_at and c.created_at <= s.created_at + timedelta(minutes=30):
                success = True
                break
        if success:
            successful_searches_count += 1
            
    success_rate = (successful_searches_count / total_searches) if total_searches > 0 else 0.0
    abandonment_rate = (1.0 - success_rate) if total_searches > 0 else 0.0
    
    # Top searches
    query_counts = {}
    zero_result_counts = {}
    state_counts = {}
    
    # Current period (last 7 days) and prior period (days 8-14)
    seven_days_ago = now - timedelta(days=7)
    current_queries = {}
    prior_queries = {}
    
    for s in searches:
        meta = s.event_metadata or {}
        q = meta.get("query", "").strip().lower()
        if not q:
            continue
            
        query_counts[q] = query_counts.get(q, 0) + 1
        
        # Zero result count
        res_count = meta.get("results_count")
        if res_count == 0 or meta.get("count") == 0:
            zero_result_counts[q] = zero_result_counts.get(q, 0) + 1
            
        # State grouping
        state = meta.get("state")
        if state:
            state = state.strip().title()
            state_counts[state] = state_counts.get(state, 0) + 1
            
        # Period counts for rising searches
        if s.created_at >= seven_days_ago:
            current_queries[q] = current_queries.get(q, 0) + 1
        else:
            prior_queries[q] = prior_queries.get(q, 0) + 1
            
    # Format Top Searches
    top_searches_list = [{"query": q, "volume": vol} for q, vol in sorted(query_counts.items(), key=lambda x: x[1], reverse=True)[:10]]
    
    # Format Zero Result Searches
    zero_result_list = [{"query": q, "volume": vol} for q, vol in sorted(zero_result_counts.items(), key=lambda x: x[1], reverse=True)[:10]]
    
    # Format State Groupings
    state_searches_list = [{"state": st, "volume": vol} for st, vol in sorted(state_counts.items(), key=lambda x: x[1], reverse=True)]
    
    # Format Rising Searches (current volume >= 20)
    rising_searches_list = []
    for q, current_vol in current_queries.items():
        if current_vol >= 20:
            prior_vol = prior_queries.get(q, 0)
            if prior_vol == 0:
                growth_pct = 100.0  # grow from 0
            else:
                growth_pct = ((current_vol - prior_vol) / prior_vol) * 100.0
            rising_searches_list.append({
                "query": q,
                "current_volume": current_vol,
                "prior_volume": prior_vol,
                "growth_pct": round(growth_pct, 1)
            })
            
    rising_searches_list.sort(key=lambda x: x["growth_pct"], reverse=True)
    
    return {
        "total_searches": total_searches,
        "search_success_rate": round(success_rate * 100, 2),
        "search_abandonment_rate": round(abandonment_rate * 100, 2),
        "top_searches": top_searches_list,
        "rising_searches": rising_searches_list[:10],
        "zero_result_searches": zero_result_list,
        "searches_by_state": state_searches_list
    }


@router.get("/analytics/onboarding")
async def get_onboarding_funnel(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin),
):
    """SuperAdmin claim funnel onboarding analytics dashboard."""
    from app.modules.temple_management.models.temple_models import PortalAnalyticsEvent
    from sqlalchemy import select, func
    
    event_names = ["CLAIM_CTA_IMPRESSION", "CLAIM_TEMPLE_CLICK", "CLAIM_SUBMISSION", "CLAIM_APPROVED"]
    stmt = (
        select(PortalAnalyticsEvent.event_name, func.count(PortalAnalyticsEvent.id))
        .filter(PortalAnalyticsEvent.event_name.in_(event_names))
        .group_by(PortalAnalyticsEvent.event_name)
    )
    res = await db.execute(stmt)
    counts = {row[0]: row[1] for row in res.all()}
    
    impressions = counts.get("CLAIM_CTA_IMPRESSION", 0)
    clicks = counts.get("CLAIM_TEMPLE_CLICK", 0)
    submissions = counts.get("CLAIM_SUBMISSION", 0)
    approvals = counts.get("CLAIM_APPROVED", 0)
    
    ctr = (clicks / impressions * 100.0) if impressions > 0 else 0.0
    submission_rate = (submissions / clicks * 100.0) if clicks > 0 else 0.0
    approval_rate = (approvals / submissions * 100.0) if submissions > 0 else 0.0
    
    return {
        "funnel": {
            "impressions": impressions,
            "clicks": clicks,
            "submissions": submissions,
            "approvals": approvals
        },
        "rates": {
            "ctr": round(ctr, 2),
            "submission_rate": round(submission_rate, 2),
            "approval_rate": round(approval_rate, 2)
        }
    }




