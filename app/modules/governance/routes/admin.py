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
from app.modules.governance.schemas.leads import LeadCreate, LeadUpdate, LeadResponse, LeadListResponse, LeadConvert
from app.modules.governance.services.leads_service import LeadsService

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


# ── Lead Management CRM Module ───────────────────────────────────────

@router.post("/leads", response_model=LeadResponse, status_code=201)
async def create_crm_lead(
    payload: LeadCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """Create a new lead in the CRM pipeline."""
    lead = await LeadsService.create_lead(db, payload)
    await db.commit()
    return lead

@router.get("/leads", response_model=LeadListResponse)
async def list_crm_leads(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter leads by status (NEW, CONTACTED, etc.)"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """List all leads with pagination and filtering by status."""
    skip = (page - 1) * limit
    leads, total = await LeadsService.get_leads(db, skip=skip, limit=limit, status=status)
    return {
        "leads": leads,
        "total": total
    }

@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_crm_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """Fetch details of a single lead."""
    lead = await LeadsService.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@router.put("/leads/{lead_id}", response_model=LeadResponse)
async def update_crm_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """Update fields of an existing lead."""
    lead = await LeadsService.update_lead(db, lead_id, payload)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.commit()
    return lead

@router.delete("/leads/{lead_id}", status_code=204)
async def delete_crm_lead(
    lead_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """Delete a lead from the CRM pipeline."""
    success = await LeadsService.delete_lead(db, lead_id)
    if not success:
        raise HTTPException(status_code=404, detail="Lead not found")
    await db.commit()
    return None


@router.post("/leads/{lead_id}/convert")
async def convert_crm_lead(
    lead_id: UUID,
    payload: LeadConvert,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """Convert a lead record into a live registered Temple and manager account."""
    result = await LeadsService.convert_lead_to_temple(
        db=db,
        lead_id=lead_id,
        domain=payload.domain,
        manager_password=payload.manager_password,
        actor_id=UUID(current_user.sub)
    )
    await db.commit()
    return api_response(data=result, message="Lead successfully converted to registered temple")
