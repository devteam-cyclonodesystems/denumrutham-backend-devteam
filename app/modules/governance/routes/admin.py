import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from typing import Optional
from uuid import UUID

from app.api.deps import get_db, require_system_permission
from app.models.domain import Temple
from app.models.onboarding import TempleRequest
from app.schemas.admin import AdminDashboardSummary, TempleListResponse, TempleListItem
from app.services.temple_profile_service import TempleProfileService
from app.core.response import api_response

logger = logging.getLogger("tms.api.admin")

router = APIRouter()

@router.get("/dashboard/summary", response_model=AdminDashboardSummary)
async def get_admin_summary(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("VIEW_ADMIN_DASHBOARD")),
):
    """
    Get platform-level metrics for the Super Admin dashboard.
    """
    # Total Temples
    total_temples = await db.scalar(select(func.count(Temple.id)))
    
    # Active Temples (APPROVED, ACTIVE, active and is_active=True)
    active_temples = await db.scalar(
        select(func.count(Temple.id)).filter(
            Temple.status.in_(["APPROVED", "ACTIVE", "active"]),
            Temple.is_active == True
        )
    )
    
    # Inactive Temples (is_active=False)
    inactive_temples = await db.scalar(
        select(func.count(Temple.id)).filter(
            Temple.is_active == False
        )
    )
    
    # Pending Approvals (from TempleRequest table)
    pending_approvals = await db.scalar(
        select(func.count(TempleRequest.id)).filter(TempleRequest.status == "PENDING")
    )
    
    # Rejected Approvals (from TempleRequest table)
    rejected_temples = await db.scalar(
        select(func.count(TempleRequest.id)).filter(TempleRequest.status == "REJECTED")
    )
    
    return api_response(data={
        "total_temples": total_temples or 0,
        "active_temples": active_temples or 0,
        "inactive_temples": inactive_temples or 0,
        "pending_approvals": pending_approvals or 0,
        "rejected_temples": rejected_temples or 0,
    }, message="Platform summary retrieved")

@router.get("/temples", response_model=TempleListResponse)
async def list_temples(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("VIEW_ADMIN_DASHBOARD")),
):
    """
    List all temples with pagination and filtering.
    """
    skip = (page - 1) * limit
    
    query = select(Temple).order_by(Temple.created_at.desc())
    
    if status_filter:
        status_val = status_filter.upper()
        if status_val == "ACTIVE":
            query = query.filter(Temple.status.in_(["APPROVED", "ACTIVE", "active"]), Temple.is_active == True)
        elif status_val == "INACTIVE":
            query = query.filter(Temple.is_active == False)
        elif status_val == "PENDING":
             query = query.filter(Temple.status.in_(["PENDING", "pending"]))
        elif status_val == "REJECTED":
             query = query.filter(Temple.status.in_(["REJECTED", "rejected"]))

    # Count total
    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0
    
    # Fetch items with joinedload to avoid N+1 if needed (though Temple has few relationships)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    temples = result.scalars().all()
    
    return {
        "items": temples,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }

@router.get("/temples/{temple_id}", response_model=TempleListItem)
async def get_temple_detail(
    temple_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("VIEW_ADMIN_DASHBOARD")),
):
    """
    Get detailed information for a specific temple.
    """
    result = await db.execute(
        select(Temple)
        .options(selectinload(Temple.profile))
        .filter(Temple.id == temple_id)
    )
    temple = result.scalar_one_or_none()
    
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")
        
    return temple


# ── Temple Profile Draft Approvals ───────────────────────────────────

@router.get("/profile-drafts")
async def list_pending_profile_drafts(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """List all pending temple profile update requests."""
    from app.models.domain import TempleProfileDraft
    result = await db.execute(
        select(TempleProfileDraft)
        .filter(TempleProfileDraft.status == "PENDING")
        .order_by(TempleProfileDraft.created_at.desc())
    )
    drafts = result.scalars().all()
    return api_response(data=drafts, message="Pending profile drafts retrieved")


@router.post("/profile-drafts/{draft_id}/approve")
async def approve_profile_draft(
    draft_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """Approve a temple profile update and promote to live."""
    profile = await TempleProfileService.approve_draft(db, draft_id, UUID(current_user.sub))
    return api_response(data=profile, message="Profile draft approved and live data updated")


@router.post("/profile-drafts/{draft_id}/reject")
async def reject_profile_draft(
    draft_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """Reject a temple profile update."""
    draft = await TempleProfileService.reject_draft(db, draft_id, UUID(current_user.sub))
    return api_response(data=draft, message="Profile draft rejected")


@router.post("/logs/telemetry", tags=["admin"])
async def log_telemetry(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint for frontend to log telemetry and errors.
    In a real system, this might save to a database or send to an external service.
    """
    logger.info(f"Frontend Telemetry Received: {payload}")
    return {"status": "logged"}
