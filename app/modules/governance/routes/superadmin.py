"""
SuperAdmin API — Temple registry, context-switching, and CRUD endpoints.
Only accessible by users with role == 'SUPERADMIN'.
"""
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
    from uuid import UUID
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
    from app.models.operational_states import TempleOperationalState
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
    from uuid import UUID
    from app.services.registration_service import RegistrationService
    return await RegistrationService.approve_temple(db, UUID(temple_id), UUID(current_user.sub))


@router.post("/temples/{temple_id}/reject")
async def reject_temple(
    temple_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """Reject a pending temple registration (legacy flow)."""
    from uuid import UUID
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
    from uuid import UUID
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
    from uuid import UUID
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
    from uuid import UUID
    from app.services.sync_engine import SyncEngine

    user_id = UUID(current_user.sub) if current_user.sub else None

    return await SyncEngine.push_changes(
        db=db,
        updates=body.updates,
        user_id=user_id,
        user_role=current_user.role,
    )

