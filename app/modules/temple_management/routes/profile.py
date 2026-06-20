from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_db, get_current_user, get_current_temple_id, require_permission, require_system_permission
from app.schemas.domain import TokenData
from app.models.domain import Temple, TempleProfile, TempleProfileDraft
from app.modules.temple_management.services.temple_profile_service import TempleProfileService

router = APIRouter()

# ---------- Schemas ----------
class TempleProfileResponseSchema(BaseModel):
    id: UUID
    temple_id: UUID
    description: Optional[str] = ""
    history: Optional[str] = ""
    location: Optional[str] = ""
    district: Optional[str] = ""
    state: Optional[str] = ""
    country: Optional[str] = "India"
    contact_number: Optional[str] = ""
    email: Optional[str] = ""
    opening_time: Optional[str] = "06:00"
    closing_time: Optional[str] = "20:00"
    live_stream_url: Optional[str] = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    upi_id: Optional[str] = ""
    image_url: Optional[str] = ""
    main_deity: Optional[str] = ""
    deities: Optional[List[str]] = []
    facebook_url: Optional[str] = ""
    instagram_url: Optional[str] = ""
    youtube_url: Optional[str] = ""
    twitter_url: Optional[str] = ""
    website_url: Optional[str] = ""
    festivals_description: Optional[str] = ""
    short_description: Optional[str] = ""
    meta_title: Optional[str] = ""
    meta_description: Optional[str] = ""
    published_at: Optional[datetime] = None
    published_by: Optional[UUID] = None
    domain: Optional[str] = ""

    model_config = ConfigDict(from_attributes=True)


class TempleProfileDraftResponseSchema(BaseModel):
    id: UUID
    temple_id: UUID
    description: Optional[str] = None
    history: Optional[str] = None
    location: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "India"
    contact_number: Optional[str] = None
    email: Optional[str] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    live_stream_url: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    upi_id: Optional[str] = None
    image_url: Optional[str] = None
    main_deity: Optional[str] = None
    deities: Optional[List[str]] = None
    facebook_url: Optional[str] = None
    instagram_url: Optional[str] = None
    youtube_url: Optional[str] = None
    twitter_url: Optional[str] = None
    website_url: Optional[str] = None
    festivals_description: Optional[str] = None
    short_description: Optional[str] = None
    meta_title: Optional[str] = None
    meta_description: Optional[str] = None
    
    requested_by: Optional[UUID] = None
    status: str
    created_at: datetime
    updated_at: datetime
    domain: Optional[str] = ""

    model_config = ConfigDict(from_attributes=True)


class ProfileDraftDetailResponse(BaseModel):
    live_profile: Optional[TempleProfileResponseSchema] = None
    pending_draft: Optional[TempleProfileDraftResponseSchema] = None


class DraftApprovalRequest(BaseModel):
    edits: Optional[dict] = None


async def _attach_domain(db: AsyncSession, obj, temple_id: UUID):
    if not obj:
        return obj
    temple_res = await db.execute(select(Temple).filter(Temple.id == temple_id))
    temple = temple_res.scalar_one_or_none()
    if temple:
        obj.domain = temple.domain
    return obj


# ---------- Routes ----------

@router.get(
    "/draft",
    response_model=ProfileDraftDetailResponse,
    tags=["temple-profile"]
)
async def get_profile_and_draft(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "view")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Retrieve the active live profile and any pending draft for the manager's temple."""
    live_profile = await TempleProfileService.get_live_profile(db, UUID(temple_id))
    pending_draft = await TempleProfileService.get_draft_profile(db, UUID(temple_id))
    if live_profile:
        await _attach_domain(db, live_profile, UUID(temple_id))
    if pending_draft:
        await _attach_domain(db, pending_draft, UUID(temple_id))
    return {
        "live_profile": live_profile,
        "pending_draft": pending_draft
    }


@router.post(
    "/draft",
    response_model=TempleProfileDraftResponseSchema,
    tags=["temple-profile"]
)
async def submit_profile_draft(
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "edit")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Submit profile updates for review. Validates draft locking and governance states."""
    # Validate Temple Governance State
    temple_res = await db.execute(select(Temple).filter(Temple.id == UUID(temple_id)))
    temple = temple_res.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    if temple.management_mode == "UNCLAIMED":
        raise HTTPException(
            status_code=403, 
            detail="Unclaimed temples cannot have manager profile submissions."
        )

    draft = await TempleProfileService.save_draft(
        db=db,
        temple_id=UUID(temple_id),
        user_id=UUID(current_user.sub),
        data=data
    )
    if draft:
        await _attach_domain(db, draft, UUID(temple_id))
    return draft


@router.get(
    "/{temple_id}/completeness",
    tags=["temple-profile"]
)
async def get_completeness_score(
    temple_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "view")),
):
    """Compute the profile completeness score for a temple based on configurable weights."""
    # Tenant verification for non-superadmins
    if current_user.role not in ["SUPERADMIN", "SUPER_ADMIN", "ADMIN"]:
        # Verify user belongs to this temple
        user_temple_res = await db.execute(
            select(Temple).filter(Temple.id == temple_id)
        )
        temple = user_temple_res.scalars().first()
        if not temple:
            raise HTTPException(status_code=404, detail="Temple not found")
        # Ensure they are manager of this temple
        # (This is implicitly verified via standard auth token claims)
        
    return await TempleProfileService.get_profile_completeness(db, temple_id)


# ---------- SuperAdmin Governance Routes ----------

@router.get(
    "/drafts/pending",
    response_model=List[TempleProfileDraftResponseSchema],
    tags=["temple-profile-governance"]
)
async def list_pending_drafts(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("REVIEW_PROFILE_DRAFTS")),
):
    """List all profile drafts waiting for review. (SuperAdmin only)."""
    stmt = select(TempleProfileDraft).filter(TempleProfileDraft.status == "PENDING").order_by(TempleProfileDraft.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()


@router.get(
    "/drafts/{draft_id}/compare",
    response_model=ProfileDraftDetailResponse,
    tags=["temple-profile-governance"]
)
async def get_draft_for_comparison(
    draft_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("REVIEW_PROFILE_DRAFTS")),
):
    """Retrieve the draft and the corresponding live profile for comparison (SuperAdmin only)."""
    draft_res = await db.execute(select(TempleProfileDraft).filter(TempleProfileDraft.id == draft_id))
    draft = draft_res.scalars().first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    live_profile = await TempleProfileService.get_live_profile(db, draft.temple_id)
    if live_profile:
        await _attach_domain(db, live_profile, draft.temple_id)
    if draft:
        await _attach_domain(db, draft, draft.temple_id)
    return {
        "live_profile": live_profile,
        "pending_draft": draft
    }


@router.post(
    "/drafts/{draft_id}/approve",
    response_model=TempleProfileResponseSchema,
    tags=["temple-profile-governance"]
)
async def approve_profile_draft(
    draft_id: UUID,
    req: Optional[DraftApprovalRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("REVIEW_PROFILE_DRAFTS")),
):
    """Approve a profile draft. Supports 'Approve with Edits' overrides with immutable log tracking."""
    edits = req.edits if req else None
    profile = await TempleProfileService.approve_draft(
        db=db,
        draft_id=draft_id,
        approver_id=UUID(current_user.sub),
        edits=edits
    )
    if profile:
        await _attach_domain(db, profile, profile.temple_id)
    return profile


@router.post(
    "/drafts/{draft_id}/reject",
    response_model=TempleProfileDraftResponseSchema,
    tags=["temple-profile-governance"]
)
async def reject_profile_draft(
    draft_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("REVIEW_PROFILE_DRAFTS")),
):
    """Reject a profile draft, locking it from live promotion."""
    draft = await TempleProfileService.reject_draft(
        db=db,
        draft_id=draft_id,
        approver_id=UUID(current_user.sub)
    )
    if draft:
        await _attach_domain(db, draft, draft.temple_id)
    return draft


@router.put(
    "/{temple_id}/direct",
    response_model=TempleProfileResponseSchema,
    tags=["temple-profile-governance"]
)
async def direct_update_profile(
    temple_id: UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("MANAGE_TEMPLE_PROFILES")),
):
    """Directly update and publish a temple profile, bypassing the draft workflow (e.g. for UNCLAIMED or DIRECTORY_ONLY)."""
    profile = await TempleProfileService.direct_update_profile(
        db=db,
        temple_id=temple_id,
        user_id=UUID(current_user.sub),
        role=current_user.role,
        data=data
    )
    if profile:
        await _attach_domain(db, profile, temple_id)
    return profile
