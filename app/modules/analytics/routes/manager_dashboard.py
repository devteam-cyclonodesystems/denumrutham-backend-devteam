"""
Manager Dashboard Routes — Staff approval, pending change requests summary.
Accessible via system-level permission guards (VIEW_DASHBOARD, MANAGE_USERS).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_temple_id, require_system_permission
from app.schemas.domain import TokenData
from app.services.registration_service import RegistrationService
from app.services.change_request_service import ChangeRequestService
from app.services.temple_profile_service import TempleProfileService
from app.core.response import api_response

router = APIRouter()


# ── Staff Approval ────────────────────────────────────────────────────

@router.get("/pending-staff")
async def list_pending_staff(
    current_user: TokenData = Depends(require_system_permission("MANAGE_USERS")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """List all pending staff registrations for the current temple."""
    staff = await RegistrationService.list_pending_staff(db, UUID(temple_id))
    staff_list = [s.model_dump() if hasattr(s, 'model_dump') else s for s in staff]
    return api_response(data=staff_list, message="Pending staff retrieved")


@router.post("/staff/{staff_id}/approve")
async def approve_staff(
    staff_id: UUID,
    current_user: TokenData = Depends(require_system_permission("MANAGE_USERS")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending staff registration."""
    result = await RegistrationService.approve_staff(
        db, staff_id, UUID(current_user.sub), UUID(temple_id)
    )
    return api_response(data=result.model_dump() if hasattr(result, 'model_dump') else result, message="Staff approved successfully")


@router.post("/staff/{staff_id}/reject")
async def reject_staff(
    staff_id: UUID,
    current_user: TokenData = Depends(require_system_permission("MANAGE_USERS")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """Reject a pending staff registration."""
    result = await RegistrationService.reject_staff(db, staff_id, UUID(current_user.sub), UUID(temple_id))
    return api_response(data=result.model_dump() if hasattr(result, 'model_dump') else result, message="Staff rejected successfully")


# ── Dashboard Summary ─────────────────────────────────────────────────

@router.get("/summary")
async def get_dashboard_summary(
    current_user: TokenData = Depends(require_system_permission("VIEW_DASHBOARD")),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    """
    Get a summary for the manager dashboard:
    - Comprehensive operational metrics (Income, Bookings, Staff)
    - Pending change requests count
    """
    from app.services.dashboard_service import DashboardService
    
    # Get standard dashboard stats
    stats = await DashboardService.get_summary(db, temple_id)
    
    # Get pending change requests count
    cr_items, cr_total = await ChangeRequestService.get_pending_approvals(db, UUID(temple_id), limit=1, offset=0)
    
    # Merge data
    data = {
        **stats,
        "pending_change_requests": cr_total,
        "temple_id": temple_id,
    }
    
    return api_response(data=data, message="Dashboard summary retrieved")


# ── My Temple Details (Draft System) ──────────────────────────────────

@router.get("/profile-draft")
async def get_profile_draft(
    current_user: TokenData = Depends(require_system_permission("VIEW_DASHBOARD")),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    """Get the current live profile and any pending draft."""
    tid = UUID(temple_id)
    live = await TempleProfileService.get_live_profile(db, tid)
    draft = await TempleProfileService.get_draft_profile(db, tid)
    
    return api_response(data={
        "live": live,
        "draft": draft
    }, message="Profile data retrieved")


@router.post("/profile-draft")
async def save_profile_draft(
    data: dict,
    current_user: TokenData = Depends(require_system_permission("VIEW_DASHBOARD")),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    """Save a draft for temple profile edits. Requires Admin approval."""
    tid = UUID(temple_id)
    uid = UUID(current_user.sub)
    draft = await TempleProfileService.save_draft(db, tid, uid, data)
    
    return api_response(data=draft, message="Draft saved successfully. Awaiting Admin approval.")
